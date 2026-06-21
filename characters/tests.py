from unittest.mock import Mock, patch

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from characters.models import Character
from characters.serializers import CharacterSerializer
from characters.scrapper import save_characters, sync_characters_with_api
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
        self.character_1 = make_character(api_id=1, name="Rick Sanchez")
        self.character_2 = make_character(api_id=2, name="Morty Smith")

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
        self.assertEqual(len(response.data), 2)

    def test_character_list_filters_by_name(self):
        url = reverse("characters:character-list")
        response = self.client.get(url, {"name": "rick"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Rick Sanchez")

    def test_character_list_filter_no_match_returns_empty(self):
        url = reverse("characters:character-list")
        response = self.client.get(url, {"name": "nobody"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


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
        save_characters(characters)

        self.assertEqual(Character.objects.count(), 1)
        self.assertTrue(Character.objects.filter(api_id=1).exists())


class ScrapperSaveCharactersDuplicateTest(TransactionTestCase):
    @patch("characters.scrapper.print")
    def test_save_characters_handles_integrity_error(self, mock_print):
        make_character(api_id=1)

        duplicate = Character(
            api_id=1,
            name="Rick Sanchez",
            status=Character.StatusChoices.ALIVE,
            species="Human",
            gender=Character.GenderChoices.MALE,
            image="https://example.com/rick.jpg",
        )

        save_characters([duplicate])

        mock_print.assert_called_once_with(
            "Character with api_id: 1 already exists in DB"
        )
        self.assertEqual(Character.objects.count(), 1)


class ScrapperSyncTest(TestCase):
    @patch("characters.scrapper.save_characters")
    @patch("characters.scrapper.scrape_characters")
    def test_sync_characters_with_api_calls_scrape_and_save(
        self, mock_scrape, mock_save
    ):
        characters = [Character(api_id=1, name="Rick Sanchez")]
        mock_scrape.return_value = characters

        sync_characters_with_api()

        mock_scrape.assert_called_once()
        mock_save.assert_called_once_with(characters)


class ScrapeCharactersTest(TestCase):
    @patch("characters.scrapper.time.sleep")
    @patch("characters.scrapper.requests.get")
    def test_scrape_characters_collects_all_pages(self, mock_get, _):
        page1 = Mock(status_code=200)
        page1.json.return_value = {
            "info": {"next": "http://next-page"},
            "results": [{"id": 1, "name": "Rick Sanchez", "status": "Alive", "species": "Human", "gender": "Male", "image": "https://example.com/rick.jpg"}],
        }
        page1.raise_for_status.return_value = None

        page2 = Mock(status_code=200)
        page2.json.return_value = {
            "info": {"next": None},
            "results": [{"id": 2, "name": "Morty Smith", "status": "Alive", "species": "Human", "gender": "Male", "image": "https://example.com/morty.jpg"}],
        }
        page2.raise_for_status.return_value = None

        mock_get.side_effect = [page1, page2]

        from characters.scrapper import scrape_characters
        characters = scrape_characters()

        self.assertEqual(len(characters), 2)
        self.assertEqual(characters[0].name, "Rick Sanchez")
        self.assertEqual(characters[1].name, "Morty Smith")

    @patch("characters.scrapper.time.sleep")
    @patch("characters.scrapper.requests.get")
    def test_scrape_characters_retries_on_429(self, mock_get, mock_sleep):
        rate_limited = Mock(status_code=429, headers={"Retry-After": "1"})

        success = Mock(status_code=200)
        success.json.return_value = {
            "info": {"next": None},
            "results": [{"id": 1, "name": "Rick Sanchez", "status": "Alive", "species": "Human", "gender": "Male", "image": "https://example.com/rick.jpg"}],
        }
        success.raise_for_status.return_value = None

        mock_get.side_effect = [rate_limited, success]

        from characters.scrapper import scrape_characters
        characters = scrape_characters()

        self.assertEqual(len(characters), 1)
        mock_sleep.assert_any_call(1)


class TasksTest(TestCase):
    @patch("characters.tasks.sync_characters_with_api")
    def test_run_sync_with_api_task_calls_sync_function(self, mock_sync):
        run_sync_with_api()
        mock_sync.assert_called_once()