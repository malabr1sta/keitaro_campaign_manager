from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def make_sessions(url):
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite") and parsed.database not in (None, ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30}
        if parsed.drivername.startswith("sqlite")
        else {},
    )
    return sessionmaker(engine, expire_on_commit=False)
