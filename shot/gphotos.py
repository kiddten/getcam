import asyncio
import time
from pathlib import Path

import aiohttp
import pendulum
from aiogoogle import Aiogoogle
from aiogoogle.sessions.aiohttp_session import AiohttpSession
from asyncio_throttle import Throttler
from loguru import logger

from shot import conf
from shot.conf import Cam


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


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

    async def start(self):
        logger.debug('Init session')
        self.client.active_session = AiohttpSession()
        self.session = self.client.active_session
        await self.refresh_token()

    async def stop(self):
        await self.session.close()

    async def raw_upload(self, path):
        logger.info(f'Uploading file {path}')
        with open(path, 'rb') as item:
            data = item.read()

        headers = {
            'Authorization': 'Bearer ' + self.client.user_creds.access_token,
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-File-Name': path,
            'X-Goog-Upload-Protocol': 'raw',
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            result = await session.post(self.upload_url, data=data)
            token = await result.text()
        logger.info(f'Finished uploading. File token: {token}')
        return token

    async def create_or_retrieve_album(self, photos, name):
        albums = await self.client.as_user(photos.albums.list())
        logger.info(f'Albums list: {albums}')
        if albums:
            for album in albums['albums']:
                if album['title'] == name:
                    album_id = album['id']
                    logger.info(f'Album {album_id} already exists')
                    return album_id
        album = {'album': {'title': name}}
        result = await self.client.as_user(photos.albums.create(json=album))
        album_id = result['id']
        return album_id

    async def upload_item(self, photos, album, token, description=None):
        logger.info(f'Adding f{token} to album {album}')
        data = {
            'newMediaItems': [
                {
                    'simpleMediaItem': {
                        'uploadToken': token
                    }
                },
            ],
            'albumId': album
        }
        if description:
            data['newMediaItems'][0]['description'] = description
        result = await self.client.as_user(photos.mediaItems.batchCreate(json=data))
        logger.info(f'Image f{token} successfully added to album {album}')
        return result

    async def main(self):
        await self.start()
        creds = await self.refresh_token()
        logger.critical(creds)
        self.client.user_creds = creds
        client = self.client
        photos = await client.discover('photoslibrary', 'v1')
        album_id = await self.create_or_retrieve_album(photos, 'test/bb')
        token = await self.raw_upload('/home/your/path')
        r = await self.upload_item(photos, album_id, token)
        await self.stop()

    async def _upload_raw_task(self, session, throttler, headers, path: Path):
        async with throttler:
            headers = {**headers}
            headers['X-Goog-Upload-File-Name'] = str(path.name)
            logger.info(f'Uploading file {path}')
            with open(path, 'rb') as item:
                data = item.read()
            result = await session.post(self.upload_url, headers=headers, data=data)
            response = await result.text()
            logger.info(f'Raw upload status {result.status} response for {path} : {response}')
        if result.status != 200:
            logger.warning(f'Error during uploading {path} {response}')
            return 'ERROR', str(path)
        return str(response), str(path)

    async def batch_raw_upload(self, path: Path):
        headers = {
            'Authorization': 'Bearer ' + self.client.user_creds.access_token,
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-Protocol': 'raw',
        }
        start_time = time.time()
        throttler = Throttler(rate_limit=conf.google_photos.rate_limit, period=60, retry_interval=.1)
        tokens_tuples = await self.upload_items(throttler, headers, sorted(path.iterdir()))
        tokens = []
        broken_files = 0
        for item in tokens_tuples:
            if item[0] == 'ERROR':
                logger.critical(f'ERROR with uploading {item[1]}')
                broken_files += 1
            else:
                tokens.append(item[0])
        logger.critical(f'BROKEN files count {broken_files}')
        empty_count = len([x for x in tokens if x is None])
        logger.critical(f'TOTAL TIMEEE::: {time.time() - start_time}')
        logger.critical(f'TOTAL LENGTH:: {len(tokens)} EMPTY TOKENS {empty_count}')
        return tokens_tuples, tokens

    async def upload_items(self, throttler, headers, items):
        connector = aiohttp.TCPConnector(limit=20)
        tasks = []
        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            for item in items:
                tasks.append(self._upload_raw_task(session, throttler, headers, item))
            tokens = await asyncio.gather(*tasks, return_exceptions=True)
        return tokens

    async def batch_upload_item(self, photos, album, tokens):
        results = []
        empty_counter = 0
        for chunk in chunks(tokens, 50):
            new_media_items = []
            for token in chunk:
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
            response = await self.client.as_user(photos.mediaItems.batchCreate(json=data))
            logger.info(f'Images count: {len(chunk)} successfully added to album {album}')
            for item in response['newMediaItemResults']:
                status = item['status']['message']
                if status != 'OK':
                    logger.success(item['uploadToken'])
                    logger.error(item['status'])
                else:
                    file_name = item['mediaItem']['filename']
                    logger.success(f'OK! {file_name}')
            results.extend(response['newMediaItemResults'])
        if empty_counter:
            logger.critical(f'Detected {empty_counter} empty tokens!')
        logger.info(f'All images: {len(tokens)} successfully added to album {album}')
        return [(item['uploadToken'], item['status']) for item in results]

    async def batch_upload(self, directory: Path):
        async with self.client as client:
            creds = await self.refresh_token(client)
        logger.critical(creds)
        self.client.user_creds = creds
        self.client.active_session = None
        async with self.client as client:
            photos = await client.discover('photoslibrary', 'v1')
            album_name = get_album_name(directory)
            album_id = await self.create_or_retrieve_album(photos, album_name)
            tokens_tuples, tokens = await self.batch_raw_upload(directory)
            await self.batch_upload_item(photos, album_id, tokens)

    async def refresh_token(self):
        creds = await self.client.oauth2.refresh(self.user_cred.as_dict(), self.client_cred.as_dict())
        self.client.user_creds = creds
        logger.info('Access_token refreshed')


class PhotosAgent(GooglePhotosManager):

    async def start(self):
        await super().start()
        self.photos = await self.client.discover('photoslibrary', 'v1')
        self.headers = {
            'Authorization': 'Bearer ' + self.client.user_creds.access_token,
            'Content-Type': 'application/octet-stream',
            'X-Goog-Upload-Protocol': 'raw',
        }
        self.raw_session = aiohttp.ClientSession(headers=self.headers)

    async def raw_upload(self, path):
        logger.info(f'Uploading file {path}')
        with open(path, 'rb') as item:
            data = item.read()
        headers = {**self.headers}
        headers['X-Goog-Upload-File-Name'] = str(path.name)
        result = await self.raw_session.post(self.upload_url, headers=headers, data=data)
        token = await result.text()
        logger.info(f'Finished uploading. File token: {token}')
        return token

    async def upload_img(self, cam: Cam, image: Path):
        day = pendulum.today()
        day = day.format('DD_MM_YYYY')
        album_name = f'{cam.name}-regular-imgs-{day}'
        if conf.debug:
            album_name = f'TEST-{album_name}'
        album_id = await self.create_or_retrieve_album(self.photos, album_name)
        token = await self.raw_upload(image)
        await self.upload_item(self.photos, album_id, token)
