from pathlib import Path


class IllustrationService:
    def __init__(self, repository, ai_client, outputs_dir):
        self.repository = repository
        self.ai_client = ai_client
        self.outputs_dir = Path(outputs_dir)

    def create_prompt_task(self, chapter_text, image_count):
        self._validate_task_input(chapter_text, image_count)
        task_id = self.repository.create_task(chapter_text.strip(), image_count)
        try:
            prompts = self.ai_client.split_chapter(chapter_text.strip(), image_count)
            self.repository.replace_prompts(task_id, prompts)
            return self.repository.get_task(task_id)
        except Exception as exc:
            self.repository.update_task_status(task_id, "failed", str(exc))
            raise

    def update_prompts(self, task_id, prompts):
        if not prompts:
            raise ValueError("At least one prompt is required.")
        if len(prompts) > 10:
            raise ValueError("At most 10 prompts are allowed.")
        for prompt in prompts:
            self._validate_prompt(prompt)
        self.repository.replace_prompts(task_id, prompts)
        return self.repository.get_task(task_id)

    def generate_images(self, task_id):
        task = self.repository.get_task(task_id)
        if task is None:
            raise KeyError("Task not found.")
        if not task["prompts"]:
            raise ValueError("Task has no prompts.")

        self.repository.update_task_status(task_id, "generating")
        for prompt in task["prompts"]:
            relative_path = Path(task_id) / f"scene-{prompt['position']:02d}.png"
            image_id = self.repository.create_image(task_id, prompt["position"], str(relative_path))
            try:
                output_path = self.outputs_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                self.ai_client.generate_image(prompt, output_path)
                self.repository.mark_image_done(image_id, str(relative_path))
            except Exception as exc:
                self.repository.mark_image_failed(image_id, str(exc))

        updated = self.repository.get_task(task_id)
        has_failed = any(image["status"] == "failed" for image in updated["images"])
        self.repository.update_task_status(task_id, "partial_failed" if has_failed else "done")
        return self.repository.get_task(task_id)

    def retry_image(self, task_id, image_id):
        task = self.repository.get_task(task_id)
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
            self.repository.update_task_status(task_id, "done")
        except Exception as exc:
            self.repository.mark_image_failed(image_id, str(exc))
            self.repository.update_task_status(task_id, "partial_failed")
        return self.repository.get_task(task_id)

    def _validate_task_input(self, chapter_text, image_count):
        if not chapter_text or not chapter_text.strip():
            raise ValueError("Chapter text is required.")
        if image_count < 1 or image_count > 10:
            raise ValueError("Image count must be between 1 and 10.")

    def _validate_prompt(self, prompt):
        for field in ("title", "scene_summary", "viewpoint", "positive_prompt", "negative_prompt"):
            if not str(prompt.get(field, "")).strip():
                raise ValueError(f"Prompt field is required: {field}")
