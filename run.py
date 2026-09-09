#!/usr/bin/env python3
"""Ponto de entrada mínimo. A implementação está em src/esocial_noise/."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from esocial_noise.main import run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run())
