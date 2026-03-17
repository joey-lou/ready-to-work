# Task: Create a Simple REST API

## Overview
Build a minimal REST API for managing a todo list.

## Requirements

### Functional
- Create a FastAPI-based REST API
- Implement CRUD operations for "tasks" (not to be confused with devflow tasks)
- Each task has: id, title, description, completed (boolean), created_at
- Store data in-memory (dict/list) for simplicity

### Endpoints
- `GET /tasks` - List all tasks
- `GET /tasks/{id}` - Get single task
- `POST /tasks` - Create task
- `PUT /tasks/{id}` - Update task
- `DELETE /tasks/{id}` - Delete task

### Technical
- Python 3.11+
- FastAPI with Pydantic models
- Proper error handling (404 for missing tasks)
- Return JSON responses

## Constraints
- No database required (in-memory storage is fine)
- No authentication needed
- Keep it simple - single file is acceptable

## Success Criteria
- All 5 endpoints work correctly
- Proper HTTP status codes (200, 201, 404)
- Clean, readable code
- Can be tested with curl or similar
