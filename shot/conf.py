import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class Cam:
    url: str
    interval: int
    offset: int
    update_channel: bool
    render_daily: bool
    fps: int
    name: Optional[str] = ''


@dataclass_json
@dataclass
class Conf:
    bot_token: str
    log_file: str
    cameras: Dict[str, Cam]
    debug: bool
    db_uri: str
    tele_proxy: str = ''

    def __post_init__(self):
        self.cameras_dict = self.cameras
        self.cameras = list(self.cameras.values())
        for name, cam in self.cameras_dict.items():
            cam.name = name


def root_directory():
    root_path = os.path.dirname(__file__)
    while root_path and 'settings.template.yaml' not in os.listdir(root_path):
        root_path = os.path.dirname(root_path)
    return root_path


def get_settings_path():
    return os.path.join(root_directory(), 'settings.json')


def read():
    with open(get_settings_path(), 'r') as _settings:
        _settings = json.load(_settings)
        config = Conf.schema().load(_settings)
        config.root_dir = root_directory()
        return config
