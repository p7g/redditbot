import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing.context import BaseContext
from typing import Callable, TYPE_CHECKING

import discord.ext.commands

if TYPE_CHECKING:
    import redditbot.reddit

pool = ThreadPoolExecutor()

__all__ = ('Context', 'sync_to_async', 'queue_to_async_gen')


@dataclass
class Context:
    discord_client: discord.ext.commands.Bot
    reddit_client: 'redditbot.reddit.Client'
    reddit_credentials: 'redditbot.reddit.Credentials'
    subscription_changes: asyncio.Queue
    new_submissions: asyncio.Queue
    mp_context: BaseContext


async def queue_to_async_gen(q: asyncio.Queue):
    while True:
        yield await q.get()
        q.task_done()


def sync_to_async(fn: Callable):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        future = pool.submit(fn, *args, **kwargs)
        return asyncio.wrap_future(future)

    return wrapper
