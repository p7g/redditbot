from typing import Iterable

from tortoise import Tortoise, fields
from tortoise.models import Model


async def init(db_url: str):
    await Tortoise.init(db_url=db_url,
                        modules={'models': ('redditbot.models', )})
    await Tortoise.generate_schemas()


class Subscription(Model):
    id = fields.IntField(pk=True)
    channel_id = fields.TextField()
    subreddit = fields.TextField()

    @classmethod
    def for_channel(cls, channel_id: int):
        return cls.filter(channel_id=str(channel_id))

    @classmethod
    def for_subreddit(cls, subreddit: str):
        return cls.filter(subreddit__in=(subreddit, 'all'))

    @classmethod
    async def subreddit_subscribers(cls, subreddit: str) -> Iterable[int]:
        subscriptions = await cls.for_subreddit(subreddit) \
            .values_list('channel_id', flat=True)
        return map(int, subscriptions)

    @classmethod
    async def all_subreddits(cls) -> Iterable[str]:
        return await cls.all().values_list('subreddit', flat=True)
