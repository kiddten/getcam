import concurrent
import datetime
import logging
import os
from pathlib import Path

import imageio
from PIL import Image
from loguru import logger
from moviepy.video.VideoClip import TextClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

from shot import conf
from shot.conf.model import Cam

logger.add(Path(conf.root_dir) / conf.log_file)
logging.basicConfig(level=logging.DEBUG)


def convert_gray_to_rgb(path):
    logger.info(f'Converting {path} to RGB')
    image = Image.open(path)
    rgb_image = Image.new('RGB', image.size)
    rgb_image.paste(image)
    rgb_image.save(path, format=image.format)


def check_sequence_for_gray_images(sequence):
    logger.debug('Checking sequence for gray images')
    sequence = sorted([os.path.join(sequence, f) for f in os.listdir(sequence)])
    converted = []
    for item in sequence:
        try:
            image = imageio.imread(item)
        except Exception:
            logger.exception(f'Can not read file {item}')
            continue
        if len(image.shape) < 3:
            convert_gray_to_rgb(item)
        converted.append(item)
    return converted


def ts_clip(path):
    logger.debug(f'Adding timestamp to {path}')
    label = path.split('/')[-1].split('.')[0].replace('_', '.')
    txt = TextClip(txt=label, fontsize=20, color="red", font='Ubuntu-Bold', transparent=True)
    return txt.get_frame(0)


def make_txt_movie(sequence, fps):
    logger.debug('Creating txt movie..')
    executor = concurrent.futures.ThreadPoolExecutor()
    txt_clip = []
    for item in executor.map(ts_clip, sequence):
        txt_clip.append(item)
    return ImageSequenceClip(txt_clip, fps=fps)


def make_movie(cam: Cam, day: str, regular: bool = True):
    regular = 'regular' if regular else ''
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs' / day
    logger.info(f'Running make movie for {path}:{day}')
    sequence = check_sequence_for_gray_images(str(path))
    txt_clip = make_txt_movie(sequence, cam.fps)
    image_clip = ImageSequenceClip(sequence, fps=cam.fps)
    clip = CompositeVideoClip([image_clip, txt_clip.set_pos(('right', 'top'))], use_bgclip=True)
    movie_path = root / regular / 'clips' / f'{day}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    movie_path = str(movie_path)
    clip.write_videofile(movie_path, audio=False)
    return movie_path


async def get_img(cam: Cam, session, regular=True):
    logger.info(f'Img handler: {cam.name}')
    regular = 'regular' if regular else ''
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    path = Path(conf.root_dir) / 'data' / cam.name
    path = path / regular / 'imgs' / today
    path.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().strftime('%d_%m_%Y_%H-%M-%S')
    name = path / f'{now}.jpg'
    logger.info(f'Attempt to get img {name}')
    try:
        response = await session.get(cam.url)
    except Exception:
        logger.exception(f'Exception during getting img {name}')
        return
    if response.status == 200:
        data = await response.read()
        if not data:
            logger.warning(f'Empty file data {name}')
            return
        with open(name, 'wb') as f:
            f.write(data)
    logger.info(f'Finished with {name}')
    return str(name)
