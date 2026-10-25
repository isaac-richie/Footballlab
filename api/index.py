"""Vercel entry point: the Lab's own request handler, run as a Python serverless function.

Every path is rewritten here (vercel.json). Only the openly licensed data in the
repository is deployed, so the hosted Lab forecasts from the model alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import Handler  # noqa: E402


class handler(Handler):
    """Vercel looks for a top-level class named `handler` defined in this file."""
