import requests
from django.conf import settings

from characters.models import Character


def scrape_characters() -> list[Character]:
    next_url_to_scrape = settings.RICK_AND_MORTY_API_CHARACTERS_URL
    characters = []

    while next_url_to_scrape:
        response = requests.get(next_url_to_scrape, timeout=10)
        response.raise_for_status()
        data = response.json()

        for character_dict in data["results"]:
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

        next_url_to_scrape = data["info"]["next"]

    return characters