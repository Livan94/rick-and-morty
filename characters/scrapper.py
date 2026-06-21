import asyncio

import aiohttp
from asgiref.sync import sync_to_async
from django.conf import settings

from characters.models import Character

GRAPHQL_QUERY = """
query GetCharacters($page: Int!) {
  characters(page: $page) {
    info {
      pages
    }
    results {
      id
      name
      status
      species
      gender
      image
    }
  }
}
"""


async def fetch_characters_page(
    session: aiohttp.ClientSession,
    page: int,
) -> dict:
    async with session.post(
        settings.RICK_AND_MORTY_API_GRAPHQL_URL,
        json={
            "query": GRAPHQL_QUERY,
            "variables": {"page": page},
        },
    ) as response:
        response.raise_for_status()
        data = await response.json()
        return data["data"]["characters"]


async def scrape_characters_async() -> list[Character]:
    async with aiohttp.ClientSession() as session:
        first_page = await fetch_characters_page(session, 1)
        total_pages = first_page["info"]["pages"]

        all_pages = [first_page]

        if total_pages > 1:
            tasks = [
                fetch_characters_page(session, page)
                for page in range(2, total_pages + 1)
            ]
            all_pages.extend(await asyncio.gather(*tasks))

    characters = []

    for page_data in all_pages:
        for character_dict in page_data["results"]:
            characters.append(
                Character(
                    api_id=character_dict["id"],
                    name=character_dict["name"],
                    status=character_dict["status"],
                    species=character_dict["species"],
                    gender=character_dict["gender"],
                    image=character_dict["image"],
                )
            )

    return characters


@sync_to_async
def save_characters(characters: list[Character]) -> None:
    Character.objects.bulk_create(
        characters,
        batch_size=500,
        ignore_conflicts=True,
    )


async def sync_characters_with_api() -> None:
    characters = await scrape_characters_async()
    await save_characters(characters)
