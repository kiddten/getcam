import asyncio
import concurrent
import datetime
import hashlib
import io
import os
import subprocess as sp
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import aiohttp
import imageio
import pendulum
from PIL import Image
from loguru import logger
from moviepy.video.VideoClip import TextClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

from shot import conf
from shot.conf.model import Cam

if TYPE_CHECKING:
    from shot import gphotos

PIPE = -1
STDOUT = -2
DEVNULL = -3


class GrayCheckError(Exception):
    pass


def subprocess_call(cmd):
    """ Executes the given subprocess command."""
    join_cmd = ' '.join(cmd)
    logger.info(f'Running command {join_cmd}')

    popen_params = {
        "stdout": DEVNULL,
        "stderr": sp.PIPE,
        "stdin": DEVNULL
    }

    proc = sp.Popen(cmd, **popen_params)

    out, err = proc.communicate()  # proc.wait()
    proc.stderr.close()

    if proc.returncode:
        logger.warning(f'Command {join_cmd} returned error!')
        raise IOError(err.decode('utf8'))
    else:
        logger.success(f'Successfully finished {join_cmd}')

    del proc


@dataclass
class Movie:
    height: int
    width: int
    path: Path
    thumb: Path


@dataclass
class ImageItem:
    cam: Cam
    path: Path
    token: Optional[str] = None
    original_path: Optional[Path] = None
    original_token: Optional[str] = None

    def clear(self):
        logger.info(f'Remove {self.path}')
        self.path.unlink()
        if self.original_path:
            self.original_path.unlink()


@dataclass
class CamHandler:
    cam: Cam
    session: aiohttp.ClientSession
    agent: Optional['gphotos.GooglePhotosManager'] = None
    previous_image: Optional[str] = None
    path: Optional[Path] = None
    executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor()

    async def get_img(self, regular=True):
        logger.info(f'Img handler: {self.cam.name}')
        regular = 'regular' if regular else ''
        today = datetime.datetime.now().strftime('%d_%m_%Y')
        path = Path(conf.root_dir) / 'data' / self.cam.name
        path = path / regular / 'imgs' / today
        path.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now().strftime('%d_%m_%Y_%H-%M-%S')
        self.path = path / f'{now}.jpg'
        logger.info(f'Attempt to get img {self.path}')
        try:
            response = await self.session.get(self.cam.url)
        except Exception:
            logger.exception(f'Exception during getting img {self.path}')
            return
        if response.status != 200:
            body = await response.read()
            logger.warning(f'Can not get img {self.path}: response status {response.status} body: {body}')
            return
        data = await response.read()
        if not data:
            logger.warning(f'Empty file data {self.path}')
            return
        if self.is_the_same(data):
            logger.warning(f'Got the same image again {self.path}')
            return
        image = await self.save_img(data)
        logger.info(f'Finished with {self.path}')
        return image

    def is_the_same(self, data):
        if not self.previous_image:
            last = None
            try:
                last = sorted(self.path.parent.iterdir())[-1]
            except IndexError:
                pass
            if not last:
                self.previous_image = hashlib.md5(data).hexdigest()
                return False
            with open(last, 'rb') as _last:
                last_data = _last.read()
            self.previous_image = hashlib.md5(last_data).hexdigest()
        current = hashlib.md5(data).hexdigest()
        equal = current == self.previous_image
        if not equal:
            self.previous_image = current
        return equal

    async def save_img(self, data):
        if not self.cam.resize:
            with open(self.path, 'wb') as f:
                f.write(data)
            return ImageItem(self.cam, self.path)
        # path data/cam_name/imgs/dd_mm_yyyy/dd_mm_yyyy_timestamp.jpg
        original = self.path.parent.parent / 'original' / self.path.parent.name / self.path.name
        original.parent.mkdir(parents=True, exist_ok=True)
        with open(original, 'wb') as f:
            f.write(data)
        size = tuple(int(i) for i in self.cam.resize.split('x'))
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: resize_img(data, size, self.path))
        return ImageItem(self.cam, self.path, original_path=original)

    async def single_image_gray_check(self, item: ImageItem):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._single_image_gray_check(item.path))

    @staticmethod
    def _single_image_gray_check(path):
        logger.debug(f'Gray check {path}')
        try:
            image = imageio.imread(path)
        except Exception:
            logger.exception(f'Can not read file {path}')
            raise GrayCheckError
        if len(image.shape) < 3:
            convert_gray_to_rgb(path)
        return path

    async def get_img_and_sync(self, regular=True):
        image = await self.get_img(regular)
        if not image:
            return
        try:
            await self.single_image_gray_check(image)
        except GrayCheckError:
            logger.exception('Remove file due to check error')
            image.clear()
            return
        try:
            await self.agent.produce(image)
        except Exception:
            logger.exception(f'Error during image sync {image}')


def seq_middle(seq):
    r = len(seq) % 2
    if r == 0:
        return len(seq) // 2
    return (len(seq) - 1) // 2


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


def make_movie(cam: Cam, day: str, regular: bool = True):
    regular = 'regular' if regular else ''
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs' / day
    logger.info(f'Running make movie for {path}:{day}')
    sequence = sorted(str(p) for p in path.iterdir())
    movie_path = root / regular / 'clips' / f'{day}.mp4'
    cmd = [
        f'{conf.venv}/movie',
        '--cam_name',
        cam.name,
        '--day',
        day,
    ]
    if regular:
        cmd.append('--regular')
    try:
        subprocess_call(cmd)
    except Exception:
        logger.exception('Error during subprocess call')
        raise
    return Movie(100, 100, movie_path, sequence[seq_middle(sequence)])


def _make_movie(cam: Cam, day: str, regular: bool = True, executor=None):
    regular = 'regular' if regular else ''
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs' / day
    logger.info(f'Running make movie for {path}:{day}')
    # sequence = check_sequence_for_gray_images(sorted(str(p) for p in path.iterdir()), executor)
    sequence = sorted(str(p) for p in path.iterdir())
    txt_clip = make_txt_movie(sequence, cam.fps, executor=executor)
    logger.info(f'Composing clip for {path}:{day}')
    image_clip = ImageSequenceClip(sequence, fps=cam.fps)
    logger.info(f'ImageSequenceClip ready')
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    logger.info(f'CompositeVideoClip ready')
    movie_path = root / regular / 'clips' / f'{day}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(str(movie_path), audio=False)
    return Movie(clip.h, clip.w, movie_path, sequence[seq_middle(sequence)])


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
    sequence = check_sequence_for_gray_images(sequence, executor)
    txt_clip = make_txt_movie(sequence, 100, executor)
    logger.info(f'Composing clip for weekly movie ww{start.week_of_year}')
    image_clip = ImageSequenceClip(sequence, fps=100)
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    movie_path = root / 'regular' / 'weekly' / f'ww{start.week_of_year}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(str(movie_path), audio=False)
    logger.info(f'Finished with clip for weekly movie ww{start.week_of_year}')
    return Movie(clip.h, clip.w, movie_path, sequence[seq_middle(sequence)])


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
        root_path = root / cam / 'regular' / 'imgs'
        count, total_size = get_count_and_size(root_path / day)
        result['cameras'][cam] = {'size': total_size, 'count': count}
        total += total_size
        if conf.cameras[cam].resize:
            original_count, original_total_size = get_count_and_size(root_path / 'original' / day)
            result['cameras'][f'{cam}-original'] = {'size': original_total_size, 'count': original_count}
            total += original_total_size
    result['total'] = total
    result['free'] = get_free_disk_space()
    return result


def get_count_and_size(path: Path):
    if not path.exists():
        return 0, 0
    total_size = 0
    count = 0
    for p in path.iterdir():
        total_size += p.stat().st_size
        count += 1
    return count, total_size


def clear_cam_storage(day, cam):
    if not cam.clear:
        return
    root = Path(conf.root_dir) / 'data'
    root_path = root / cam.name / 'regular' / 'imgs'
    path = root_path / day
    logger.info(f'Clearing {path}')
    clear_path(path)
    if cam.resize:
        logger.info(f'Clearing {path}')
        path = root_path / 'original' / day
        clear_path(path)


def clear_path(path: Path):
    if not path.exists():
        return
    for p in path.iterdir():
        p.unlink()


def get_free_disk_space():
    statvfs = os.statvfs('/')
    return statvfs.f_frsize * statvfs.f_bavail
