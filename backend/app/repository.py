import sqlite3
import uuid
from contextlib import closing
from pathlib import Path


class TaskRepository:
    def __init__(self, database_path):
        self.database_path = Path(database_path)

    def init_schema(self, legacy_owner_id=None):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT,
                    chapter_text TEXT NOT NULL,
                    image_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    scene_summary TEXT NOT NULL,
                    viewpoint TEXT NOT NULL,
                    positive_prompt TEXT NOT NULL,
                    negative_prompt TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    prompt_position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    path TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_owner_column(conn)
            if legacy_owner_id:
                conn.execute(
                    "UPDATE tasks SET owner_id = ? WHERE owner_id IS NULL OR owner_id = ''",
                    (legacy_owner_id,),
                )
            conn.commit()

    def create_task(self, chapter_text, image_count, owner_id):
        task_id = uuid.uuid4().hex
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, owner_id, chapter_text, image_count, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, owner_id, chapter_text, image_count, "created"),
            )
            conn.commit()
        return task_id

    def update_task_status(self, task_id, status, error_message=None, owner_id=None):
        with closing(self._connect()) as conn:
            if owner_id is None:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status, error_message, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND owner_id = ?
                    """,
                    (status, error_message, task_id, owner_id),
                )
            conn.commit()

    def replace_prompts(self, task_id, prompts, owner_id):
        with closing(self._connect()) as conn:
            if not self._task_exists(conn, task_id, owner_id):
                return False
            conn.execute("DELETE FROM prompts WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM images WHERE task_id = ?", (task_id,))
            for position, prompt in enumerate(prompts, start=1):
                conn.execute(
                    """
                    INSERT INTO prompts (
                        task_id, position, title, scene_summary, viewpoint,
                        positive_prompt, negative_prompt
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        position,
                        prompt["title"],
                        prompt["scene_summary"],
                        prompt["viewpoint"],
                        prompt["positive_prompt"],
                        prompt["negative_prompt"],
                    ),
                )
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_id = ?",
                ("prompts_ready", task_id, owner_id),
            )
            conn.commit()
            return True

    def update_prompt(self, task_id, position, prompt, owner_id):
        with closing(self._connect()) as conn:
            if not self._task_exists(conn, task_id, owner_id):
                return False
            cursor = conn.execute(
                """
                UPDATE prompts
                SET title = ?, scene_summary = ?, viewpoint = ?,
                    positive_prompt = ?, negative_prompt = ?
                WHERE task_id = ? AND position = ?
                """,
                (
                    prompt["title"],
                    prompt["scene_summary"],
                    prompt["viewpoint"],
                    prompt["positive_prompt"],
                    prompt["negative_prompt"],
                    task_id,
                    position,
                ),
            )
            conn.execute(
                "UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_id = ?",
                (task_id, owner_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_images_for_prompt(self, task_id, prompt_position):
        with closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM images WHERE task_id = ? AND prompt_position = ?",
                (task_id, prompt_position),
            )
            conn.commit()

    def create_image(self, task_id, prompt_position, path):
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO images (task_id, prompt_position, status, path)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, prompt_position, "running", path),
            )
            conn.commit()
            return cursor.lastrowid

    def mark_image_done(self, image_id, path):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE images
                SET status = ?, path = ?, error_message = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("done", path, image_id),
            )
            conn.commit()

    def mark_image_failed(self, image_id, error_message):
        with closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE images
                SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("failed", error_message, image_id),
            )
            conn.commit()

    def list_tasks(self, owner_id):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, image_count, status, error_message, created_at, updated_at,
                       substr(chapter_text, 1, 120) AS chapter_preview
                FROM tasks
                WHERE owner_id = ?
                ORDER BY created_at DESC
                """,
                (owner_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_task(self, task_id, owner_id):
        with closing(self._connect()) as conn:
            task = conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND owner_id = ?",
                (task_id, owner_id),
            ).fetchone()
            if task is None:
                return None
            prompts = conn.execute(
                "SELECT * FROM prompts WHERE task_id = ? ORDER BY position",
                (task_id,),
            ).fetchall()
            images = conn.execute(
                "SELECT * FROM images WHERE task_id = ? ORDER BY prompt_position",
                (task_id,),
            ).fetchall()
            result = dict(task)
            result["prompts"] = [dict(row) for row in prompts]
            result["images"] = [dict(row) for row in images]
            return result

    def delete_task(self, task_id, owner_id):
        with closing(self._connect()) as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ?", (task_id, owner_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_image(self, task_id, image_id, owner_id):
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT images.*
                FROM images
                JOIN tasks ON tasks.id = images.task_id
                WHERE images.id = ? AND images.task_id = ? AND tasks.owner_id = ?
                """,
                (image_id, task_id, owner_id),
            ).fetchone()
            return dict(row) if row else None

    def _ensure_owner_column(self, conn):
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN owner_id TEXT")

    def _task_exists(self, conn, task_id, owner_id):
        row = conn.execute(
            "SELECT 1 FROM tasks WHERE id = ? AND owner_id = ?",
            (task_id, owner_id),
        ).fetchone()
        return row is not None

    def _connect(self):
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
