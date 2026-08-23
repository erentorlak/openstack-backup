import pytest
from sqlalchemy.orm import Session

from sqlalchemy import create_engine

from osbak.db import init_db, make_session_factory


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    init_db(engine)
    factory = make_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
