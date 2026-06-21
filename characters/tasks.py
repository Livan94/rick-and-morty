from celery import shared_task
import asyncio

from characters.scrapper import sync_characters_with_api


@shared_task
def run_sync_with_api() -> None:
    asyncio.run(sync_characters_with_api())
