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
