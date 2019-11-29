from datetime import datetime

import discord
import praw.models
import yarl
from discord.ext import commands
from tortoise.exceptions import DoesNotExist, IntegrityError
from structlog import get_logger

from redditbot.models import Subscription
from redditbot.util import Context, queue_to_async_gen

logger = get_logger(__name__)

REDDIT_URL = yarl.URL('https://reddit.com')


def init(context: Context):
    reddit_client = context.reddit_client
    subscription_changes = context.subscription_changes

    bot = commands.Bot(command_prefix='>',
                       description='Subscribe to subreddit submissions',
                       case_insensitive=True)

    @bot.group(name='subs',
               invoke_without_command=True,
               case_insensitive=True,
               aliases=('sub', ))
    async def subs(ctx, *args):
        logger.info('Received invalid command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    args=args)
        if args:
            await ctx.send('Invalid subcommand %s' % ' '.join(args))
        else:
            await subs_list(ctx)

    async def subs_list(ctx, *args):
        logger.info('Received subscription list command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id)

        subscriptions = await Subscription.for_channel(ctx.channel.id)

        async with ctx.typing():
            if subscriptions:
                buf = '**This channel is subscribed to:**\n'

                for subscription in subscriptions:
                    buf += f'\t- r/{subscription.subreddit}\n'
            else:
                buf = '**This channel has no subscriptions**'

        await ctx.send(buf)

    subs.command(name='list',
                 callback=subs_list,
                 brief='See all subscriptions for this channel')

    @subs.command(name='new', aliases=('add', ))
    async def subs_new(ctx, subreddit):
        logger.info('Received subscription new command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    subreddit=subreddit)

        async with ctx.typing():
            if await reddit_client.is_valid_subreddit(subreddit):
                try:
                    sub = await Subscription.create(channel_id=ctx.channel.id,
                                                    subreddit=subreddit)
                    await subscription_changes.put(
                        ('added', (ctx.channel.id, sub.normalized_subreddit)))

                    msg = f'**Successfully subscribed to** {subreddit}**!**'
                except IntegrityError:
                    msg = f'**Already subscribed to** {subreddit}**!**'
            else:
                msg = f'**Invalid subreddit:** {subreddit}'

        await ctx.send(msg)

    @subs.command(name='delete', aliases=('remove', ))
    async def subs_delete(ctx, subreddit):
        logger.info('Received subscription delete command',
                    user_id=ctx.message.author.id,
                    channel_id=ctx.channel.id,
                    subreddit=subreddit)

        async with ctx.typing():
            try:
                subscription = await Subscription.get(
                    channel_id=ctx.channel.id, subreddit=subreddit)
                await subscription.delete()
                await subscription_changes.put(
                    ('removed', (ctx.channel.id,
                                 subscription.normalized_subreddit)))

                msg = ('**Successfully removed subscription'
                       f' to** {subreddit}**!**')
            except DoesNotExist:
                msg = f'**This channel is not subscribed to** {subreddit}'

        await ctx.send(msg)

    return bot


def _link(path: str):
    return str(REDDIT_URL.with_path(path))


def generate_embed(post: praw.models.Submission) -> discord.Embed:
    embed = discord.Embed(title=post.title,
                          color=0xff5700,
                          description=post.selftext,
                          timestamp=datetime.utcfromtimestamp(
                              post.created_utc),
                          url=post.url) \
        .set_footer(text=post.subreddit_name_prefixed,
                    icon_url=post.subreddit.icon_img) \
        .set_author(name=post.author.subreddit['display_name_prefixed'],
                    icon_url=post.author.icon_img,
                    url=_link(post.author.subreddit['url']))

    if getattr(post, 'post_hint', None) == 'image':
        embed = embed.set_image(url=post.url)
    return embed


async def forward_messages(ctx: Context):
    logger.info('Forwarding reddit submissions to discord')
    async for reddit_update in queue_to_async_gen(ctx.new_submissions):
        subreddit = reddit_update.subreddit
        display_name = subreddit.display_name
        display_name_prefixed = subreddit.display_name_prefixed

        logger.info('Got reddit update',
                    id=reddit_update.id,
                    subreddit=display_name)

        channel_ids = await Subscription \
            .subreddit_subscribers(display_name)

        for channel_id in channel_ids:
            channel: discord.TextChannel = ctx.discord_client \
                .get_channel(channel_id)
            if channel:
                await channel.send(f'**New post on** {display_name_prefixed}',
                                   embed=generate_embed(reddit_update))
