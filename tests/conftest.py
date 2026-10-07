import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(EXAMPLES))

from build_sample_models import build_licensing_model  # noqa: E402

import ifcquery  # noqa: E402


@pytest.fixture(scope="session")
def model():
    """The sample licensing model (metres), built in memory. See examples/build_sample_models.py."""
    return build_licensing_model("m")


@pytest.fixture(scope="session")
def model_mm():
    """The same model stored in millimetre units."""
    return build_licensing_model("mm")


@pytest.fixture(scope="session")
def sample_path():
    return EXAMPLES / "models" / "licensing_sample.ifc"


@pytest.fixture
def q(model):
    """Run a single-statement query on the sample model and return its value."""

    def run(text, m=None):
        results = ifcquery.run(text, m or model)
        return results[-1].value

    return run
