"""Shared fixtures for the local (non-versioned) test suite."""
import sys
from pathlib import Path

# 让测试可以直接 import app.* 而不需要安装后端为包
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
