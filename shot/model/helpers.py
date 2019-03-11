import gc
import inspect
import warnings
import weakref
from asyncio import get_event_loop
from concurrent.futures import Executor
from functools import partial, update_wrapper, wraps
from threading import Event
from typing import Callable, Optional

from . import db


def wrapped_partial(func, *args, **kwargs):
    partial_func = partial(func, *args, **kwargs)
    update_wrapper(partial_func, func)
    return partial_func


class ThreadSwitcher:
    __slots__ = 'executor', 'exited'

    _coro_lookup = weakref.WeakValueDictionary()

    def __init__(self, executor: Optional[Executor]) -> None:
        self.executor = executor
        self.exited = False

    @classmethod
    def optimized(cls, func):
        """ Decorator to optimize functions which use ThreadSwitcher
        """
        # if not asyncio.iscoroutinefunction(func):
        #     return func
        code_id = id(func.__code__)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            coro = func(*args, **kwargs)
            frame_id = id(coro.cr_frame)
            cls._add_coro_object(code_id, frame_id, coro)
            try:
                return await coro
                # return coro
            finally:
                cls._cleanup_coro_object(code_id, frame_id)

        return wrapper

    def __aenter__(self):
        # This is run in the event loop thread
        return self

    def __await__(self):
        def exec_when_ready():
            # self._on_thread_enter()
            event.wait()
            coro.send(None)

            if not self.exited:
                raise RuntimeError('attempted to "await" in a worker thread')

        if self.exited:
            # This is run in the worker thread
            yield
        else:
            # This is run in the event loop thread
            previous_frame = inspect.currentframe().f_back
            coro = self._get_coro_object(id(previous_frame.f_code), id(previous_frame))
            if coro is None or coro.cr_frame is not previous_frame:
                # Fallback to slow method with info from GC if there is no cache or if it's wrong
                warnings.warn(
                    "Going to use slow GC method to search coro object for {}. "
                    "Consider using '{}.optimized' decorator".format(
                        previous_frame.f_code, self.__class__.__name__
                    )
                )
                coro = next(obj for obj in gc.get_referrers(previous_frame.f_code)
                            if inspect.iscoroutine(obj) and obj.cr_frame is previous_frame)
            # del previous_frame
            event = Event()
            loop = get_event_loop()
            future = loop.run_in_executor(self.executor, exec_when_ready)
            next(future.__await__())  # Make the future think it's being awaited on
            loop.call_soon(event.set)
            yield future

    def __aexit__(self, exc_type, exc_val, exc_tb):
        # This is run in the worker thread
        self.exited = True
        return self

    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                loop = get_event_loop()
            except RuntimeError:
                # Event loop not available -- we're in a worker thread
                return func(*args, **kwargs)
            else:
                callback = wrapped_partial(func, *args, **kwargs)
                return loop.run_in_executor(self.executor, callback)

        assert not inspect.iscoroutinefunction(func), 'Cannot wrap coroutine functions to be run in an executor'
        return wrapper

    @classmethod
    def _add_coro_object(cls, code_id, frame_id, coro):
        cls._coro_lookup[(code_id, frame_id)] = coro

    @classmethod
    def _cleanup_coro_object(cls, code_id, frame_id):
        cls._coro_lookup.pop((code_id, frame_id), None)

    @classmethod
    def _get_coro_object(cls, code_id, frame_id):
        return cls._coro_lookup.get((code_id, frame_id), None)

    def _on_thread_enter(self):
        """ This method is called before the function in worker thread
        """
        # just stub for inherited classes


class ThreadSwitcherWithDB(ThreadSwitcher):

    def __aexit__(self, exc_type, exc_val, exc_tb):
        # This is run in the worker thread
        db._session.remove()
        return super().__aexit__(exc_type, exc_val, exc_tb)


def db_in_thread(executor=None):
    return ThreadSwitcherWithDB(executor)
