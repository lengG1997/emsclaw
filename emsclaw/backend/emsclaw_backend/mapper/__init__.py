"""backend mapper layer — ORM persistence.

Each mapper owns one (or a few) ORM tables and exposes CRUD-style methods
on plain Device rows. No business rules, no validation beyond SQL.

Mirrors the Java @Mapper layer.
"""