import datetime
import logging
from pathlib import Path

import imageio
import pendulum
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
    logger.debug(f'Txt frame with timestamp {path}')
    label = path.split('/')[-1].split('.')[0].replace('_', '.')
    txt = TextClip(txt=label, fontsize=20, color="red", font='Ubuntu-Bold', transparent=True)
    return txt.get_frame(0)


def make_txt_movie(sequence, fps, executor):
    logger.debug('Creating txt movie..')
    txt_clip = []
    for item in executor.map(ts_clip, sequence):
        txt_clip.append(item)
    return ImageSequenceClip(txt_clip, fps=fps)


def make_movie(cam: Cam, day: str, regular: bool = True, executor=None):
    regular = 'regular' if regular else ''
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs' / day
    logger.info(f'Running make movie for {path}:{day}')
    sequence = check_sequence_for_gray_images(sorted(str(p) for p in path.iterdir()))
    txt_clip = make_txt_movie(sequence, cam.fps, executor=executor)
    image_clip = ImageSequenceClip(sequence, fps=cam.fps)
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    movie_path = root / regular / 'clips' / f'{day}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    movie_path = str(movie_path)
    clip.write_videofile(movie_path, audio=False)
    return movie_path


def make_weekly_movie(cam: Cam, executor):
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs'
    start = pendulum.yesterday()
    logger.info(f'Running make weekly movie for ww{start.week_of_year}')
    week_ago = start.subtract(weeks=1).date()
    sequence = []
    morning = pendulum.Time(6)
    evening = pendulum.Time(18)
    for day in sorted(list(path.iterdir()), key=lambda x: pendulum.from_format(x.name, 'DD_MM_YYYY')):
        if pendulum.from_format(day.name, 'DD_MM_YYYY').date() > week_ago:
            for img in sorted(day.iterdir()):
                t_img = img.name.split('.')[0]
                t_img = pendulum.from_format(t_img, 'DD_MM_YYYY_HH-mm-ss').time()
                if morning < t_img < evening:
                    sequence.append(str(img))
    sequence = check_sequence_for_gray_images(sequence)
    txt_clip = make_txt_movie(sequence, 100, executor)
    logger.info(f'Composing clip for weekly movie ww{start.week_of_year}')
    image_clip = ImageSequenceClip(sequence, fps=100)
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    movie_path = root / 'regular' / 'weekly' / f'ww{start.week_of_year}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    movie_path = str(movie_path)
    clip.write_videofile(movie_path, audio=False)
    logger.info(f'Finished with clip for weekly movie ww{start.week_of_year}')
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


def stats(day=None):
    day = day or pendulum.today()
    day = day.format('DD_MM_YYYY')
    root = Path(conf.root_dir) / 'data'
    result = {}
    for cam in conf.cameras.keys():
        path = root / cam / 'regular' / 'imgs' / day
        result[cam] = len(list(path.iterdir()))
    return result
