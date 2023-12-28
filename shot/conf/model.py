from dataclasses import dataclass
from typing import Dict, List, Optional

from dataclasses_json import dataclass_json


class LightWeightToDictMixin:

    def as_dict(self):
        return self.__dict__


@dataclass_json
@dataclass
class GooglePhotos:
    @dataclass_json
    @dataclass
    class User(LightWeightToDictMixin):
        access_token: str
        refresh_token: str
        expires_in: int
        expires_at: str

    @dataclass_json
    @dataclass
    class Client(LightWeightToDictMixin):
        client_id: str
        client_secret: str
        scopes: List[str]

    user: User
    client: Client
    rate_limit: int
    album_batch_size: int
    raw_upload_timeout: int = 60
    handle_album_timeout: int = 3 * 60


@dataclass_json
@dataclass
class Cam:
    url: str
    offset: int
    fps: int = 25
    interval: int = 60
    update_channel: bool = True
    render_daily: bool = True
    clear: bool = True
    name: Optional[str] = None
    resize: Optional[str] = None
    description: Optional[str] = None


@dataclass_json
@dataclass
class Conf:
    # here is should be same content as in __init__.py
    bot_token: str
    log_file: str
    cameras: Dict[str, Cam]
    debug: bool
    db_uri: str
    vk_service: str
    vk_host: str
    venv: str
    stdout_log: Optional[bool] = False
    cameras_list: Optional[List[Cam]] = None
    tele_proxy: Optional[str] = None
    root_dir: Optional[str] = None
    google_photos: Optional[GooglePhotos] = None

    def __post_init__(self):
        self.cameras_list = list(self.cameras.values())
        for name, cam in self.cameras.items():
            cam.name = name
