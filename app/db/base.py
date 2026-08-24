from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every SQLAlchemy model.

    `Base.metadata` collects the table definitions of all imported models.
    A model is only registered once its module has been imported, which
    matters for Alembic autogenerate in Phase 4.
    """
