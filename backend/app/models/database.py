"""
Database connection and session management using SQLAlchemy.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings


def _normalize_db_url(url: str) -> str:
    """
    Ensure Postgres URLs use the installed driver (psycopg v3).

    SQLAlchemy defaults a bare ``postgresql://`` URL to the psycopg2 driver,
    which isn't installed (we ship ``psycopg[binary]`` v3). Rewrite the scheme
    to ``postgresql+psycopg://`` so it uses psycopg v3. SQLite / other URLs
    are left untouched.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):  # some providers use this alias
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


engine = create_engine(
    _normalize_db_url(settings.database_url),
    # Keep a small pool; scale up when moving to production
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass


def get_db():
    """
    FastAPI dependency that yields a database session
    and guarantees it is closed after the request.

    Usage:
        @router.post("/")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
