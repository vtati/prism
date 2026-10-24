"""Test isolation: point the whole suite at a throwaway PRISM_DATA_DIR.

config.py reads PRISM_DATA_DIR once at import time, and pytest imports this
conftest before any test module (and therefore before any app.* import), so
setting it here keeps test runs — edition counter, checkpoints, past-runs,
run artifacts — out of the shared data/ dir. Without this, every test run
advanced the production edition counter.
"""
import os
import tempfile

os.environ["PRISM_DATA_DIR"] = tempfile.mkdtemp(prefix="prism-test-data-")
os.environ.setdefault("PRISM_CAROUSEL_VIA_MCP", "0")  # direct renderer in tests
