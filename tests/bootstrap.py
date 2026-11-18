"""测试引导：在隔离解释器（python -I）下也能导入项目包。

unittest discovery 会把本目录加入 sys.path；由此把项目根目录补入，
不依赖 PYTHONPATH 或调用时的工作目录。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
