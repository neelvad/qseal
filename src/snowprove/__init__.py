"""Compatibility import shim for the former ``snowprove`` package name."""

from __future__ import annotations

import qseal as _qseal
from qseal import *  # noqa: F403

__path__ = _qseal.__path__
