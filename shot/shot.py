import asyncio
import concurrent
import datetime
import logging
import os

import imageio
from PIL import Image
from aiotg import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from moviepy.video.VideoClip import TextClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

import shot.conf as conf


class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(raw=True)
        logger_opt.log(record.levelno, record.getMessage())


logging.getLogger(None).addHandler(InterceptHandler())

logger.add(conf.log_file)
logging.basicConfig(level=logging.DEBUG)
bot = Bot(conf.bot_token, proxy=conf.tele_proxy)


def convert_gray_to_rgb(path):
    logger.info(f'Converting {path} to RGB')
    image = Image.open(path)
    rgb_image = Image.new('RGB', image.size)
    rgb_image.paste(image)
    rgb_image.save(path, format=image.format)


def check_sequence_for_gray_images(sequence):
    logger.debug('Checking sequence for gray images')
    sequence = sorted([os.path.join(sequence, f) for f in os.listdir(sequence)])
    for item in sequence:
        image = imageio.imread(item)
        if len(image.shape) < 3:
            convert_gray_to_rgb(item)
    return sequence


def ts_clip(path):
    logger.debug(f'Adding timestamp to {path}')
    label = path.split('/')[-1].split('.')[0].replace('_', '.')
    txt = TextClip(txt=label, fontsize=20, color="red", font='Ubuntu-Bold', transparent=True)
    return txt.get_frame(0)


def make_txt_movie(sequence):
    logger.debug('Creating txt movie..')
    executor = concurrent.futures.ThreadPoolExecutor()
    txt_clip = []
    for item in executor.map(ts_clip, sequence):
        txt_clip.append(item)
    return ImageSequenceClip(txt_clip, fps=25)


@logger.catch()
def make_movie(path, day):
    logger.info(f'Running make movie for {path}:{day}')
    os.makedirs(conf.clips_folder, exist_ok=True)
    sequence = check_sequence_for_gray_images(path)
    txt_clip = make_txt_movie(sequence)
    image_clip = ImageSequenceClip(sequence, fps=25)
    clip = CompositeVideoClip([image_clip, txt_clip.set_pos(('right', 'top'))], use_bgclip=True)
    name = f'{conf.clips_folder}/{day}.mp4'
    clip.write_videofile(name, audio=False)
    return name


@logger.catch()
async def get_img():
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    path = f'{conf.data_folder}/{today}'
    os.makedirs(path, exist_ok=True)
    now = datetime.datetime.now().strftime('%d_%m_%Y_%H-%M-%S')
    async with bot.session.get(conf.cam_url) as response:
        if response.status == 200:
            data = await response.read()
            name = f'{path}/{now}.jpg'
            with open(name, 'wb') as f:
                f.write(data)
    logger.info(f'Finished with {now}')
    return name


async def periodic_get_img():
    while True:
        await get_img()
        await asyncio.sleep(conf.interval)


@bot.command('/today')
async def today_movie(chat, match):
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{today}', f'{today}')
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command('/yesterday')
async def yesterday_movie(chat, match):
    day = datetime.datetime.now() - datetime.timedelta(days=1)
    day = day.strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{day}', f'{day}')
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command(r'/mov (.+)')
async def mov(chat, match):
    day = match.group(1)
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{day}', f'{day}')
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command('/img')
async def img(chat, match):
    image = await get_img()
    with open(image, 'rb') as image:
        await chat.send_photo(image)


async def daily_movie():
    day = datetime.datetime.now() - datetime.timedelta(days=1)
    day = day.strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{day}', f'{day}')


async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_movie, 'cron', hour=0, minute=1)
    scheduler.start()

    pe = asyncio.create_task(periodic_get_img())
    bot_loop = asyncio.create_task(bot.loop())
    await asyncio.wait([pe, bot_loop])


def run():
    asyncio.run(main())


if __name__ == '__main__':
    run()
