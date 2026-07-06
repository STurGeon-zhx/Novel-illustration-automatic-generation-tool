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
from app.ai_client import POSITIVE_STYLE_PROMPT
from app.repository import TaskRepository
from app.service import IllustrationService


class FakeAiClient:
    def __init__(self):
        self.image_calls = []
        self.image_sizes = []

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

    def generate_image(self, prompt, output_path, image_size=None):
        self.image_calls.append(prompt["positive_prompt"])
        self.image_sizes.append(image_size)
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

    def test_split_chapter_requires_unified_anime_style(self):
        client = RecordingAgnesClient()

        client.split_chapter("雨夜里，少年回到故乡。", 1)

        _, payload = client.calls[0]
        joined_messages = "\n".join(message["content"] for message in payload["messages"])
        self.assertIn("漫画封面", joined_messages)
        self.assertIn("漫画PV截图质感", joined_messages)
        self.assertIn("positive_prompt", joined_messages)

    def test_split_chapter_adds_style_to_positive_prompt(self):
        client = RecordingAgnesClient()

        prompts = client.split_chapter("雨夜里，少年回到故乡。", 1)

        self.assertTrue(prompts[0]["positive_prompt"].startswith(POSITIVE_STYLE_PROMPT))

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

    def test_generate_image_accepts_image_size_override(self):
        client = RecordingAgnesClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "image.png"

            client.generate_image(
                {
                    "positive_prompt": "雨夜巷口，主角撑伞回头，电影感光影",
                    "negative_prompt": "低清晰度，畸形手",
                },
                output_path,
                image_size="768x1024",
            )

        _, payload = client.calls[0]
        self.assertEqual(payload["size"], "768x1024")

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

    def test_post_json_rebuilds_request_for_each_retry(self):
        client = OpenAICompatibleClient(FakeSettings())
        seen_request_ids = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            seen_request_ids.append(id(request))
            if len(seen_request_ids) == 1:
                raise urllib.error.URLError(ConnectionResetError(10054, "connection reset"))
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = client._post_json("/chat/completions", {"model": "agnes-2.0-flash"})

        self.assertEqual(response, {"ok": True})
        self.assertEqual(len(seen_request_ids), 2)
        self.assertNotEqual(seen_request_ids[0], seen_request_ids[1])

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

            task_id = repo.create_task("chapter text", 2, "owner-a")
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
                "owner-a",
            )
            image_id = repo.create_image(task_id, 1, "outputs/task/image.png")
            repo.mark_image_done(image_id, "outputs/task/image.png")

            task = repo.get_task(task_id, "owner-a")

            self.assertEqual(task["chapter_text"], "chapter text")
            self.assertEqual(task["prompts"][0]["title"], "scene")
            self.assertEqual(task["images"][0]["status"], "done")
            self.assertIsNone(repo.get_task(task_id, "owner-b"))

    def test_task_repository_deletes_task_and_related_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "app.db"
            repo = TaskRepository(db_path)
            repo.init_schema()

            task_id = repo.create_task("chapter text", 1, "owner-a")
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
                "owner-a",
            )
            repo.create_image(task_id, 1, "task/image.png")

            self.assertFalse(repo.delete_task(task_id, "owner-b"))
            deleted = repo.delete_task(task_id, "owner-a")

            self.assertTrue(deleted)
            self.assertIsNone(repo.get_task(task_id, "owner-a"))
            self.assertEqual(repo.list_tasks("owner-a"), [])

    def test_task_repository_lists_only_tasks_for_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = TaskRepository(Path(tmpdir) / "app.db")
            repo.init_schema()
            owner_a_task = repo.create_task("chapter a", 1, "owner-a")
            repo.create_task("chapter b", 1, "owner-b")

            owner_a_tasks = repo.list_tasks("owner-a")
            owner_b_tasks = repo.list_tasks("owner-b")

            self.assertEqual([task["id"] for task in owner_a_tasks], [owner_a_task])
            self.assertEqual(len(owner_b_tasks), 1)

    def test_task_repository_claims_legacy_tasks_for_configured_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "app.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY,
                        chapter_text TEXT NOT NULL,
                        image_count INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO tasks (id, chapter_text, image_count, status) VALUES (?, ?, ?, ?)",
                    ("legacy-task", "old chapter", 1, "done"),
                )
                conn.commit()
            finally:
                conn.close()

            repo = TaskRepository(db_path)
            repo.init_schema(legacy_owner_id="owner-a")

            self.assertEqual(repo.list_tasks("owner-a")[0]["id"], "legacy-task")
            self.assertEqual(repo.list_tasks("owner-b"), [])


class ServiceTests(unittest.TestCase):
    def test_service_creates_task_with_requested_number_of_prompts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            service = IllustrationService(repo, FakeAiClient(), root / "outputs")

            task = service.create_prompt_task("long chapter", 3, "owner-a")

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
            task = service.create_prompt_task("long chapter", 2, "owner-a")

            updated = service.generate_images(task["id"], "owner-a")

            self.assertEqual([image["status"] for image in updated["images"]], ["done", "done"])
            self.assertEqual(len(ai_client.image_calls), 2)
            self.assertTrue((root / "outputs" / updated["images"][0]["path"]).exists())

    def test_service_passes_image_size_to_image_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            ai_client = FakeAiClient()
            service = IllustrationService(repo, ai_client, root / "outputs")
            task = service.create_prompt_task("long chapter", 2, "owner-a")

            service.generate_images(task["id"], "owner-a", image_size="768x1024")

            self.assertEqual(ai_client.image_sizes, ["768x1024", "768x1024"])

    def test_service_regenerates_one_prompt_without_removing_other_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            ai_client = FakeAiClient()
            service = IllustrationService(repo, ai_client, root / "outputs")
            task = service.create_prompt_task("long chapter", 2, "owner-a")
            generated = service.generate_images(task["id"], "owner-a")
            kept_image = next(image for image in generated["images"] if image["prompt_position"] == 2)
            ai_client.image_calls.clear()
            ai_client.image_sizes.clear()

            updated = service.regenerate_prompt_image(
                task["id"],
                1,
                {
                    "title": "changed scene",
                    "scene_summary": "changed summary",
                    "viewpoint": "close shot",
                    "positive_prompt": "changed positive",
                    "negative_prompt": "changed negative",
                },
                "owner-a",
                image_size="768x1024",
            )

            self.assertEqual(ai_client.image_calls, ["changed positive"])
            self.assertEqual(ai_client.image_sizes, ["768x1024"])
            self.assertEqual(updated["prompts"][0]["title"], "changed scene")
            self.assertEqual(len(updated["images"]), 2)
            self.assertEqual(
                next(image for image in updated["images"] if image["prompt_position"] == 2)["id"],
                kept_image["id"],
            )

    def test_service_rejects_image_count_outside_one_to_ten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            service = IllustrationService(repo, FakeAiClient(), root / "outputs")

            with self.assertRaises(ValueError):
                service.create_prompt_task("chapter", 11, "owner-a")

    def test_service_rejects_other_owner_task_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = TaskRepository(root / "app.db")
            repo.init_schema()
            service = IllustrationService(repo, FakeAiClient(), root / "outputs")
            task = service.create_prompt_task("long chapter", 1, "owner-a")

            with self.assertRaises(KeyError):
                service.generate_images(task["id"], "owner-b")


if __name__ == "__main__":
    unittest.main()
