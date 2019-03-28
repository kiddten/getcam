from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dataclasses_json import dataclass_json

from shot import conf
from shot.utils import part_path


@dataclass_json
@dataclass
class InlineKeyboardButton:
    text: str
    callback_data: str
    type: str = 'InlineKeyboardButton'


@dataclass_json
@dataclass
class Markup:
    inline_keyboard: List[List[InlineKeyboardButton]]
    type: str = 'InlineKeyboardMarkup'


@dataclass_json
@dataclass
class Options:
    cam: str
    markup: Markup = field(init=False)

    def __post_init__(self):
        self.markup = Markup(
            [
                [
                    InlineKeyboardButton(text='img', callback_data=f'img {self.cam}'),
                    InlineKeyboardButton(text='regular', callback_data=f'regular {self.cam}'),
                    InlineKeyboardButton(text='today', callback_data=f'today {self.cam}'),
                    InlineKeyboardButton(text='weekly', callback_data=f'weekly {self.cam}'),
                    InlineKeyboardButton(text='gphotos', callback_data=f'sync {self.cam}'),
                ],
                [InlineKeyboardButton(text='« Back', callback_data='back')],
            ]
        )


@dataclass_json
@dataclass
class Menu:
    main_menu: Markup = Markup(
        [[InlineKeyboardButton(text=cam.name, callback_data=f'select {cam.name}')] for cam in conf.cameras_list], )

    cam_options: Dict[str, Options] = field(
        default_factory=lambda: {cam.name: Options(cam.name) for cam in conf.cameras_list}
    )


@dataclass_json
@dataclass
class CamerasChannel:
    options: Markup = Markup(
        [[InlineKeyboardButton(text=cam.name, callback_data=f'choose_cam {cam.name}') for cam in conf.cameras_list], ])


@dataclass_json
@dataclass
class SyncFolders:
    cam: str
    folders: Markup = field(init=False)

    def __post_init__(self):
        root = Path(conf.root_dir) / 'data' / self.cam / 'regular' / 'imgs'
        self.folders = Markup(
            [
                [InlineKeyboardButton(text=item.name, callback_data=f'gsnc {part_path(item)}')] for item in
                sorted(root.iterdir())
            ]
        )
