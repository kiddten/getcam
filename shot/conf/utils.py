import os


def root_directory():
    root_path = os.path.dirname(__file__)
    # TODO fix lookup
    while root_path and 'settings.template.json' not in os.listdir(root_path):
        root_path = os.path.dirname(root_path)
    return root_path


def get_settings_path():
    return os.path.join(root_directory(), 'settings.json')
