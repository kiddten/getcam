import asyncio
import datetime
import io
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


def convert_gray_to_rgb(path):
    logger.info(f'Converting {path} to RGB')
    image = Image.open(path)
    rgb_image = Image.new('RGB', image.size)
    rgb_image.paste(image)
    rgb_image.save(path, format=image.format)


def image_gray_check(path):
    logger.debug(f'Gray check {path}')
    try:
        image = imageio.imread(path)
    except Exception:
        logger.exception(f'Can not read file {path}')
        return
    if len(image.shape) < 3:
        convert_gray_to_rgb(path)
    return path


def check_sequence_for_gray_images(sequence, executor):
    logger.debug('Checking sequence for gray images')
    converted = []
    for item in executor.map(image_gray_check, sequence):
        if item is not None:
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
    sequence = check_sequence_for_gray_images(sorted(str(p) for p in path.iterdir()), executor)
    txt_clip = make_txt_movie(sequence, cam.fps, executor=executor)
    logger.info(f'Composing clip for {path}:{day}')
    image_clip = ImageSequenceClip(sequence, fps=cam.fps)
    logger.info(f'ImageSequenceClip ready')
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    logger.info(f'CompositeVideoClip ready')
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
        image = await save_img(cam, name, data)
    logger.info(f'Finished with {name}')
    return str(image)


async def save_img(cam: Cam, path, data):
    if not cam.resize:
        with open(path, 'wb') as f:
            f.write(data)
        return path
    # path data/cam_name/imgs/dd_mm_yyyy/dd_mm_yyyy_timestamp.jpg
    original = path.parent.parent / 'original' / path.parent.name / path.name
    original.parent.mkdir(parents=True, exist_ok=True)
    with open(original, 'wb') as f:
        f.write(data)
    size = tuple(int(i) for i in cam.resize.split('x'))
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: resize_img(data, size, path))
    return original


def resize_img(data, size, path):
    logger.debug(f'Resizing image {path}')
    image = Image.open(io.BytesIO(data))
    image.thumbnail(size, Image.ANTIALIAS)
    image.save(path, format='JPEG')


def stats(day=None):
    day = day or pendulum.today()
    day = day.format('DD_MM_YYYY')
    logger.info(f'Calculating file stats {day}')
    root = Path(conf.root_dir) / 'data'
    result = {'cameras': {}}
    total = 0
    for cam in conf.cameras.keys():
        total_size = 0
        count = 0
        path = root / cam / 'regular' / 'imgs' / day
        for p in path.iterdir():
            total_size += p.stat().st_size
            count += 1
        result['cameras'][cam] = {'size': total_size, 'count': count}
        total += total_size
    result['total'] = total
    return result
