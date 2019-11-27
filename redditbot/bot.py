import json

import discord
import praw.models
from discord.ext import commands
from tortoise.exceptions import DoesNotExist
from structlog import get_logger

from redditbot.models import Subscription
from redditbot.util import Context, queue_to_async_gen

logger = get_logger(__name__)


def init(context: Context):
    reddit_client = context.reddit_client
    subscription_changes = context.subscription_changes

    bot = commands.Bot(command_prefix='>')

    @bot.group(name='subscription', invoke_without_command=True)
    async def subscription(ctx, name='<empty>', *args):
        logger.info('Received invalid command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    args=args)
        await ctx.send(f'Invalid subcommand {name}')

    @subscription.command(name='list')
    async def subscriptions_list(ctx, *args):
        logger.info('Received subscription list command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id)

        qs = Subscription.filter(channel_id=ctx.channel.id)

        async with ctx.typing():
            if not await qs:
                buf = '**This channel has no subscriptions**'
            else:
                buf = '**This channel is subscribed to:**\n'

                async for subscription in Subscription.filter(
                        channel_id=ctx.channel.id):
                    buf += f'\t- /r/{subscription.subreddit}\n'

        await ctx.send(buf)

    @subscription.command(name='new')
    async def subscriptions_new(ctx, subreddit):
        logger.info('Received subscription new command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    subreddit=subreddit)

        success = False
        async with ctx.typing():
            if await reddit_client.is_valid_subreddit(subreddit):
                await Subscription.create(channel_id=ctx.channel.id,
                                          subreddit=subreddit)
                success = True

        if success:
            msg = f'**Successfully subscribed to** {subreddit}**!**'
            await subscription_changes.coro_put(
                ('added', (ctx.channel.id, subreddit)))
        else:
            msg = f'**Invalid subreddit:** {subreddit}'

        await ctx.send(msg)

    @subscription.command(name='delete')
    async def subscriptions_delete(ctx, subreddit):
        logger.info('Received subscription delete command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    subreddit=subreddit)

        found = False
        async with ctx.typing():
            try:
                subscription = await Subscription.get(
                    channel_id=ctx.channel.id, subreddit=subreddit)
                found = True
                await subscription.delete()
            except DoesNotExist:
                pass

        if found:
            msg = f'**Successfully removed subscription to** {subreddit}**!**'
            await subscription_changes.coro_put(
                ('removed', (ctx.channel.id, subreddit)))
        else:
            msg = f'**This channel is not subscribed to** {subreddit}'

        await ctx.send(msg)

    return bot


def generate_embed(post: praw.models.Submission) -> discord.Embed:
    return None


async def forward_messages(ctx: Context):
    logger.info('Forwarding reddit submissions to discord')
    async for reddit_update in queue_to_async_gen(ctx.new_submissions):
        display_name = reddit_update.subreddit.display_name

        logger.info('Got reddit update',
                    id=reddit_update.id,
                    subreddit=display_name)

        subscriptions = await Subscription.filter(
            subreddit__in=(reddit_update.subreddit.display_name, 'all'))

        for sub in subscriptions:
            channel: discord.TextChannel = ctx.discord_client \
                .get_channel(int(sub.channel_id))
            if channel:
                await channel.send(f'New post on /r/{display_name}',
                                   embed=generate_embed(reddit_update))
