# Active subtask

Implement the FastAPI todo REST API in the **workspace (project root)**.

- Create `main.py` (or single app file) with FastAPI app, Pydantic model for tasks (id, title, description, completed, created_at), in-memory storage (dict/list), and endpoints: `GET /tasks`, `GET /tasks/{id}`, `POST /tasks`, `PUT /tasks/{id}`, `DELETE /tasks/{id}`. Return JSON; use 200/201/404 as appropriate; raise HTTPException for missing task.
- Add `requirements.txt` with FastAPI and uvicorn (and pydantic if needed).
- Optionally add a minimal test or curl examples to verify the endpoints.

Do not create implementation files under `.rtw/` or this run directory.

---

## Review findings

- **main.py**: FastAPI app with Task/TaskCreate Pydantic models (id, title, description, completed, created_at), in-memory `tasks` dict, all five CRUD endpoints; 201 on POST, 404 via HTTPException for missing task; JSON responses.
- **requirements.txt**: FastAPI, uvicorn, pydantic present.
- **curl_examples.sh**: Optional curl examples added.
- Implementation under workspace root (examples/), not under .rtw/. **PASSED.**
