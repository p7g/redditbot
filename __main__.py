import asyncio
import logging
import multiprocessing as mp
import os

from aioprocessing import AioQueue
from dotenv import load_dotenv
from structlog import get_logger

from redditbot import bot, models, reddit, util

load_dotenv()

logger = get_logger(__name__)


async def read_queue(ctx: util.Context):
    logger.info('Reading queue')
    while True:
        val = await ctx.new_submissions.coro_get()
        logger.info('Got a new subscription', data=val)


async def start():
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.DEBUG)

    reddit_credentials = reddit.Credentials(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
    )

    reddit_client = reddit.Client(reddit_credentials)
    logger.info('Initialized reddit client')

    context = util.Context(
        discord_client=None,
        reddit_client=reddit_client,
        reddit_credentials=reddit_credentials,
        subscription_changes=AioQueue(),
        new_submissions=AioQueue(),
        mp_context=mp.get_context('spawn'),
    )

    context.discord_client = discord_client = bot.init(context)
    logger.info('Initialized dicord client')

    try:
        await models.init(os.getenv('DB_URL'))
        logger.info('Initialized database')

        reddit_process = reddit.SubredditWatcher.create(context)
        reddit_process.start()

        logger.info('Starting application')
        await asyncio.gather(
            read_queue(context),
            bot.forward_messages(context),
            discord_client.start(os.getenv('DISCORD_TOKEN')),
        )
    finally:
        logger.info('Logging out discord client')
        await discord_client.logout()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
