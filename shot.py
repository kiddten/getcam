import datetime
import os
import shutil
import time

import requests
from loguru import logger
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

import conf

LOG_FILE = 'cam.log'
TODAY = datetime.datetime.now().strftime('%d_%m_%Y')

logger.add(LOG_FILE)


@logger.catch()
def get_img():
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    path = f'{conf.data_folder}/{today}'
    global TODAY
    if today != TODAY:
        make_movie(f'{conf.data_folder}/{TODAY}', f'{TODAY}')
        TODAY = today
    os.makedirs(path, exist_ok=True)
    img = requests.get(conf.cam_url, stream=True)
    now = datetime.datetime.now().strftime('%d_%m_%Y_%H-%M-%S')
    logger.info(f'Getting {now}')
    if img.status_code == 200:
        with open(f'{path}/{now}.jpg', 'wb') as f:
            img.raw.decode_content = True
            shutil.copyfileobj(img.raw, f)
    logger.info(f'Finished with {now}')
    time.sleep(conf.interval)


@logger.catch()
def make_movie(path, day):
    os.makedirs(conf.clips_folder, exist_ok=True)
    clip = ImageSequenceClip(sequence=path, fps=25)
    clip.write_videofile(f'{conf.clips_folder}/{day}.mp4', audio=False)


if __name__ == '__main__':
    while 1:
        get_img()

