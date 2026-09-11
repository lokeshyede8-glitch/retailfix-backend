from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import os
import re
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Railway / Heroku compatibility: convert legacy postgres:// to postgresql://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    raise ValueError(
        "DATABASE_URL environment variable is missing or points to SQLite.\n"
        "PostgreSQL is now the only supported database.\n"
        "Please configure DATABASE_URL in your .env file with a valid PostgreSQL URL."
    )

logger.info(f"Current Folder: {os.getcwd()}")

masked_url = DATABASE_URL
if "@" in DATABASE_URL:
    masked_url = re.sub(r":([^:@]+)@", r":***@", DATABASE_URL)

logger.info(f"Database URL: {masked_url}")

try:
    engine = create_engine(
        DATABASE_URL,

        # Connection Pool Settings
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_reset_on_return="rollback",

        # PostgreSQL Connection Settings
        connect_args={
            "client_encoding": "utf8",
            "application_name": "RetailFixCRM"
        },

        future=True,
        echo=False,
    )

    # Verify connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()

    logger.info("=" * 72)
    logger.info("Successfully connected to PostgreSQL database!")
    logger.info("=" * 72)

except Exception:
    logger.exception("[FATAL ERROR] PostgreSQL database connection failed!")
    raise

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()