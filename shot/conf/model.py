from dataclasses import dataclass
from typing import Dict, List, Optional

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
    name: Optional[str] = None


@dataclass_json
@dataclass
class Conf:
    # here is should be same content as in __init__.py
    bot_token: str
    log_file: str
    cameras: Dict[str, Cam]
    debug: bool
    db_uri: str
    cameras_list: Optional[List[Cam]] = None
    tele_proxy: Optional[str] = None
    root_dir: Optional[str] = None

    def __post_init__(self):
        self.cameras_list = list(self.cameras.values())
        for name, cam in self.cameras.items():
            cam.name = name
