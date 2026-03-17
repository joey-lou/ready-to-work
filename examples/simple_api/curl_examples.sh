#!/bin/bash
# Run server: uvicorn main:app --reload
BASE=http://127.0.0.1:8000

curl -s -X POST "$BASE/tasks" -H "Content-Type: application/json" -d '{"title":"First","description":"A task"}' | jq .
curl -s "$BASE/tasks" | jq .
curl -s "$BASE/tasks/<id>" | jq .   # replace <id> with id from POST response
curl -s -X PUT "$BASE/tasks/<id>" -H "Content-Type: application/json" -d '{"title":"Updated","description":"Done","completed":true}' | jq .
curl -s -X DELETE "$BASE/tasks/<id>" | jq .
