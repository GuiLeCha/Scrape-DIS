#!/usr/bin/env python
"""
AWS Academy Material Extractor
Wrapper de compatibilidad para aws_academy_extractor.py
Redirige al paquete modularizado `aws_extractor`.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Exportaciones para mantener retrocompatibilidad total
from aws_extractor.config import APP_NAME, Settings
from aws_extractor.core.drive import GoogleDriveUploader
from aws_extractor.core.extractor import Extractor
from aws_extractor.core.player import ContentPlayer
from aws_extractor.ui.app import App, launch
from aws_extractor.utils import enable_windows_dpi_awareness, safe_name

if __name__ == "__main__":
    launch()
