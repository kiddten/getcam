import asyncio
import datetime
import logging
import os

import imageio
from PIL import Image
from aiotg import Bot
from loguru import logger
from moviepy.video.io.ImageSequenceClip import ImageSequenceClip

import conf

LOG_FILE = 'cam.log'
logger.add(LOG_FILE)
logging.basicConfig(level=logging.DEBUG)
bot = Bot(conf.bot_token, proxy=conf.tele_proxy)


def convert_gray_to_rgb(path):
    logger.info('Converting f{path} to RGB')
    image = Image.open(path)
    rgb_image = Image.new('RGB', image.size)
    rgb_image.paste(image)
    rgb_image.save(path, format=image.format)


def check_sequence_for_gray_images(sequence):
    sequence = sorted([os.path.join(sequence, f) for f in os.listdir(sequence)])
    for item in sequence:
        image = imageio.imread(item)
        if len(image.shape) < 3:
            convert_gray_to_rgb(item)
    return sequence


@logger.catch()
def make_movie(path, day):
    logger.info(f'Running make movie for {path}:{day}')
    os.makedirs(conf.clips_folder, exist_ok=True)
    sequence = check_sequence_for_gray_images(path)
    clip = ImageSequenceClip(sequence, fps=25)
    name = f'{conf.clips_folder}/{day}.mp4'
    clip.write_videofile(name, audio=False)
    return name


@logger.catch()
async def get_img():
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    path = f'{conf.data_folder}/{today}'
    loop = asyncio.get_event_loop()
    _today = loop.TODAY
    if today != _today:
        loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{_today}', f'{_today}')
        loop.TODAY = _today
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
async def today_img(chat, match):
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{today}', f'{today}')
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command('/yesterday')
async def today_img(chat, match):
    day = datetime.datetime.now() - datetime.timedelta(days=1)
    day = day.strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, f'{conf.data_folder}/{day}', f'{day}')
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command('/img')
async def img(chat, match):
    image = await get_img()
    with open(image, 'rb') as image:
        await chat.send_photo(image)


async def main():
    loop = asyncio.get_event_loop()
    loop.TODAY = datetime.datetime.now().strftime('%d_%m_%Y')
    pe = asyncio.create_task(periodic_get_img())
    bot_loop = asyncio.create_task(bot.loop())
    await asyncio.wait([pe, bot_loop])


if __name__ == '__main__':
    asyncio.run(main())
