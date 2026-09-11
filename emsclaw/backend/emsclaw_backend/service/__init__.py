"""backend service layer — business logic.

Each service orchestrates mappers + enforces business rules. No HTTP concerns,
no SQL — both are pushed down (mapper) or up (controller).

Mirrors the Java @Service layer.
"""