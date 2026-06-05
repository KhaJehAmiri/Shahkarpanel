from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import (
    SQLALCHEMY_DATABASE_URL,
    SQLALCHEMY_POOL_SIZE,
    SQLALCHEMY_MAX_OVERFLOW,
)

IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith('sqlite')
IS_POSTGRESQL = SQLALCHEMY_DATABASE_URL.startswith('postgresql')

# Case-insensitive collation for identifier columns (username, node name).
# SQLite uses the built-in NOCASE collation. PostgreSQL has no such collation;
# case-insensitivity is provided through the CITEXT type (see models.py) and a
# dedicated migration. MySQL handles it via its own collations in migrations.
USERNAME_COLLATION = "NOCASE" if IS_SQLITE else None

if IS_SQLITE:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=SQLALCHEMY_POOL_SIZE,
        max_overflow=SQLALCHEMY_MAX_OVERFLOW,
        pool_recycle=3600,
        pool_timeout=10,
        # Validate connections before use; avoids "server closed the connection"
        # errors on long-lived pooled connections (important for PostgreSQL/HA).
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass
