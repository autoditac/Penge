"""Dedicated Alembic environment for the chat OAuth database."""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from pydantic import BaseModel, ConfigDict, PostgresDsn, ValidationError
from sqlalchemy import engine_from_config, pool

config = context.config
MAX_SECRET_FILE_BYTES = 65_536

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


class MigrationSettings(BaseModel):
    """Validated mounted-secret configuration for chat migrations."""

    model_config = ConfigDict(frozen=True)

    database_url_file: Path

    @classmethod
    def from_environment(cls) -> "MigrationSettings":
        """Load the dedicated database URL file from the environment."""
        raw_path = os.environ.get("PENGE_CHAT_MIGRATION_DATABASE_URL_FILE")
        if raw_path is None:
            raise RuntimeError("PENGE_CHAT_MIGRATION_DATABASE_URL_FILE is required")
        return cls(database_url_file=Path(raw_path))

    def database_url(self) -> str:
        """Read and validate the owner-only mounted database URL."""
        path = self.database_url_file
        stat = path.stat()
        if not path.is_file() or stat.st_size < 1 or stat.st_size > MAX_SECRET_FILE_BYTES:
            raise RuntimeError("chat migration database URL must be a non-empty regular file")
        if stat.st_mode & 0o077:
            raise RuntimeError("chat migration database URL file must be owner-only")
        if hasattr(os, "getuid") and stat.st_uid != os.getuid():
            raise RuntimeError("chat migration database URL file must be process-owned")
        try:
            return str(PostgresDsn(path.read_text(encoding="utf-8").strip()))
        except ValidationError as error:
            raise RuntimeError("chat migration database URL is invalid") from error


config.set_main_option("sqlalchemy.url", MigrationSettings.from_environment().database_url())
target_metadata = None


def run_migrations_offline() -> None:
    """Run dedicated chat migrations in offline mode."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run dedicated chat migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
