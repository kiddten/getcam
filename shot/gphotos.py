import asyncio
from collections import defaultdict
from pathlib import Path
from typing import List

import aiohttp
from aiogoogle import Aiogoogle
from aiogoogle.sessions.aiohttp_session import AiohttpSession
from async_lru import alru_cache
from loguru import logger

from shot import conf
from shot.shooter import ImageItem


def get_album_name(path: Path):
    name = [path.name]
    for item in path.parents:
        if item.name == 'data':
            break
        name.append(item.name)
    name = '-'.join(reversed(name))
    if conf.debug:
        name = f'TEST-{name}'
    return name


class _Aiogoogle(Aiogoogle):

    async def send(self, *args, **kwargs):
        return await self.active_session.send(*args, **kwargs)


class GooglePhotosManager:
    def __init__(self):
        self.client_cred = conf.google_photos.client
        self.user_cred = conf.google_photos.user
        self.client = _Aiogoogle(client_creds=self.client_cred.as_dict(), user_creds=self.user_cred.as_dict())
        self.upload_url = 'https://photoslibrary.googleapis.com/v1/uploads'
        self.session = None
        self.photos = None
        self.headers = {
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-Protocol': 'raw',
        }
        self.raw_session = None
        self.queue = None
        self._stopped = asyncio.Event()
        self.consumer = None
        self.items = defaultdict(list)

    async def start(self):
        logger.debug('Init session')
        self.client.active_session = AiohttpSession()
        self.session = self.client.active_session
        await self.refresh_token()
        self.photos = await self.client.discover('photoslibrary', 'v1')
        self.headers['Authorization'] = f'Bearer {self.client.user_creds.access_token}'
        self.raw_session = aiohttp.ClientSession(headers=self.headers)
        self.queue = asyncio.Queue()

    async def stop(self):
        logger.info('Stopping photos manager..')
        self._stopped.set()
        self.consumer.cancel()
        await self.handle_queue_body(shutdown=True)
        await self.session.close()
        await self.raw_session.close()

    async def refresh_token(self):
        creds = await self.client.oauth2.refresh(self.user_cred.as_dict(), self.client_cred.as_dict())
        self.client.user_creds = creds
        logger.info('Access_token refreshed')

    async def produce(self, cam, image: ImageItem):
        logger.debug(f'Putting item to queue {image}')
        await self.queue.put(image)

    async def consume(self):
        while not self._stopped.is_set():
            logger.info('Consuming item..')
            item = await self.queue.get()
            await self.upload_image_item(item)
            self.items[item.cam.name].append(item)
            await self.handle_queue_body()

    async def upload_image_item(self, item: ImageItem):
        item.token = await self.raw_upload(item.path)
        if not item.cam.resize:
            return
        item.original_token = await self.raw_upload(item.original_path)

    async def handle_queue_body(self, shutdown=False):
        if shutdown:
            logger.info('Graceful photos manager shutdown..')
        for cam, photos in self.items.items():
            if len(photos) >= conf.google_photos.album_batch_size or (shutdown and len(photos) > 0):
                logger.info(f'Going to handle batch for {cam}')
                await self.handle_album(photos)
                logger.success(f'Finished with batch for {cam}')
                for _ in range(len(photos)):
                    self.queue.task_done()
                self.items[cam][:] = []

    async def handle_album(self, photos: List[ImageItem]):
        album_name = get_album_name(photos[0].path.parent)
        album_id = await self.create_or_retrieve_album(album_name)
        await self.batch_upload_album(album_id, photos)
        if photos[0].cam.resize:
            album_name = get_album_name(photos[0].original_path.parent)
            album_id = await self.create_or_retrieve_album(album_name)
            await self.batch_upload_album(album_id, photos, token_get='original_token')

    async def batch_upload_album(self, album, images: List[ImageItem], token_get='token'):
        empty_counter = 0
        new_media_items = []
        for image in images:
            token = getattr(image, token_get)
            if token:
                new_media_items.append({'simpleMediaItem': {'uploadToken': token}})
            else:
                logger.warning('Empty token!')
                empty_counter += 1
        data = {
            'newMediaItems': new_media_items,
            'albumId': album
        }
        # TODO add retry when aborted
        response = await self.client.as_user(self.photos.mediaItems.batchCreate(json=data))
        logger.success(f'Images count: {len(new_media_items)} successfully added to album {album}')
        for item in response['newMediaItemResults']:
            status = item['status']['message']
            if status != 'OK':
                logger.info(item['uploadToken'])
                logger.error(item['status'])
            else:
                file_name = item['mediaItem']['filename']
                logger.success(f'OK! {file_name}')
        results = response['newMediaItemResults']
        if empty_counter:
            logger.critical(f'Detected {empty_counter} empty tokens!')
        logger.info(f'Images: {len(results)} successfully added to album {album}')

    async def loop(self):
        self.consumer = asyncio.create_task(self.consume())
        await self.queue.join()

    @alru_cache(maxsize=24)
    async def create_or_retrieve_album(self, name):
        albums = await self.client.as_user(self.photos.albums.list())
        if albums:
            for album in albums['albums']:
                if album['title'] == name:
                    album_id = album['id']
                    logger.info(f'Album {album_id} already exists')
                    return album_id
        album = {'album': {'title': name}}
        result = await self.client.as_user(self.photos.albums.create(json=album))
        album_id = result['id']
        logger.info(f'Album {name} -- album id {album_id}')
        return album_id

    async def raw_upload(self, path):
        logger.info(f'Uploading file {path}')
        with open(path, 'rb') as item:
            data = item.read()
        headers = {**self.headers}
        headers['X-Goog-Upload-File-Name'] = str(path.name)
        headers['Authorization'] = f'Bearer {self.client.user_creds.access_token}'
        result = await self.raw_session.post(self.upload_url, headers=headers, data=data)
        token = await result.text()
        logger.info(f'Finished uploading. File token: {token}')
        return token
