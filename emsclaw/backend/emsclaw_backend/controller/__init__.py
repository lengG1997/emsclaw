"""backend controller layer — HTTP endpoints.

Each controller is a FastAPI APIRouter. Responsibilities:
- Parse/validate HTTP input (path, query, body)
- Translate HTTP exceptions into 4xx responses
- Shape responses via Pydantic DTOs

No business logic, no SQL — pushed down to service (business) and mapper
(persistence) respectively.

Mirrors the Java @RestController layer.
"""