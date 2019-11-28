from typing import Iterable

from tortoise import Tortoise, fields
from tortoise.models import Model
from tortoise.query_utils import Q


async def init(db_url: str):
    await Tortoise.init(db_url=db_url,
                        modules={'models': ('redditbot.models', )})
    await Tortoise.generate_schemas()


def _normalize_string(s: str) -> str:
    return s.lower()


class CICharField(fields.CharField):
    def to_db_value(self, value, instance):
        return super().to_db_value(_normalize_string(value), instance)


class Subscription(Model):
    id = fields.IntField(pk=True)
    channel_id = fields.CharField(max_length=20)
    subreddit = fields.CharField(max_length=21)  # r/21charactersandnomore
    normalized_subreddit = CICharField(max_length=21)

    @classmethod
    async def create(cls, channel_id, subreddit):
        return await super().create(channel_id=channel_id,
                                    subreddit=subreddit,
                                    normalized_subreddit=subreddit)

    @classmethod
    def for_channel(cls, channel_id: int):
        return cls.filter(channel_id=str(channel_id))

    @classmethod
    def for_subreddit(cls, subreddit: str):
        normalized = subreddit  # _normalize_string(subreddit)
        return cls.filter(
            Q(normalized_subreddit=normalized) | Q(normalized_subreddit='all'))

    @classmethod
    async def subreddit_subscribers(cls, subreddit: str) -> Iterable[int]:
        subscriptions = await cls.for_subreddit(subreddit) \
            .values_list('channel_id', flat=True)
        return map(int, subscriptions)

    @classmethod
    async def all_subreddits(cls) -> Iterable[str]:
        return await cls.all().values_list('subreddit', flat=True)
