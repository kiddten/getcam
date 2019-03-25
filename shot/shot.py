import asyncio
import datetime
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from shot import conf
from shot.bot import CamBot
from shot.shooter import get_img


def init_logging():
    config = {
        'handlers': [
            {
                'sink': Path(conf.root_dir) / conf.log_file,
                'level': 'DEBUG'
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


async def main(run_scheduler=True):
    bot = CamBot()
    if run_scheduler:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        for cam in conf.cameras_list:
            scheduler.add_job(
                get_img, 'interval', (cam, bot.session),
                seconds=cam.interval, next_run_time=datetime.datetime.now()
            )
        scheduler.add_job(bot.daily_movie_group, 'cron', hour=0, minute=2)
        scheduler.add_job(bot.daily_stats, 'cron', hour=0, minute=0, second=5)

    bot_loop = asyncio.create_task(bot.loop())
    alive_message = asyncio.create_task(bot.notify_admins('Ready! Use /menu, /stats'))
    await asyncio.wait([bot_loop, alive_message])


def run():
    init_logging()
    logger.info('Running getcam service')
    asyncio.run(main())


if __name__ == '__main__':
    run()
