import asyncio
from unittest.mock import AsyncMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from characters.models import Character
from characters.serializers import CharacterSerializer
from characters.scrapper import (
    save_characters,
    scrape_characters_async,
    sync_characters_with_api,
)
from characters.tasks import run_sync_with_api


def make_character(**kwargs) -> Character:
    defaults = dict(
        api_id=1,
        name="Rick Sanchez",
        status=Character.StatusChoices.ALIVE,
        species="Human",
        gender=Character.GenderChoices.MALE,
        image="https://example.com/rick.jpg",
    )
    defaults.update(kwargs)
    return Character.objects.create(**defaults)


class CharacterModelTest(TestCase):
    def test_str_returns_name(self):
        character = make_character()
        self.assertEqual(str(character), "Rick Sanchez")


class CharacterSerializerTest(TestCase):
    def test_serializer_fields(self):
        character = make_character()
        data = CharacterSerializer(character).data

        self.assertEqual(
            set(data.keys()),
            {"id", "api_id", "name", "status", "species", "gender", "image"},
        )
        self.assertEqual(data["name"], "Rick Sanchez")


class CharacterViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        make_character(api_id=1, name="Rick Sanchez")
        make_character(api_id=2, name="Morty Smith")

    def test_get_random_character_returns_200(self):
        url = reverse("characters:character-random")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(response.data["name"], ["Rick Sanchez", "Morty Smith"])

    def test_get_random_character_returns_404_when_no_characters(self):
        Character.objects.all().delete()
        url = reverse("characters:character-random")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "No characters found.")

    def test_character_list_returns_all_characters(self):
        url = reverse("characters:character-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_character_list_filters_by_name(self):
        url = reverse("characters:character-list")
        response = self.client.get(url, {"name": "rick"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Rick Sanchez")

    def test_character_list_filter_no_match_returns_empty(self):
        url = reverse("characters:character-list")
        response = self.client.get(url, {"name": "nobody"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)


class ScrapperSaveCharactersTest(TestCase):
    def test_save_characters_saves_new_characters(self):
        characters = [
            Character(
                api_id=1,
                name="Rick Sanchez",
                status=Character.StatusChoices.ALIVE,
                species="Human",
                gender=Character.GenderChoices.MALE,
                image="https://example.com/rick.jpg",
            )
        ]

        asyncio.run(save_characters(characters))

        self.assertEqual(Character.objects.count(), 1)
        self.assertTrue(Character.objects.filter(api_id=1).exists())

    def test_save_characters_ignores_duplicates(self):
        make_character(api_id=1)

        duplicate = Character(
            api_id=1,
            name="Rick Sanchez",
            status=Character.StatusChoices.ALIVE,
            species="Human",
            gender=Character.GenderChoices.MALE,
            image="https://example.com/rick.jpg",
        )

        asyncio.run(save_characters([duplicate]))

        self.assertEqual(Character.objects.count(), 1)


class ScrapeCharactersAsyncTest(TestCase):
    @patch("characters.scrapper.fetch_characters_page", new_callable=AsyncMock)
    def test_scrape_characters_async_collects_all_pages(self, mock_fetch):
        mock_fetch.side_effect = [
            {
                "info": {"pages": 2},
                "results": [
                    {
                        "id": 1,
                        "name": "Rick Sanchez",
                        "status": "Alive",
                        "species": "Human",
                        "gender": "Male",
                        "image": "https://example.com/rick.jpg",
                    }
                ],
            },
            {
                "info": {"pages": 2},
                "results": [
                    {
                        "id": 2,
                        "name": "Morty Smith",
                        "status": "Alive",
                        "species": "Human",
                        "gender": "Male",
                        "image": "https://example.com/morty.jpg",
                    }
                ],
            },
        ]

        characters = asyncio.run(scrape_characters_async())

        self.assertEqual(len(characters), 2)
        self.assertEqual(characters[0].name, "Rick Sanchez")
        self.assertEqual(characters[1].name, "Morty Smith")
        self.assertEqual(mock_fetch.await_count, 2)


class ScrapperSyncTest(TestCase):
    @patch("characters.scrapper.save_characters", new_callable=AsyncMock)
    @patch(
        "characters.scrapper.scrape_characters_async",
        new_callable=AsyncMock
    )
    def test_sync_characters_with_api_calls_scrape_and_save(
        self, mock_scrape, mock_save
    ):
        characters = [Character(api_id=1, name="Rick Sanchez")]
        mock_scrape.return_value = characters

        asyncio.run(sync_characters_with_api())

        mock_scrape.assert_awaited_once()
        mock_save.assert_awaited_once_with(characters)


class TasksTest(TestCase):
    @patch("characters.tasks.asyncio.run")
    @patch("characters.tasks.sync_characters_with_api")
    def test_run_sync_with_api_task_calls_asyncio_run(
        self, mock_sync, mock_asyncio_run
    ):
        run_sync_with_api()

        mock_sync.assert_called_once()
        mock_asyncio_run.assert_called_once_with(mock_sync.return_value)
