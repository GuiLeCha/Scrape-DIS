#!/usr/bin/env python
from __future__ import annotations

import sys
from pathlib import Path

# Añade el directorio base al sys.path para importación limpia
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aws_extractor.ui.app import launch

if __name__ == "__main__":
    launch()

