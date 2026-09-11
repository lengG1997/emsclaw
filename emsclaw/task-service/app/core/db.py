"""task-service DB connection (migrated from MongoDB to PostgreSQL/SQLAlchemy).

The legacy MongoDB connection layer lived here. The service now uses the
SQLAlchemy connection layer in ``app.db.session`` (async + sync engines,
``init_db``, ``get_session``). This module is intentionally kept as a near-empty
stub for backwards import compatibility; new code should import from
``app.db.session`` instead.
"""
