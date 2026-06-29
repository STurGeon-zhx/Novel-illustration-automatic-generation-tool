import base64
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_client import extract_prompt_items
from app.ai_client import OpenAICompatibleClient
from app.repository import TaskRepository
from app.service import IllustrationService


class FakeAiClient:
    def __init__(self):
        self.image_calls = []

    def split_chapter(self, chapter_text, image_count):
        return [
            {
                "title": f"scene {index}",
                "scene_summary": f"summary {index}",
                "viewpoint": "wide shot",
                "positive_prompt": f"positive prompt {index}",
                "negative_prompt": "low quality",
            }
            for index in range(1, image_count + 1)
        ]

    def generate_image(self, prompt, output_path):
        self.image_calls.append(prompt["positive_prompt"])
        output_path.write_bytes(base64.b64decode("iVBORw0KGgo="))
        return output_path


class FakeSettings:
    base_url = "https://apihub.agnes-ai.com/v1"
    api_key = "test-key"
    text_model = "agnes-2.0-flash"
    image_model = "agnes-image-2.1-flash"
    image_size = "1024x768"
    image_return_base64 = True
    timeout_seconds = 30
    max_retries = 2


class RecordingAgnesClient(OpenAICompatibleClient):
    def __init__(self):
        super().__init__(FakeSettings())
        self.calls = []

    def _post_json(self, path, payload):
        self.calls.append((path, payload))
        if path == "/chat/completions":
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                [
                                    {
                                        "title": "雨夜重逢",
                                        "scene_summary": "主角在雨夜巷口重逢",
                                        "viewpoint": "低机位近景",
                                        "positive_prompt": "雨夜巷口，主角撑伞回头，电影感光影",
                                        "negative_prompt": "低清晰度，畸形手",
                                    }
                                ],
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        return {"data": [{"b64_json": "iVBORw0KGgo=", "url": None}]}


class CountRetryAgnesClient(OpenAICompatibleClient):
    def __init__(self):
        super().__init__(FakeSettings())
        self.calls = 0

    def _post_json(self, path, payload):
        self.calls += 1
        if self.calls == 1:
            return {"choices": [{"message": {"content": '{"prompts":[]}'}}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "prompts": [
                                    {
                                        "title": "雨夜重逢",
                                        "scene_summary": "主角在雨夜巷口重逢",
                                        "viewpoint": "低机位近景",
                                        "positive_prompt": "雨夜巷口，主角撑伞回头，电影感光影",
                                        "negative_prompt": "低清晰度，畸形手",
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


class AgnesClientTests(unittest.TestCase):
    def test_split_chapter_requests_prompts_array_inside_json_object(self):
        client = RecordingAgnesClient()

        client.split_chapter("雨夜里，少年回到故乡。", 1)

        _, payload = client.calls[0]
        joined_messages = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn('"prompts"', joined_messages)
        self.assertIn("正好 1 个", joined_messages)

    def test_split_chapter_retries_when_prompt_count_is_wrong(self):
        client = CountRetryAgnesClient()

        prompts = client.split_chapter("雨夜里，少年回到故乡。", 1)

        self.assertEqual(len(prompts), 1)
        self.assertEqual(client.calls, 2)

    def test_split_chapter_uses_agnes_text_model_endpoint(self):
        client = RecordingAgnesClient()

        prompts = client.split_chapter("雨夜里，少年回到故乡。", 1)

        path, payload = client.calls[0]
        self.assertEqual(path, "/chat/completions")
        self.assertEqual(payload["model"], "agnes-2.0-flash")
        self.assertEqual(prompts[0]["title"], "雨夜重逢")

    def test_generate_image_uses_agnes_image_payload_without_negative_prompt_field(self):
        client = RecordingAgnesClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "image.png"

            client.generate_image(
                {
                    "positive_prompt": "雨夜巷口，主角撑伞回头，电影感光影",
                    "negative_prompt": "低清晰度，畸形手",
                },
                output_path,
            )

        path, payload = client.calls[0]
        self.assertEqual(path, "/images/generations")
        self.assertEqual(payload["model"], "agnes-image-2.1-flash")
        self.assertEqual(payload["size"], "1024x768")
        self.assertTrue(payload["return_base64"])
        self.assertNotIn("negative_prompt", payload)
        self.assertIn("避免", payload["prompt"])

    def test_post_json_retries_transient_url_errors(self):
        client = OpenAICompatibleClient(FakeSettings())

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        with patch(
            "urllib.request.urlopen",
            side_effect=[urllib.error.URLError(TimeoutError("timed out")), FakeResponse()],
        ) as urlopen:
            response = client._post_json("/chat/completions", {"model": "agnes-2.0-flash"})

        self.assertEqual(response, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)

    def test_post_json_retries_transient_http_500_errors(self):
        client = OpenAICompatibleClient(FakeSettings())

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        transient_error = urllib.error.HTTPError(
            url="https://apihub.agnes-ai.com/v1/images/generations",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=BytesIO(b'{"error":{"message":"upstream error"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=[transient_error, FakeResponse()]) as urlopen:
            response = client._post_json("/images/generations", {"model": "agnes-image-2.1-flash"})

        self.assertEqual(response, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)


class PromptParsingTests(unittest.TestCase):
    def test_extract_prompt_items_reads_json_inside_markdown_fence(self):
        content = """```json
        [
          {
            "title": "A",
            "scene_summary": "B",
            "viewpoint": "C",
            "positive_prompt": "D",
            "negative_prompt": "E"
          }
        ]
        ```"""

        items = extract_prompt_items(content)

        self.assertEqual(items[0]["title"], "A")
        self.assertEqual(items[0]["positive_prompt"], "D")

    def test_extract_prompt_items_accepts_single_prompt_object(self):
        content = json.dumps(
            {
                "title": "A",
                "scene_summary": "B",
                "viewpoint": "C",
                "positive_prompt": "D",
                "negative_prompt": "E",
            }
        )

        items = extract_prompt_items(content)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A")


class RepositoryTests(unittest.TestCase):
    def test_task_repository_persists_task_prompts_and_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "app.db"
            repo = TaskRepository(db_path)
            repo.init_schema()

            task_id = repo.create_task("chapter text", 2)
            repo.replace_prompts(
                task_id,
                [
                    {
                        "title": "scene",
                        "scene_summary": "summary",
                        "viewpoint": "view",
                        "positive_prompt": "positive",
                        "negative_prompt": "negative",
                    }
                ],
            )
            image_id = repo.create_image(task_id, 1, "outputs/task/image.png")
            repo.mark_image_done(image_id, "outputs/task/image.png")

            task = repo.get_task(task_id)

            self.assertEqual(task["chapter_text"], "chapter text")
            self.assertEqual(task["prompts"][0]["title"], "scene")
            self.assertEqual(task["images"][0]["status"], "done")


class ServiceTests(unittest.TestCase):
    def test_service_creates_task_with_requested_number_of_prompts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            service = IllustrationService(repo, FakeAiClient(), root / "outputs")

            task = service.create_prompt_task("long chapter", 3)

            self.assertEqual(task["image_count"], 3)
            self.assertEqual(len(task["prompts"]), 3)
            self.assertEqual(task["status"], "prompts_ready")

    def test_service_generates_images_for_saved_prompts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            ai_client = FakeAiClient()
            service = IllustrationService(repo, ai_client, root / "outputs")
            task = service.create_prompt_task("long chapter", 2)

            updated = service.generate_images(task["id"])

            self.assertEqual([image["status"] for image in updated["images"]], ["done", "done"])
            self.assertEqual(len(ai_client.image_calls), 2)
            self.assertTrue((root / "outputs" / updated["images"][0]["path"]).exists())

    def test_service_rejects_image_count_outside_one_to_ten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            service = IllustrationService(repo, FakeAiClient(), root / "outputs")

            with self.assertRaises(ValueError):
                service.create_prompt_task("chapter", 11)


if __name__ == "__main__":
    unittest.main()
