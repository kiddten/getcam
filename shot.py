import datetime
import os
import shutil
import time

import requests
from loguru import logger

import conf

LOG_FILE = 'cam.log'

logger.add(LOG_FILE)


@logger.catch()
def get_img():
    os.makedirs(conf.images_folder, exist_ok=True)
    img = requests.get(conf.cam_url, stream=True)
    now = datetime.datetime.now().strftime('%d_%m_%Y_%H-%M-%S')
    logger.info(f'Getting {now}')
    if img.status_code == 200:
        with open(f'{conf.images_folder}/{now}.jpg', 'wb') as f:
            img.raw.decode_content = True
            shutil.copyfileobj(img.raw, f)
    logger.info(f'Finished with {now}')
    time.sleep(conf.interval)


if __name__ == '__main__':
    while 1:
        get_img()

# from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
#
# clip = ImageSequenceClip(sequence='remote/imgs', fps=25)
# clip.write_videofile('mpche2.mp4', audio=False)
