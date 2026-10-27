from alembic import context

from app import models  # noqa: F401
from app.config import Settings
from app.db import Base, make_engine

config = context.config
settings = Settings()
if not settings.database_url:
    raise RuntimeError("Configure CAREERPILOT_DATABASE_URL in backend/.env before migrating")

if context.is_offline_mode():
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()

