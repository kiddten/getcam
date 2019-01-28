import yaml


def read():
    with open('settings.yaml', 'r') as _:
        settings = yaml.load(_)
    for key in settings.keys():
        globals()[key] = settings[key]


read()
del globals()['read']
