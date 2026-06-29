import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_PROMPT_FIELDS = [
    "title",
    "scene_summary",
    "viewpoint",
    "positive_prompt",
    "negative_prompt",
]


def extract_prompt_items(content):
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    data = json.loads(text)
    if isinstance(data, dict):
        if all(field in data for field in REQUIRED_PROMPT_FIELDS):
            data = [data]
        for key in ("prompts", "scenes", "items"):
            if key in data:
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError("Prompt model response must be a JSON array.")

    items = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Prompt item {index} must be an object.")
        normalized = {}
        for field in REQUIRED_PROMPT_FIELDS:
            value = str(item.get(field, "")).strip()
            if not value:
                raise ValueError(f"Prompt item {index} missing field: {field}")
            normalized[field] = value
        items.append(normalized)
    return items


class OpenAICompatibleClient:
    def __init__(self, settings):
        self.settings = settings

    def split_chapter(self, chapter_text, image_count):
        last_count = None
        for attempt in range(getattr(self.settings, "max_retries", 2) + 1):
            payload = self._build_split_payload(chapter_text, image_count, last_count)
            response = self._post_json("/chat/completions", payload)
            content = response["choices"][0]["message"]["content"]
            items = extract_prompt_items(content)
            if len(items) == image_count:
                return items
            last_count = len(items)
        raise ValueError(f"Expected {image_count} prompts, got {last_count}.")

    def _build_split_payload(self, chapter_text, image_count, previous_count=None):
        correction = ""
        if previous_count is not None:
            correction = (
                f"上一次返回了 {previous_count} 个提示词，数量错误。"
                f"这次必须返回正好 {image_count} 个提示词，不要返回空数组。"
            )
        payload = {
            "model": self.settings.text_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是小说插画分镜师。只输出 JSON 对象，不要解释。"
                        '输出格式必须是 {"prompts":[...]}。prompts 数组里的每个对象必须包含 '
                        "title、scene_summary、viewpoint、positive_prompt、negative_prompt。"
                        "positive_prompt 约 200 中文字，必须是生图模型可识别的画面提示词。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{correction}"
                        f"请把以下小说章节拆成正好 {image_count} 个不同场景视角的插画提示词，"
                        f'并返回 {{"prompts":[...]}}，prompts 数组长度必须等于 {image_count}。\n\n'
                        f"{chapter_text}"
                    ),
                },
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        return payload

    def generate_image(self, prompt, output_path):
        image_prompt = prompt["positive_prompt"]
        if prompt.get("negative_prompt"):
            image_prompt = f"{image_prompt}\n\n避免：{prompt['negative_prompt']}"

        payload = {
            "model": self.settings.image_model,
            "prompt": image_prompt,
            "size": self.settings.image_size,
        }
        if self.settings.image_return_base64:
            payload["return_base64"] = True

        response = self._post_json("/images/generations", payload)
        image = response["data"][0]
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if image.get("b64_json"):
            output_path.write_bytes(base64.b64decode(image["b64_json"]))
            return output_path

        if image.get("url"):
            request = urllib.request.Request(image["url"], headers={"User-Agent": "novel-illustrator/1.0"})
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as resp:
                output_path.write_bytes(resp.read())
            return output_path

        raise ValueError("Image response must contain b64_json or url.")

    def _post_json(self, path, payload):
        url = self.settings.base_url.rstrip("/") + path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
        )
        max_retries = getattr(self.settings, "max_retries", 2)
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 or exc.code >= 500:
                    if attempt < max_retries:
                        time.sleep(min(2 ** attempt, 5))
                        continue
                raise RuntimeError(f"Model API error {exc.code}: {detail}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                if attempt >= max_retries:
                    raise RuntimeError(f"Model API connection failed after {attempt + 1} attempts: {exc}") from exc
                time.sleep(min(2 ** attempt, 5))

        raise RuntimeError("Model API request failed.")
