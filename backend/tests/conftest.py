import pytest

from app.core.config import get_settings
from app.digital_twin.network import load_network
from app.sumo.environment import check_sumo


@pytest.fixture(scope="session")
def net():
    return load_network(get_settings().network_file)


def pytest_collection_modifyitems(config, items):
    if not check_sumo().available:
        skip = pytest.mark.skip(reason="SUMO not installed (environment limitation)")
        for it in items:
            if "sumo" in it.keywords:
                it.add_marker(skip)
