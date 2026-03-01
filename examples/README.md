# Tasks API

Run the API: `uvicorn main:app --reload` (default: http://127.0.0.1:8000).

## Verify all 5 endpoints

**Script:** `python verify_api.py` (requires `httpx`: `pip install httpx`). Prints OK/FAIL for each endpoint and exits 0 if all pass.

**curl:**

```bash
# GET /tasks
curl -s http://127.0.0.1:8000/tasks

# POST /tasks
curl -s -X POST http://127.0.0.1:8000/tasks -H "Content-Type: application/json" -d '{"title":"Test","description":"","completed":false}'
# Use the returned "id" in the next two.

# GET /tasks/{id}
curl -s http://127.0.0.1:8000/tasks/<id>

# PUT /tasks/{id}
curl -s -X PUT http://127.0.0.1:8000/tasks/<id> -H "Content-Type: application/json" -d '{"title":"Updated","completed":true}'

# DELETE /tasks/{id}
curl -s -X DELETE http://127.0.0.1:8000/tasks/<id>
```
