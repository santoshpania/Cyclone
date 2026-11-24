"""Alembic environment. Migrations run as the schema owner (MIGRATIONS_DATABASE_URL)."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.settings import get_settings

url = context.config.get_main_option("sqlalchemy.url") or get_settings().migrations_url_sync


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
