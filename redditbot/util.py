import asyncio
import functools
import queue

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing.context import BaseContext
from typing import Callable, Iterable, Generator, TYPE_CHECKING

import discord.ext.commands
import janus

if TYPE_CHECKING:
    import redditbot.reddit

pool = ThreadPoolExecutor()

__all__ = ('Context', 'generator_to_coroutine', 'sync_to_async',
           'queue_to_async_gen')


@dataclass
class Context:
    discord_client: discord.ext.commands.Bot
    reddit_client: 'redditbot.reddit.Client'
    reddit_credentials: 'redditbot.reddit.Credentials'
    subscription_changes: asyncio.Queue
    new_submissions: asyncio.Queue
    mp_context: BaseContext


def _yield_to_queue(q: queue.Queue, gen: Iterable):
    for val in gen:
        q.put(val)
    q.join()


async def queue_to_async_gen(q: asyncio.Queue):
    while True:
        yield await q.get()
        q.task_done()


def queue_to_gen(q: queue.Queue):
    while True:
        yield q.get()
        q.task_done()


def generator_to_coroutine(gen: Callable[..., Generator]):
    @functools.wraps(gen)
    def wrapper(*args, **kwargs):
        q = janus.Queue()
        pool.submit(_yield_to_queue, q.sync_q, gen(*args, **kwargs))
        return queue_to_async_gen(q.async_q)

    return wrapper


def sync_to_async(fn: Callable):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        future = pool.submit(fn, *args, **kwargs)
        return asyncio.wrap_future(future)

    return wrapper
