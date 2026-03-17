from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

tasks: dict[str, dict] = {}


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    completed: bool = False


class Task(BaseModel):
    id: str
    title: str
    description: str
    completed: bool
    created_at: datetime


@app.get("/tasks")
def list_tasks() -> list[Task]:
    return [Task(**t) for t in tasks.values()]


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> Task:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**tasks[task_id])


@app.post("/tasks", status_code=201)
def create_task(body: TaskCreate) -> Task:
    task_id = str(uuid4())
    now = datetime.utcnow()
    tasks[task_id] = {
        "id": task_id,
        "title": body.title,
        "description": body.description,
        "completed": body.completed,
        "created_at": now,
    }
    return Task(**tasks[task_id])


@app.put("/tasks/{task_id}")
def update_task(task_id: str, body: TaskCreate) -> Task:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    t = tasks[task_id]
    t["title"] = body.title
    t["description"] = body.description
    t["completed"] = body.completed
    return Task(**t)


@app.delete("/tasks/{task_id}", status_code=200)
def delete_task(task_id: str) -> dict:
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    del tasks[task_id]
    return {"ok": True}
