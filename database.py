"""
Database connection and session management.

Provides SQLAlchemy engine, session factory, and helper functions for database operations.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from config import config

logger = logging.getLogger(__name__)

# Create database engine with connection pooling
engine = create_engine(
    config.database_url,
    poolclass=QueuePool,
    pool_size=10,  # Base number of connections
    max_overflow=20,  # Additional connections under load
    pool_pre_ping=True,  # Verify connections before use (prevents stale connections)
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=False,  # Set to True for SQL query logging (debug only)
)


# Configure SQLite foreign key support (if using SQLite for testing)
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable foreign key constraints for SQLite."""
    if 'sqlite' in config.database_url:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for getting database sessions.

    Usage in FastAPI:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            ...

    Usage elsewhere:
        db = next(get_db())
        try:
            # Use db
            db.commit()
        except:
            db.rollback()
            raise
        finally:
            db.close()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_db_session() as db:
            job = db.query(TranscriptionJob).filter_by(id=job_id).first()
            # Session automatically committed on success, rolled back on exception
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    Initialize database schema.

    Creates all tables defined in models.py if they don't exist.
    For production, use Alembic migrations instead.
    """
    from models import Base

    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def check_db_connection() -> bool:
    """
    Check if database connection is working.

    Returns:
        True if connection successful, False otherwise
    """
    try:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database connection check passed")
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


def get_db_stats() -> dict:
    """
    Get database connection pool statistics.

    Returns:
        Dictionary with pool size, checked out connections, overflow, etc.
    """
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "checked_in": pool.checkedin(),
    }
