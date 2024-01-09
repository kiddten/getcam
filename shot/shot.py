import asyncio
import datetime
import logging
import signal
import sys
import tracemalloc
from asyncio.runners import _cancel_all_tasks
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from shot import conf
from shot.bot import CamBot
from shot.shooter import CamHandler


def init_logging():
    config = {
        'handlers': [
            {
                'sink': Path(conf.root_dir) / conf.log_file,
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


async def mem_trace(top=15):
    start = tracemalloc.take_snapshot()
    prev = start
    while True:
        current = tracemalloc.take_snapshot()
        top_stats = current.compare_to(prev, 'lineno')
        result = '\n'.join(str(stat) for stat in top_stats[:top])
        total = sum(stat.size for stat in top_stats)
        result = f'{result}\nTotal usage: {total / 1024} KB'
        logger.info(f'Top {top} memory usage diff\n{result}')
        prev = current
        await asyncio.sleep(5 * 60)


def run():
    # tracemalloc.start(25)

    def shutdown_by_signal(sig):
        logger.info(f'Got {sig} signal. Shutting down..')
        loop.stop()

    init_logging()
    logger.info('Running getcam service')
    loop = asyncio.get_event_loop()
    loop.set_debug(conf.debug)

    for sig_name in 'SIGINT', 'SIGTERM':
        loop.add_signal_handler(getattr(signal, sig_name), shutdown_by_signal, sig_name)

    bot = CamBot()
    scheduler = AsyncIOScheduler()
    handlers = [CamHandler(cam, bot.session, None) for cam in conf.cameras_list]

    cron_expression = '0-59/1 5-22 * * *'

    async def main():
        scheduler.start()
        for handler in handlers:
            scheduler.add_job(
                handler.get_img_and_sync,
                trigger=CronTrigger.from_crontab(cron_expression),
                seconds=handler.cam.interval,
                next_run_time=datetime.datetime.now()
            )
        scheduler.add_job(bot.daily_movie_group, 'cron', hour=23, minute=1)
        scheduler.add_job(bot.daily_photo_group, 'cron', hour=10, minute=10)

        # asyncio.create_task(mem_trace())
        asyncio.create_task(bot.loop())
        await bot.notify_admins('Ready! Use /menu, /stats')

    loop.run_until_complete(main())
    loop.run_forever()
    loop.run_until_complete(bot.notify_admins('Going to restart services..'))
    bot.stop()
    scheduler.shutdown()
    _cancel_all_tasks(loop)
    loop.run_until_complete(loop.shutdown_asyncgens())
    logger.success('Service has been stopped')


if __name__ == '__main__':
    run()
