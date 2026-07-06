from pathlib import Path


VALID_VISUAL_STYLES = {"urban_live", "ancient_live", "urban_anime", "ancient_anime"}
VALID_GENRE_STYLES = {"romance", "fantasy", "suspense", "scifi", "apocalypse"}


class IllustrationService:
    def __init__(self, repository, ai_client, outputs_dir):
        self.repository = repository
        self.ai_client = ai_client
        self.outputs_dir = Path(outputs_dir)

    def create_prompt_task(self, chapter_text, image_count, owner_id, visual_style=None, genre_style=None):
        self._validate_task_input(chapter_text, image_count, visual_style, genre_style)
        task_id = self.repository.create_task(
            chapter_text.strip(),
            image_count,
            owner_id,
            visual_style,
            genre_style,
        )
        try:
            prompts = self.ai_client.split_chapter(chapter_text.strip(), image_count, visual_style, genre_style)
            self.repository.replace_prompts(task_id, prompts, owner_id)
            return self.repository.get_task(task_id, owner_id)
        except Exception as exc:
            self.repository.update_task_status(task_id, "failed", str(exc), owner_id)
            raise

    def update_prompts(self, task_id, prompts, owner_id):
        if not prompts:
            raise ValueError("At least one prompt is required.")
        if len(prompts) > 10:
            raise ValueError("At most 10 prompts are allowed.")
        for prompt in prompts:
            self._validate_prompt(prompt)
        if not self.repository.replace_prompts(task_id, prompts, owner_id):
            raise KeyError("Task not found.")
        return self.repository.get_task(task_id, owner_id)

    def generate_images(self, task_id, owner_id, image_size=None):
        task = self.repository.get_task(task_id, owner_id)
        if task is None:
            raise KeyError("Task not found.")
        if not task["prompts"]:
            raise ValueError("Task has no prompts.")

        self.repository.update_task_status(task_id, "generating", owner_id=owner_id)
        for prompt in task["prompts"]:
            relative_path = Path(task_id) / f"scene-{prompt['position']:02d}.png"
            image_id = self.repository.create_image(task_id, prompt["position"], str(relative_path))
            try:
                output_path = self.outputs_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                self.ai_client.generate_image(prompt, output_path, image_size=image_size)
                self.repository.mark_image_done(image_id, str(relative_path))
            except Exception as exc:
                self.repository.mark_image_failed(image_id, str(exc))

        updated = self.repository.get_task(task_id, owner_id)
        has_failed = any(image["status"] == "failed" for image in updated["images"])
        self.repository.update_task_status(
            task_id,
            "partial_failed" if has_failed else "done",
            owner_id=owner_id,
        )
        return self.repository.get_task(task_id, owner_id)

    def regenerate_prompt_image(self, task_id, position, prompt, owner_id, image_size=None):
        self._validate_prompt(prompt)
        task = self.repository.get_task(task_id, owner_id)
        if task is None:
            raise KeyError("Task not found.")
        if position not in {item["position"] for item in task["prompts"]}:
            raise KeyError("Prompt not found.")
        if not self.repository.update_prompt(task_id, position, prompt, owner_id):
            raise KeyError("Prompt not found.")

        relative_path = Path(task_id) / f"scene-{position:02d}.png"
        self.repository.delete_images_for_prompt(task_id, position)
        image_id = self.repository.create_image(task_id, position, str(relative_path))
        try:
            output_path = self.outputs_dir / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.ai_client.generate_image({**prompt, "position": position}, output_path, image_size=image_size)
            self.repository.mark_image_done(image_id, str(relative_path))
        except Exception as exc:
            self.repository.mark_image_failed(image_id, str(exc))

        updated = self.repository.get_task(task_id, owner_id)
        has_failed = any(image["status"] == "failed" for image in updated["images"])
        self.repository.update_task_status(
            task_id,
            "partial_failed" if has_failed else "done",
            owner_id=owner_id,
        )
        return self.repository.get_task(task_id, owner_id)

    def retry_image(self, task_id, image_id, owner_id):
        task = self.repository.get_task(task_id, owner_id)
        if task is None:
            raise KeyError("Task not found.")
        images = {image["id"]: image for image in task["images"]}
        image = images.get(image_id)
        if image is None:
            raise KeyError("Image not found.")
        prompts = {prompt["position"]: prompt for prompt in task["prompts"]}
        prompt = prompts[image["prompt_position"]]

        try:
            output_path = self.outputs_dir / image["path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.ai_client.generate_image(prompt, output_path)
            self.repository.mark_image_done(image_id, image["path"])
            self.repository.update_task_status(task_id, "done", owner_id=owner_id)
        except Exception as exc:
            self.repository.mark_image_failed(image_id, str(exc))
            self.repository.update_task_status(task_id, "partial_failed", owner_id=owner_id)
        return self.repository.get_task(task_id, owner_id)

    def _validate_task_input(self, chapter_text, image_count, visual_style=None, genre_style=None):
        if not chapter_text or not chapter_text.strip():
            raise ValueError("Chapter text is required.")
        if image_count < 1 or image_count > 10:
            raise ValueError("Image count must be between 1 and 10.")
        if visual_style not in VALID_VISUAL_STYLES:
            raise ValueError("Visual style is required.")
        if genre_style not in VALID_GENRE_STYLES:
            raise ValueError("Genre style is required.")

    def _validate_prompt(self, prompt):
        for field in ("title", "scene_summary", "viewpoint", "positive_prompt", "negative_prompt"):
            if not str(prompt.get(field, "")).strip():
                raise ValueError(f"Prompt field is required: {field}")
