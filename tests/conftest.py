import pytest

from stockbot.config import RuntimeConfig
from stockbot.db import init_db, make_engine, make_session_factory


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite://")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def runtime_cfg():
    return RuntimeConfig()
