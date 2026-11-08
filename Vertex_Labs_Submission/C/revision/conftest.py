import importlib
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_addoption(parser):
    parser.addoption('--implementation', default='fix_revised')


@pytest.fixture
def implementation(request):
    return importlib.import_module(request.config.getoption('--implementation'))
