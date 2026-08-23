import pytest
from sqlalchemy.orm import Session

from osbak.db import create_engine_by_url, init_db, make_session_factory


@pytest.fixture()
def session() -> Session:
    engine = create_engine_by_url("sqlite://")
    init_db(engine)
    factory = make_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
