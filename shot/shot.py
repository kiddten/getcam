import asyncio
import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from aiotg import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dataclasses_json import dataclass_json
from loguru import logger

from shot.conf import Cam, read
from shot.shooter import get_img, make_movie

conf = read()


class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(raw=True)
        logger_opt.log(record.levelno, record.getMessage())


if not conf.debug:
    logging.getLogger(None).addHandler(InterceptHandler())

logger.add(Path(conf.root_dir) / conf.log_file)
logging.basicConfig(level=logging.DEBUG)
bot = Bot(conf.bot_token, proxy=conf.tele_proxy)


async def periodic_get_img(cam: Cam):
    while True:
        await get_img(cam, bot.session)
        await asyncio.sleep(cam.interval)


async def get_cam(name, chat):
    if name not in conf.cameras_dict:
        await chat.send_text('Wrong cam name!')
        return
    return conf.cameras_dict[name]


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


async def daily_movie(cam: Cam):
    day = datetime.datetime.now() - datetime.timedelta(days=1)
    day = day.strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, make_movie, cam, day)


@dataclass_json
@dataclass
class InlineKeyboardButton:
    text: str
    callback_data: str
    type: str = 'InlineKeyboardButton'


@dataclass_json
@dataclass
class Markup:
    inline_keyboard: List[List[InlineKeyboardButton]]
    type: str = 'InlineKeyboardMarkup'


@dataclass_json
@dataclass
class Options:
    cam: str
    markup: Markup = field(init=False)

    def __post_init__(self):
        self.markup = Markup(
            [
                [
                    InlineKeyboardButton(text='img', callback_data=f'img {self.cam}'),
                    InlineKeyboardButton(text='regular', callback_data=f'regular {self.cam}'),
                    InlineKeyboardButton(text='today', callback_data=f'today {self.cam}'),
                ],
                [InlineKeyboardButton(text='« Back', callback_data='back')],
            ]
        )


@dataclass_json
@dataclass
class Menu:
    main_menu: Markup = Markup(
        [[InlineKeyboardButton(text=cam.name, callback_data=f'select {cam.name}') for cam in conf.cameras], ])

    cam_options: Dict[str, Options] = field(
        default_factory=lambda: {cam.name: Options(cam.name) for cam in conf.cameras}
    )


m = Menu()


@bot.command(r'/menu')
async def menu(chat, match):
    await chat.send_text('Menu', reply_markup=m.main_menu.to_json())


@bot.callback(r'select (.+)')
async def select(chat, cq, match):
    await cq.answer()
    cam = match.group(1)
    await bot.edit_message_text(
        chat.id, cq.src['message']['message_id'], f'Camera: {cam}',
        reply_markup=m.cam_options[cam].markup.to_json()
    )


@bot.callback(r'back')
async def back(chat, cq, match):
    await cq.answer()
    await bot.edit_message_text(
        chat.id, cq.src['message']['message_id'], 'Menu', reply_markup=m.main_menu.to_json()
    )


async def img_handler(chat, match):
    cam = await get_cam(match.group(1), chat)
    if not cam:
        return
    image = await get_img(cam, bot.session, regular=False)
    with open(image, 'rb') as image:
        await chat.send_photo(image)


@bot.command(r'img (.+)')
async def img_command(chat, match):
    await img_handler(chat, match)


@bot.callback(r'img (.+)')
async def img_callback(chat, cq, match):
    await cq.answer()
    await img_handler(chat, match)


@bot.callback(r'regular (.+)')
async def regular_callback(chat, cq, match):
    await cq.answer()
    await regular_handler(chat, match.group(1))


@bot.command(r'regular (.+)')
async def regular_command(chat, match):
    await regular_handler(chat, match.group(1))


async def regular_handler(chat, cam_name):
    cam = await get_cam(cam_name, chat)
    if not cam:
        return
    day = datetime.datetime.now() - datetime.timedelta(days=1)
    day = day.strftime('%d_%m_%Y')
    clip = Path(conf.root_dir) / 'data' / cam.name / 'regular' / 'clips' / f'{day}.mp4'
    if not clip.exists():
        await chat.send_text(f'Can not find regular clip for {day}!')
        return
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.command(r'today (.+)')
async def today_command(chat, match):
    await today_handler(chat, match.group(1))


@bot.callback(r'today (.+)')
async def today_callback(chat, cq, match):
    await cq.answer(text='Going to make movie till now..')
    await today_handler(chat, match.group(1))


async def today_handler(chat, cam_name):
    cam = await get_cam(cam_name, chat)
    if not cam:
        return
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    clip = await loop.run_in_executor(None, make_movie, cam, today, False)
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


@bot.callback
async def unhandled_callbacks(chat, cq):
    await cq.answer()
    await chat.send_text("Unhandled callback fired")


async def main():
    scheduler = AsyncIOScheduler()
    for cam in conf.cameras:
        scheduler.add_job(daily_movie, 'cron', (cam,), hour=0, minute=cam.offset)
    scheduler.start()

    periodic_tasks = [asyncio.create_task(periodic_get_img(cam)) for cam in conf.cameras]
    bot_loop = asyncio.create_task(bot.loop())
    await asyncio.wait([*periodic_tasks, bot_loop])


def run():
    asyncio.run(main())


if __name__ == '__main__':
    run()
# TODO move all init here
