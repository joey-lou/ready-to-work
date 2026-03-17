# Plan: Simple REST API (Todo list)

## 1. Scope
- Single FastAPI app (single file acceptable)
- In-memory store: dict keyed by task id
- Pydantic models for request/response

## 2. Implementation steps
1. **Implement API and storage** – FastAPI app with Pydantic task model (id, title, description, completed, created_at), in-memory dict, and all five CRUD endpoints with correct status codes (200, 201, 404). Add requirements (FastAPI, uvicorn). Optional: minimal tests or curl commands.

## 3. Done when
- All 5 endpoints work; status codes correct; code in project root (not under .rtw/).
