import asyncio
import platform

from dataclasses import dataclass
from typing import List, Iterable

import praw
import prawcore

from aioprocessing import AioPipe
from aioprocessing.connection import AioConnection
from structlog import get_logger

from .models import Subscription
from .util import Context, sync_to_async, queue_to_async_gen

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

    def subreddit_stream(self, name: str, **kwargs):
        return self._reddit.subreddit(name).stream.submissions(**kwargs)

    @sync_to_async
    def is_valid_subreddit(self, name: str) -> bool:
        try:
            self._reddit.subreddits.search_by_name(name, exact=True)
            return True
        except prawcore.NotFound:
            return False


def _subreddit_watcher(credentials: Credentials, subreddits: List[str],
                       pipe: AioConnection):
    logger = get_logger(f'{__name__} (spawn)')
    logger.info('Listening for subreddit submissions')
    client = Client(credentials)

    for update in client.subreddit_stream('+'.join(subreddits),
                                          skip_existing=True):
        pipe.send(update)


async def _pipe_to_queue(ctx: Context, recv: AioConnection):
    while True:
        val = await recv.coro_recv()
        await ctx.new_submissions.coro_put(val)


def _start_watching(ctx: Context, subreddits: Iterable[str],
                    send: AioConnection):
    process = ctx.mp_context.Process(target=_subreddit_watcher,
                                     kwargs={
                                         'credentials': ctx.reddit_credentials,
                                         'subreddits': list(subreddits),
                                         'pipe': send,
                                     })
    process.start()
    return process


async def watch_subscriptions(ctx: Context):
    logger.info('Watching for reddit submissions')

    qs = Subscription.all().values_list('subreddit', flat=True)
    known_subreddits = set(await qs)

    recv, send = AioPipe(duplex=False)
    if known_subreddits:
        process = _start_watching(ctx, known_subreddits, send)
    else:
        process = None

    asyncio.get_event_loop().create_task(_pipe_to_queue(ctx, recv))

    async for op, (channel,
                   subreddit) in queue_to_async_gen(ctx.subscription_changes):
        logger.info('Received subscription change',
                    op=op,
                    channel=channel,
                    subreddit=subreddit)
        # if we're already watching or there are more channels watching the
        # subreddit, don't do anything
        if (op == 'added' and subreddit in known_subreddits
                or op == 'removed' and
                1 < await Subscription.filter(subreddit=subreddit).count()):
            continue

        if op == 'removed':
            known_subreddits.remove(subreddit)
        elif op == 'added':
            known_subreddits.add(subreddit)

        logger.info('Updating subreddit stream process')
        if process:
            process.terminate()
        if known_subreddits:
            process = _start_watching(ctx, known_subreddits, send)
        else:
            process = None
