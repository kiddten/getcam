import asyncio
import datetime
import logging
import signal
import sys
from asyncio.runners import _cancel_all_tasks
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from shot import conf
from shot.bot import CamBot
from shot.gphotos import GooglePhotosManager
from shot.shooter import CamHandler


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
    logging.getLogger('backoff').setLevel(logging.DEBUG)


def run():
    def shutdown_by_signal(sig):
        logger.info(f'Got {sig} signal. Shutting down..')
        loop.stop()

    init_logging()
    logger.info('Running getcam service')
    loop = asyncio.get_event_loop()
    loop.set_debug(conf.debug)

    for sig_name in 'SIGINT', 'SIGTERM':
        loop.add_signal_handler(getattr(signal, sig_name), shutdown_by_signal, sig_name)

    agent = GooglePhotosManager()
    bot = CamBot(agent=agent)
    scheduler = AsyncIOScheduler()
    handlers = [CamHandler(cam, bot.session, agent) for cam in conf.cameras_list]

    async def main():
        await agent.start()
        scheduler.start()
        for handler in handlers:
            scheduler.add_job(
                handler.get_img_and_sync, 'interval', seconds=handler.cam.interval,
                next_run_time=datetime.datetime.now()
            )
        scheduler.add_job(agent.refresh_token, 'interval', minutes=30)
        scheduler.add_job(bot.daily_movie_group, 'cron', hour=0, minute=2)
        scheduler.add_job(bot.daily_stats, 'cron', hour=0, minute=0, second=5)

        asyncio.create_task(bot.loop())
        asyncio.create_task(agent.loop())
        await bot.notify_admins('Ready! Use /menu, /stats')

    loop.run_until_complete(main())
    loop.run_forever()
    bot.stop()
    scheduler.shutdown()
    loop.run_until_complete(agent.stop())
    _cancel_all_tasks(loop)
    loop.run_until_complete(loop.shutdown_asyncgens())
    logger.success('Service has been stopped')


if __name__ == '__main__':
    run()
