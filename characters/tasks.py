from characters.models import Character

from celery import shared_task

from characters.scrapper import sync_characters_with_api


# @shared_task
# def count_characters() -> int:
#     return Character.objects.count()


@shared_task
def run_sync_with_api() -> None:
    return sync_characters_with_api()
