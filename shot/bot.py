import asyncio
import concurrent
import dataclasses
import datetime
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pendulum
from aiotg import Bot, Chat
from loguru import logger

from shot import conf
from shot.conf.model import Cam
from shot.gphotos import GooglePhotosManager
from shot.keyboards import CamerasChannel, InlineKeyboardButton, Markup, Menu, SyncFolders
from shot.model import Admin, Channel, db
from shot.model.helpers import ThreadSwitcherWithDB, db_in_thread
from shot.shooter import CamHandler, make_movie, make_weekly_movie, stats
from shot.utils import convert_size

if TYPE_CHECKING:
    from shot import gphotos


async def send_video(chat, clip):
    with open(clip.path, 'rb') as _clip, open(clip.thumb, 'rb') as thumb:
        await chat.send_video(
            _clip, supports_streaming='true',
            width=str(clip.width), height=str(clip.height), thumb=thumb
        )


async def unhandled_callbacks(chat, cq):
    await cq.answer()
    await chat.send_text('Unhandled callback!')


async def get_cam(name, chat):
    if name not in conf.cameras:
        await chat.send_text('Wrong cam name!')
        return
    return conf.cameras[name]


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
    # TODO load metadata from path
    with open(clip, 'rb') as clip:
        await chat.send_video(clip)


async def regular(chat, cq, match):
    await cq.answer()
    await regular_handler(chat, match.group(1))


async def today(chat, cq, match):
    await cq.answer(text='Going to make movie till now..')
    await today_handler(chat, match.group(1))


async def today_handler(chat, cam_name):
    cam = await get_cam(cam_name, chat)
    if not cam:
        return
    today = datetime.datetime.now().strftime('%d_%m_%Y')
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        clip = await loop.run_in_executor(pool, lambda: make_movie(cam, today, regular=False, executor=pool))
    await send_video(chat, clip)


async def weekly(chat: Chat, cq, match):
    await cq.answer(text='Going to make weekly movie!')
    cam = await get_cam(match.group(1), chat)
    if not cam:
        return
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        clip = await loop.run_in_executor(pool, lambda: make_weekly_movie(cam, pool))
    await send_video(chat, clip)


@ThreadSwitcherWithDB.optimized
async def reg(chat: Chat, match):
    # TODO return back or add password protect
    return
    async with db_in_thread():
        admin = db.query(Admin).filter(Admin.chat_id == chat.id).one_or_none()
    if admin:
        await chat.send_text('You are already registered!')
        return
    async with db_in_thread():
        admin = Admin(chat_id=chat.id)
        db.add(admin)
        db.commit()
    await chat.send_text('You are successfully registered!')


class CamBot:

    def __init__(self, agent: 'gphotos.GooglePhotosManager'):
        self._bot = Bot(conf.bot_token, proxy=conf.tele_proxy)
        self.session = self._bot.session
        self.loop = self._bot.loop
        self.menu_markup = Menu()
        self.init_handlers()
        self.agent = agent

    def init_handlers(self):
        self._bot.add_command(r'/mov (.+) (.+)', self.mov)
        self._bot.add_command(r'/check (.+) (.+)', self.check_album)
        self._bot.add_command(r'/reg', reg)
        self._bot.add_command(r'/ch', self.reg_channel)
        self._bot.add_command(r'/menu', self.menu)
        self._bot.add_command(r'/all', self.img_all_cams)
        self._bot.add_command(r'/stats', self.stats_command)
        self._bot.add_command(r'/daily', self.daily_movie_group_command)
        self._bot.add_callback(r'regular (.+)', regular)
        self._bot.add_callback(r'today (.+)', today)
        self._bot.add_callback(r'weekly (.+)', weekly)
        self._bot.add_callback(r'select (.+)', self.select)
        self._bot.add_callback(r'back', self.back)
        self._bot.add_callback(r'img (.+)', self.img_callback)
        self._bot.add_callback(r'choose_cam (.+)', self.choose_cam_callback)
        self._bot.add_callback(r'sync (.+)', self.sync_gphotos)
        self._bot.add_callback(r'gsnc (.+)', self.run_sync_gphotos)
        self._bot.add_callback(r'remove (.+)', self.remove_folder)
        self._bot.callback(unhandled_callbacks)

    def stop(self):
        self._bot.stop()

    @ThreadSwitcherWithDB.optimized
    async def daily_stats(self):
        markdown_result = await self.stats_handler(pendulum.yesterday())
        await self.notify_admins('\n'.join(markdown_result), parse_mode='Markdown')

    @ThreadSwitcherWithDB.optimized
    async def daily_movie(self, cam: Cam):
        day = datetime.datetime.now() - datetime.timedelta(days=1)
        day = day.strftime('%d_%m_%Y')
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            try:
                clip = await loop.run_in_executor(pool, lambda: make_movie(cam, day, executor=pool))
            except FileNotFoundError as exc:
                logger.exception(exc)
                await self.notify_admins(f'File {exc.filename} not found for daily movie {cam.name}: {day}')
                return
            except Exception as exc:
                logger.exception(exc)
                await self.notify_admins(f'Error during making daily movie for {cam.name}: {day}')
                return
        if cam.update_channel:
            async with db_in_thread():
                channels = db.query(Channel).filter(Channel.cam == cam.name).all()
            for channel in channels:
                await send_video(Chat(self._bot, channel.chat_id), clip)
        await self.notify_admins(f'Daily movie for {cam.name}: {day} ready!')

    async def mov(self, chat, match):
        cam = await get_cam(match.group(2), chat)
        if not cam:
            return
        day = match.group(1)
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            try:
                clip = await loop.run_in_executor(pool, lambda: make_movie(cam, day, executor=pool))
            except Exception:
                await self.notify_admins(f'Error during movie request {day} {cam.name}')
                return
        await self.notify_admins(f'Video ready. Uploading..')
        with open(clip, 'rb') as clip:
            await chat.send_video(clip)

    async def daily_movie_group(self):
        for cam in sorted(conf.cameras_list, key=lambda k: k.offset):
            if cam.render_daily:
                await self.daily_movie(cam)

    async def daily_movie_group_command(self, chat, match):
        logger.info('Forced daily movie group command')
        await self.daily_movie_group()

    async def img_all_cams(self, chat: Chat, match):
        for cam in conf.cameras_list:
            await self.img_handler(chat, cam)

    async def img_handler(self, chat: Chat, cam):
        image = await CamHandler(cam, self._bot.session).get_img(regular=False)
        if not image:
            await chat.send_text(f'Error during image request for {cam.name}')
            return
        path = image.original_path if cam.resize else image.path
        with open(path, 'rb') as image:
            await chat.send_photo(image)

    async def img_callback(self, chat, cq, match):
        await cq.answer()
        cam = await get_cam(match.group(1), chat)
        if not cam:
            return
        await self.img_handler(chat, cam)

    @ThreadSwitcherWithDB.optimized
    async def reg_channel(self, chat: Chat, match):
        async with db_in_thread():
            channel = db.query(Channel).filter(Channel.chat_id == chat.id).one_or_none()
        if channel:
            await self.notify_admins(f'Channel {chat.id} already registered!')
            return
        await chat.send_text('Choose cam for channel', reply_markup=CamerasChannel().options.to_json())

    @ThreadSwitcherWithDB.optimized
    async def choose_cam_callback(self, chat, cq, match):
        cam = match.group(1)
        async with db_in_thread():
            channel = Channel(chat_id=chat.id, cam=cam)
            db.add(channel)
            db.commit()
        await cq.answer(text=f'Added channel for {cam}')
        await self.notify_admins(text=f'Added channel {chat.id} for {cam}')

    @ThreadSwitcherWithDB.optimized
    async def notify_admins(self, text, **options):
        async with db_in_thread():
            admins = db.query(Admin).all()
        for admin in admins:
            await self._bot.send_message(admin.chat_id, text, **options)

    async def menu(self, chat, match):
        await chat.send_text('Menu', reply_markup=self.menu_markup.main_menu.to_json())

    async def select(self, chat: Chat, cq, match):
        await cq.answer()
        cam = match.group(1)
        await chat.edit_text(
            cq.src['message']['message_id'], f'Camera: {cam}',
            markup=dataclasses.asdict(self.menu_markup.cam_options[cam].markup)
        )

    async def back(self, chat, cq, match):
        await cq.answer()
        await chat.edit_text(
            cq.src['message']['message_id'], 'Menu',
            markup=dataclasses.asdict(self.menu_markup.main_menu)
        )

    async def sync_gphotos(self, chat, cq, match):
        await cq.answer()
        cam = match.group(1)
        await chat.edit_text(
            cq.src['message']['message_id'], f'Choose folder for {cam}',
            markup=dataclasses.asdict(SyncFolders(cam).folders)
        )

    async def run_sync_gphotos(self, chat, cq, match):
        _folder = match.group(1)
        folder = Path(conf.root_dir) / 'data' / _folder
        logger.debug(f'GOING TO SYNC FOLDER {folder}')
        await cq.answer(text=f'GOING TO SYNC FOLDER {folder}')
        await self.notify_admins(f'Started sync {folder}')
        try:
            await GooglePhotosManager().batch_upload(Path(folder))
        except Exception:
            logger.exception('Sync error!')
            await self.notify_admins(f'Error with {folder}!')
            return
        await self.notify_admins(f'{folder} successfully uploaded!')
        markup = Markup([[InlineKeyboardButton(text=f'{_folder}', callback_data=f'remove {_folder}')]])
        await chat.send_text(f'Remove folder {folder.name}', reply_markup=markup.to_json())

    async def remove_folder(self, chat, cq, match):
        await cq.answer(text='Removing folder..')
        folder = match.group(1)
        folder = Path(conf.root_dir) / 'data' / folder
        shutil.rmtree(folder)
        await chat.send_text('Successfully removed!')

    async def stats_command(self, chat: Chat, match):
        try:
            markdown_result = await self.stats_handler(pendulum.today())
        except Exception:
            await chat.send_text('Error during request stats')
            return
        await chat.send_text('\n'.join(markdown_result), parse_mode='Markdown')

    async def stats_handler(self, day=None):
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: stats(day))
        album_stats = await self.agent.album_stats(day)
        markdown_result = [f'#stats *{day.format("DD/MM/YYYY")}*']
        for d in result['cameras']:
            stat = result['cameras'][d]
            count, size = stat['count'], convert_size(stat['size'])
            avg = convert_size(stat['size'] / count)
            media_count = album_stats[d]
            markdown_result.append(f'*{d}*: {count} - {media_count} - {size} - {avg} ')
        total = convert_size(result['total'])
        markdown_result.append(f'*total*: {total}')
        return markdown_result

    async def check_album(self, chat, match):
        cam = await get_cam(match.group(1), chat)
        if not cam:
            return
        day = match.group(2)
        await self.agent.check_album(cam, day)
