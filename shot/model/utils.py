import asyncio
import threading
import traceback

from loguru import logger


def db_session_scope():
    """ Custom scope function for SQLAlchemy DB sessions

    Returns current task id if available, or current thread id.
    Caller must do db.session.remove() themselves, cause there is no garbage collected thread-local used.
    """
    try:
        task = asyncio.Task.current_task()
    except RuntimeError:
        task = None
    if task is not None:
        logger.error("ASYNC_DB_USAGE: {}", "".join(traceback.format_stack()))
        return id(task)
    return threading.get_ident()
