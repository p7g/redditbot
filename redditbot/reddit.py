import asyncio
import platform
import queue
import multiprocessing as mp

from dataclasses import dataclass
from typing import Dict, List, Generator

import aiostream.stream
import praw
import prawcore

from aioprocessing import AioQueue
from structlog import get_logger

from .models import Subscription
from .util import (Context, generator_to_coroutine, sync_to_async,
                   queue_to_async_gen)

logger = get_logger(__name__)


@dataclass
class Credentials:
    client_id: str
    client_secret: str


class Client:
    def __init__(self, credentials: Credentials):
        self._reddit = praw.Reddit(
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            user_agent=f'{platform.system()}:redditbot-dev:v0.0.1 (by /u/p-7g)',
        )

    def subreddit_stream(self, name: str):
        return generator_to_coroutine(
            self._reddit.subreddit(name).stream.submissions)()

    @sync_to_async
    def is_valid_subreddit(self, name: str) -> bool:
        try:
            self._reddit.subreddits.search_by_name(name, exact=True)
            return True
        except prawcore.NotFound:
            return False


class empty_generator:
    async def __aiter__(self):
        return self

    async def __anext__(self):
        return None


class SubredditWatcher(mp.Process):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # logger is only used from other thread
        self._logger = get_logger(f'{__name__} (spawn)')
        self._gen = empty_generator()
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls, ctx: Context):
        logger.info('Starting SubredditWatcher process')

        kwargs = {
            'reddit_credentials': ctx.reddit_credentials,
            'subscription_changes': ctx.subscription_changes,
            'new_submissions': ctx.new_submissions,
        }

        return cls(kwargs=kwargs)

    def run(self):
        self._logger.info('Hello from the other side')
        kwargs = self._kwargs
        reddit_client = Client(kwargs['reddit_credentials'])

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            asyncio.gather(
                self._watch_subscriptions(reddit_client,
                                          kwargs['subscription_changes']),
                self.__send_to_queue(kwargs['new_submissions'])))

    async def _watch_subscriptions(self, reddit_client: Client,
                                   subscription_changes: AioQueue):
        self._logger.info('Watching for reddit submissions')

        qs = Subscription.all().values_list('subreddit', flat=True)
        known_subreddits = {
            subreddit: reddit_client.subreddit_stream(subreddit)
            for subreddit in set(await qs)
        }

        async for op, (channel,
                       subreddit) in queue_to_async_gen(subscription_changes):
            self._logger.info('Received subscription change',
                              op=op,
                              channel=channel,
                              subreddit=subreddit)
            # if we're already watching or there are more channels watching the
            # subreddit, don't do anything
            if (op == 'added' and subreddit in known_subreddits
                    or op == 'removed' and 1 < await
                    Subscription.filter(subreddit=subreddit).count()):
                continue

            if op == 'removed':
                generator = known_subreddits[subreddit]
                del known_subreddits[subreddit]
            elif op == 'added':
                known_subreddits[subreddit] = reddit_client \
                    .subreddit_stream(subreddit)

            self._logger.info('Updating subreddit stream generator')
            self._logger.info('Waiting for lock (_watch_subscriptions)')
            async with self._lock:
                self._logger.info('got lock (_watch_subscriptions)')
                self._gen = aiostream.stream.merge(
                    *list(known_subreddits.values()))

    async def __aiter__(self):
        while True:
            self._logger.info('Waiting for lock (__aiter__)')
            async with self._lock:
                self._logger.info('got lock (__aiter__)')
                gen = self._gen
            yield await gen.__anext__()

    async def __send_to_queue(self, new_submissions: AioQueue):
        async for update in self:
            if update:
                self._logger('got submission',
                             subreddit=update.subreddit.display_name)
                await new_submissions.coro_put(update)
