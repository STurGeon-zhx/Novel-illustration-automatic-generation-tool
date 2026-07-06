from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
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
    visual_style: str | None = None
    genre_style: str | None = None


class PromptItem(BaseModel):
    title: str = Field(min_length=1)
    scene_summary: str = Field(min_length=1)
    viewpoint: str = Field(min_length=1)
    positive_prompt: str = Field(min_length=1)
    negative_prompt: str = Field(min_length=1)


class UpdatePromptsRequest(BaseModel):
    prompts: list[PromptItem] = Field(min_length=1, max_length=10)


class GenerateImagesRequest(BaseModel):
    image_size: str | None = Field(default=None, pattern=r"^\d+x\d+$")


class RegeneratePromptImageRequest(PromptItem):
    image_size: str | None = Field(default=None, pattern=r"^\d+x\d+$")


settings = load_settings()
repository = TaskRepository(settings.database_path)
repository.init_schema(legacy_owner_id=settings.legacy_owner_id)
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


def get_client_id(
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    client_id_cookie: str | None = Cookie(default=None, alias="client_id"),
):
    client_id = (x_client_id or client_id_cookie or "").strip()
    if len(client_id) < 12 or len(client_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid client id.")
    return client_id


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/client/bootstrap")
def client_bootstrap(request: Request):
    client_host = request.client.host if request.client else ""
    if settings.legacy_owner_id and client_host in {"127.0.0.1", "::1"}:
        return {"legacy_owner_id": settings.legacy_owner_id}
    return {"legacy_owner_id": ""}


@app.get("/api/tasks")
def list_tasks(owner_id: str = Depends(get_client_id)):
    return {"tasks": repository.list_tasks(owner_id)}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, owner_id: str = Depends(get_client_id)):
    task = repository.get_task(task_id, owner_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, owner_id: str = Depends(get_client_id)):
    if not repository.delete_task(task_id, owner_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"deleted": True}


@app.post("/api/tasks")
def create_task(request: CreateTaskRequest, owner_id: str = Depends(get_client_id)):
    try:
        return service.create_prompt_task(
            request.chapter_text,
            request.image_count,
            owner_id,
            request.visual_style,
            request.genre_style,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.put("/api/tasks/{task_id}/prompts")
def update_prompts(task_id: str, request: UpdatePromptsRequest, owner_id: str = Depends(get_client_id)):
    if repository.get_task(task_id, owner_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        return service.update_prompts(task_id, [item.model_dump() for item in request.prompts], owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/generate")
def generate_images(
    task_id: str,
    request: GenerateImagesRequest | None = None,
    owner_id: str = Depends(get_client_id),
):
    try:
        return service.generate_images(task_id, owner_id, image_size=request.image_size if request else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/prompts/{position}/generate")
def regenerate_prompt_image(
    task_id: str,
    position: int,
    request: RegeneratePromptImageRequest,
    owner_id: str = Depends(get_client_id),
):
    try:
        return service.regenerate_prompt_image(
            task_id,
            position,
            request.model_dump(exclude={"image_size"}),
            owner_id,
            image_size=request.image_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/images/{image_id}/retry")
def retry_image(task_id: str, image_id: int, owner_id: str = Depends(get_client_id)):
    try:
        return service.retry_image(task_id, image_id, owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}/images/{image_id}/file")
def get_image_file(task_id: str, image_id: int, owner_id: str = Depends(get_client_id)):
    image = repository.get_image(task_id, image_id, owner_id)
    if image is None or image["status"] != "done" or not image["path"]:
        raise HTTPException(status_code=404, detail="Image not found.")

    outputs_root = settings.outputs_dir.resolve()
    image_path = (settings.outputs_dir / image["path"]).resolve()
    if outputs_root not in image_path.parents:
        raise HTTPException(status_code=404, detail="Image not found.")
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found.")
    return FileResponse(image_path)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
