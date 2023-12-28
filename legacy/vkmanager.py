import aiohttp
from loguru import logger

from shot import conf


class VKManagerError(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail


class VKManager:
    def __init__(self):
        self.host = conf.vk_host
        self.post_url = f'http://{self.host}/upload_item'
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def new_post(self, cam, path, name, description):
        logger.info(f'Pushing video to vk..')
        data = {
            'cam': cam,
            'path': path,
            'name': name,
            'description': description
        }
        result = await self.session.post(self.post_url, json=data)
        result_json = await result.json()
        if result.status != 200:
            raise VKManagerError(result.status, result_json['detail'])
        return result_json
