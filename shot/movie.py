import argparse
import logging
import sys
from concurrent import futures
from pathlib import Path

import imageio
from PIL import Image
from loguru import logger
from moviepy.video.VideoClip import TextClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

from shot import conf
from shot.conf.model import Cam


def init_logging():
    config = {
        'handlers': [
            {
                'sink': Path(conf.root_dir) / 'movie.log',
                'level': 'DEBUG',
                'rotation': '1 week'
            },
        ],
    }
    if conf.stdout_log:
        config['handlers'].append({'sink': sys.stdout, 'level': 'DEBUG'})
    logger.configure(**config)

    class InterceptHandler(logging.Handler):
        def emit(self, record):
            logger_opt = logger.opt(depth=6, exception=record.exc_info)
            logger_opt.log(record.levelname, record.getMessage())

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(InterceptHandler())
    logging.getLogger('backoff').setLevel(logging.DEBUG)


def ts_clip(path):
    logger.debug(f'Txt frame with timestamp {path}')
    label = path.split('/')[-1].split('.')[0].replace('_', '.')
    txt = TextClip(txt=label, fontsize=20, color="red", font='Ubuntu-Bold', transparent=True)
    return txt.get_frame(0)


def convert_gray_to_rgb(path):
    logger.info(f'Converting {path} to RGB')
    image = Image.open(path)
    rgb_image = Image.new('RGB', image.size)
    rgb_image.paste(image)
    rgb_image.save(path, format=image.format)


def make_txt_movie(sequence, fps):
    logger.debug('Creating txt movie..')
    txt_clip = []
    with futures.ThreadPoolExecutor() as pool:
        for item in pool.map(ts_clip, sequence):
            txt_clip.append(item)
    return ImageSequenceClip(txt_clip, fps=fps)


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


def check_sequence_for_gray_images(sequence):
    logger.debug('Checking sequence for gray images')
    converted = []
    with futures.ThreadPoolExecutor() as pool:
        for item in pool.map(image_gray_check, sequence):
            if item is not None:
                converted.append(item)
    return converted


def make_movie(cam: Cam, day: str, regular: bool = True):
    regular = 'regular' if regular else ''
    root = Path(conf.root_dir) / 'data' / cam.name
    path = root / 'regular' / 'imgs' / day
    logger.info(f'Running make movie for {path}:{day}')
    # sequence = check_sequence_for_gray_images(sorted(str(p) for p in path.iterdir()))
    sequence = sorted(str(p) for p in path.iterdir())
    txt_clip = make_txt_movie(sequence, cam.fps)
    logger.info(f'Composing clip for {path}:{day}')
    image_clip = ImageSequenceClip(sequence, fps=cam.fps)
    logger.info(f'ImageSequenceClip ready')
    clip = CompositeVideoClip([image_clip, txt_clip.set_position(('right', 'top'))], use_bgclip=True)
    logger.info(f'CompositeVideoClip ready')
    movie_path = root / regular / 'clips' / f'{day}.mp4'
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    clip.write_videofile(str(movie_path), audio=False)
    # return Movie(clip.h, clip.w, movie_path, sequence[seq_middle(sequence)])


def parse_args():
    parser = argparse.ArgumentParser(description='Make movie for given path')
    group = parser.add_argument_group('args necessary for movie')
    group.add_argument('--cam_name', help='cam name')
    group.add_argument('--day', help='day')
    group.add_argument('--regular', action='store_true', help='regular movie')
    return parser.parse_args()


def main():
    init_logging()
    args = parse_args()
    cam = args.cam_name
    if cam not in conf.cameras:
        logger.warning('Wrong cam name')
        return
    cam = conf.cameras[cam]
    regular = args.regular
    day = args.day
    make_movie(cam, day, regular)
