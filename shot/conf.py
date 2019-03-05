import os

import yaml


def root_directory():
    root_path = os.path.dirname(__file__)
    while root_path and 'settings.template.yaml' not in os.listdir(root_path):
        root_path = os.path.dirname(root_path)
    return root_path


def get_settings_path():
    return os.path.join(root_directory(), 'settings.yaml')


def read():
    with open(get_settings_path(), 'r') as _:
        settings = yaml.load(_)
    for key in settings.keys():
        if key in ('log_file', 'data_folder', 'clips_folder'):
            settings[key] = os.path.join(root_directory(), settings[key])
        globals()[key] = settings[key]


read()
del globals()['read']
