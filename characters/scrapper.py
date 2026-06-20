import time

import requests
from django.conf import settings
from django.db import IntegrityError

from characters.models import Character


def scrape_characters() -> list[Character]:
    next_url_to_scrape = settings.RICK_AND_MORTY_API_CHARACTERS_URL
    characters = []

    while next_url_to_scrape:
        response = requests.get(next_url_to_scrape, timeout=10)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 60
            time.sleep(wait_seconds)
            continue

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
        time.sleep(0.3)

    return characters


def save_characters(characters: list[Character]) -> None:
    for character in characters:
        try:
            character.save()
        except IntegrityError:
            print(f"Character with api_id: {character.api_id} already exists in DB")

def sync_characters_with_api() -> None:
    characters = scrape_characters()
    save_characters(characters)
