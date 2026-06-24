"""Shared test setup.

The app computes ``DATA_DIR`` (and a few derived paths) at import time, so we
point it at a throwaway temp directory *before* any app module is imported.
"""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="facefun-test-"))
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
