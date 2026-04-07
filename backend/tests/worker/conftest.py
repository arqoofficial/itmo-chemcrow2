"""Worker test conftest — overrides the session-scoped db fixture so worker
unit tests can run without a real PostgreSQL connection."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="session", autouse=True)
def db():
    """Return a mock DB session so worker unit tests don't need a live DB."""
    yield MagicMock()
