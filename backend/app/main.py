from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_client import OpenAICompatibleClient
from .config import load_settings
from .repository import TaskRepository
from .service import IllustrationService


class CreateTaskRequest(BaseModel):
    chapter_text: str = Field(min_length=1)
    image_count: int = Field(ge=1, le=10)


class PromptItem(BaseModel):
    title: str = Field(min_length=1)
    scene_summary: str = Field(min_length=1)
    viewpoint: str = Field(min_length=1)
    positive_prompt: str = Field(min_length=1)
    negative_prompt: str = Field(min_length=1)


class UpdatePromptsRequest(BaseModel):
    prompts: list[PromptItem] = Field(min_length=1, max_length=10)


settings = load_settings()
repository = TaskRepository(settings.database_path)
repository.init_schema()
service = IllustrationService(repository, OpenAICompatibleClient(settings), settings.outputs_dir)

app = FastAPI(title="Novel Illustration Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.outputs_dir.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(settings.outputs_dir)), name="outputs")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/tasks")
def list_tasks():
    return {"tasks": repository.list_tasks()}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = repository.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks")
def create_task(request: CreateTaskRequest):
    try:
        return service.create_prompt_task(request.chapter_text, request.image_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.put("/api/tasks/{task_id}/prompts")
def update_prompts(task_id: str, request: UpdatePromptsRequest):
    if repository.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        return service.update_prompts(task_id, [item.model_dump() for item in request.prompts])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/generate")
def generate_images(task_id: str):
    try:
        return service.generate_images(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/images/{image_id}/retry")
def retry_image(task_id: str, image_id: int):
    try:
        return service.retry_image(task_id, image_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
