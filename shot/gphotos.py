import asyncio
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiogoogle
import aiohttp
import async_timeout
import backoff
import pendulum
from aiogoogle import Aiogoogle
from aiogoogle.sessions.aiohttp_session import AiohttpSession
from async_lru import alru_cache
from asyncio_throttle import Throttler
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


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def fatal_code(api_error: aiogoogle.excs.HTTPError):
    return api_error.res.status_code == 400


class _Aiogoogle(Aiogoogle):

    async def send(self, *args, **kwargs):
        return await self.active_session.send(*args, **kwargs)


@dataclass
class PhotoItem:
    path: Path
    token: Optional[str] = None
    status: Optional[str] = None


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
        self.albums_cache = None

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

    async def produce(self, image: ImageItem):
        logger.debug(f'Putting item to queue {image}')
        await self.queue.put(image)

    async def consume(self):
        async def step():
            item = await self.queue.get()
            try:
                async with async_timeout.timeout(conf.google_photos.raw_upload_timeout):
                    await self.upload_image_item(item)
            except asyncio.TimeoutError:
                logger.warning(f'Timed out error during upload {item.path}')
            self.items[item.cam.name].append(item)
            await self.handle_queue_body()

        while not self._stopped.is_set():
            logger.info('Consuming item..')
            try:
                async with async_timeout.timeout(60 * 5):
                    await step()
            except asyncio.TimeoutError:
                logger.exception('Queue get step body hangs')
            except Exception:
                logger.exception('Unhandled exception during gphotos consume step')

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
                try:
                    async with async_timeout.timeout(conf.google_photos.handle_album_timeout):
                        await self.handle_album(photos)
                except asyncio.TimeoutError:
                    logger.warning(f'Timed out error during handling batch for {cam}')
                    return
                except Exception:
                    logger.exception('Unhandled exception during gphotos queue step')
                logger.success(f'Finished with batch for {cam}')
                for _ in range(len(photos)):
                    self.queue.task_done()
                photos[:] = []

    async def handle_album(self, photos: List[ImageItem]):
        items = defaultdict(list)
        for item in photos:
            items[item.path.parent].append(item)
        if len(items) > 1:
            logger.info('Detected image items from several folders')
        for image_items in items.values():
            await self._handle_album(image_items)

    async def _handle_album(self, photos: List[ImageItem]):
        album_name = get_album_name(photos[0].path.parent)
        album_id = await self.create_or_retrieve_album(album_name)
        logger.info(f'Going to upload items to album {album_id}')
        await self.batch_upload_album(album_id, photos)
        if photos[0].cam.resize:
            logger.info(f'Going to upload resized items to album {album_id}')
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
        if empty_counter == len(new_media_items):
            logger.warning(f'There are no new items for {album}')
            return
        response = await self.media_items_batch_create(data)
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

    async def photos_albums_list(self):
        albums = []
        first_page = await self.client.as_user(self.photos.albums.list(pageSize=50))
        albums.extend(first_page['albums'])
        if not first_page.get('nextPageToken'):
            return albums
        next_page = first_page['nextPageToken']
        while next_page:
            logger.info('Getting next albums page..')
            page = await self.client.as_user(self.photos.albums.list(pageSize=50, pageToken=next_page))
            albums.extend(page['albums'])
            try:
                next_page = page['nextPageToken']
            except KeyError:
                next_page = None
        logger.info(f'Got info about {len(albums)} albums')
        return albums

    @alru_cache(maxsize=48)
    async def create_or_retrieve_album(self, name):
        cache_updated = False
        if not self.albums_cache:
            self.albums_cache = await self.photos_albums_list()
            cache_updated = True
        if self.albums_cache:
            for album in self.albums_cache:
                if album['title'] == name:
                    album_id = album['id']
                    logger.info(f'Album {album_id} -- {name} already exists')
                    return album_id
        if not cache_updated:
            self.albums_cache = await self.photos_albums_list()
        if self.albums_cache:
            for album in self.albums_cache:
                if album['title'] == name:
                    album_id = album['id']
                    logger.info(f'Album {album_id} -- {name} already exists')
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
        logger.info(f'Finished uploading {path}. File token: {token}')
        return token

    async def album_stats(self, day=None):
        day = day or pendulum.today()
        day = day.format('DD_MM_YYYY')
        root = Path(conf.root_dir) / 'data'
        result = {}
        for cam in conf.cameras.keys():
            root_path = root / cam / 'regular' / 'imgs'
            count = await self.album_media_items_count(root_path / day)
            result[cam] = count
            if conf.cameras[cam].resize:
                count = await self.album_media_items_count(root_path / 'original' / day)
                result[f'{cam}-original'] = count
        return result

    async def album_media_items_count(self, name):
        # https://photoslibrary.googleapis.com/v1/albums/{albumId}
        album_name = get_album_name(name)
        album_id = await self.create_or_retrieve_album(album_name)
        response = await self.client.as_user(self.photos.albums.get(albumId=album_id, fields='mediaItemsCount'))
        try:
            response = response['mediaItemsCount']
        except TypeError:
            response = 0
        return response

    async def album_info(self, album_id):
        logger.info(f'Getting album content for {album_id}')
        # POST https://photoslibrary.googleapis.com/v1/mediaItems:search
        items = []
        data = {'albumId': album_id, 'pageSize': 100}
        first_page = await self.client.as_user(self.photos.mediaItems.search(json=data))
        if not first_page:
            return items
        for item in first_page['mediaItems']:
            items.append(item['filename'])
        if not first_page.get('nextPageToken'):
            return items
        logger.success(len(items))
        next_page = first_page['nextPageToken']
        while next_page:
            data['pageToken'] = next_page
            page = await self.client.as_user(self.photos.mediaItems.search(json=data))
            for item in page['mediaItems']:
                items.append(item['filename'])
            logger.success(len(items))
            try:
                next_page = page['nextPageToken']
            except KeyError:
                next_page = None
        return items

    async def check_album(self, cam: 'conf.Cam', day):
        root = Path(conf.root_dir) / 'data'
        path_cam = root / cam.name / 'regular' / 'imgs'
        path = path_cam / day
        logger.info(f'Checking album {path}')
        await self._check_album(path, cam)
        if cam.resize:
            path = path_cam / 'original' / day
            logger.info(f'Checking album {path}')
            await self._check_album(path, cam)

    async def _check_album(self, path, cam):
        if not path.exists():
            logger.info(f'Skipping check {path} since dir is not exists')
            return
        album_name = get_album_name(path)
        # TODO dont create album
        album_id = await self.create_or_retrieve_album(album_name)
        album_items = await self.album_info(album_id)
        logger.info(f'Remote list: {album_items}')
        local_items = [item.name for item in path.iterdir()]
        logger.info(f'Local list: {local_items}')
        diff = set(local_items) - set(album_items)
        items_in_queue = [item.path.name for item in self.items[cam.name]]
        logger.info(f'Queue items list: {items_in_queue}')
        diff = diff - set(items_in_queue)
        logger.info(f'There are {len(diff)} items should be uploaded {diff}')
        if diff:
            await self.upload_missing_images(album_id, [path / item for item in diff])

    async def upload_missing_images(self, album_id: str, images: List[Path]):
        photo_items = [PhotoItem(image) for image in images]
        await self.batch_raw_upload(photo_items)
        await self.batch_upload_item(album_id, photo_items)

    async def batch_raw_upload(self, images: List[PhotoItem]):
        throttler = Throttler(rate_limit=conf.google_photos.rate_limit, period=60, retry_interval=.1)
        await self.upload_items(throttler, images)

    async def upload_items(self, throttler, items: List[PhotoItem]):
        connector = aiohttp.TCPConnector(limit=20)
        tasks = []
        async with aiohttp.ClientSession(connector=connector, headers=self.headers) as session:
            for item in items:
                tasks.append(self._upload_raw_task(session, throttler, item))
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _upload_raw_task(self, session, throttler, item: PhotoItem):
        async with throttler:
            logger.info(f'Uploading file {item.path}')
            headers = {**self.headers}
            headers['X-Goog-Upload-File-Name'] = str(item.path.name)
            headers['Authorization'] = f'Bearer {self.client.user_creds.access_token}'
            with open(item.path, 'rb') as _item:
                data = _item.read()
            result = await session.post(self.upload_url, headers=headers, data=data)
            if result.status != 200:
                body = await result.read()
                logger.warning(f'Error during raw uploading {item.path} {body}')
                item.error = True
                return
            token = await result.text()
            logger.success(f'Got token for {item.path} : {token}')
        item.token = token

    async def batch_upload_item(self, album_id, photo_items: List[PhotoItem]):
        results = []
        empty_counter = 0
        for chunk in chunks(photo_items, 50):
            new_media_items = []
            for item in chunk:
                if item.token:
                    new_media_items.append({'simpleMediaItem': {'uploadToken': item.token}})
                else:
                    logger.warning('Empty token!')
                    empty_counter += 1
            data = {
                'newMediaItems': new_media_items,
                'albumId': album_id
            }
            response = await self.media_items_batch_create(data)
            # try:
            #     response = await self.client.as_user(self.photos.mediaItems.batchCreate(json=data))
            # except aiogoogle.excs.HTTPError:
            #     logger.exception('Got HTTP error during API batch create')
            #     logger.info(f'Failed to sync following items {photo_items}')
            #     return
            count = 0
            for item in response['newMediaItemResults']:
                status = item['status']['message']
                if status != 'OK':
                    logger.success(item['uploadToken'])
                    logger.error(item['status'])
                else:
                    file_name = item['mediaItem']['filename']
                    logger.success(f'OK! {file_name}')
                    count += 1
            logger.info(f'Images {count} successfully added to album {album_id}')
            results.extend(response['newMediaItemResults'])
        if empty_counter:
            logger.critical(f'Detected {empty_counter} empty tokens!')
        logger.info(f'Finished handling batch {len(photo_items)} with album {album_id}')

    @backoff.on_exception(backoff.expo, aiogoogle.excs.HTTPError, max_time=60 * 5, giveup=fatal_code)
    async def media_items_batch_create(self, data):
        return await self.client.as_user(self.photos.mediaItems.batchCreate(json=data))
