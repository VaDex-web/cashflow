"""Тесты запускаются и без установки пакета: добавляем core/ и tests/ в sys.path."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
