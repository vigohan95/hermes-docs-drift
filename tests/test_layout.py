"""The test suite must run whatever the checkout directory is called.

The repository root has an ``__init__.py`` because Hermes loads the plugin from
it. Left alone, pytest treats the root as a test package and imports that file
before the first test. Its relative import only works when the directory name
happens to be a valid Python identifier, so ``git clone`` into the default
``hermes-docs-drift`` and ``pytest`` gave one setup error per test.
"""

import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

PROBE = """
from docsdrift.scan import Scanner


def test_probe():
    assert Scanner.__name__ == "Scanner"
"""


@pytest.mark.parametrize("dirname", ["hermes-docs-drift", "plugin", "docsdrift"])
def test_suite_runs_in_a_checkout_named(dirname, tmp_path):
    clone = tmp_path / dirname
    (clone / "tests").mkdir(parents=True)
    for rel in ("__init__.py", "pytest.ini", "tests/conftest.py"):
        shutil.copyfile(os.path.join(ROOT, *rel.split("/")), clone / rel)
    shutil.copytree(os.path.join(ROOT, "docsdrift"), clone / "docsdrift",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (clone / "tests" / "test_probe.py").write_text(PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    run = subprocess.run([sys.executable, "-m", "pytest"], cwd=clone, env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "1 passed" in run.stdout
