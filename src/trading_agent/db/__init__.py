"""Database layer: SQLAlchemy schema, migrations, and session helpers.

PostgreSQL is the durable store (plan section 6). The schema follows plan
section 16. Money values use NUMERIC(20,8); quantities use the same column
type (instrument precision is enforced in application code); timestamps are
timezone-aware UTC.
"""
