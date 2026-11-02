"""Где лежат файлы программы и где лежат данные пользователя.

В исходниках это одна папка. В exe страницы берутся из сборки, а база, .env и ключи — рядом с exe.
"""

import sys
from pathlib import Path


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
