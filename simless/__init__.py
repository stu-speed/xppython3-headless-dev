# --- Universal import bootstrap for simless ---
import sys
from pathlib import Path

# Resolve project root (simless/__init__.py → project root)
_project_root = Path(__file__).resolve().parents[1]

_plugins_root = _project_root / "Resources" / "plugins"
_xppython3_root = _plugins_root / "XPPython3"
_pyplugins_root = _plugins_root / "PythonPlugins"

# Insert correct roots FIRST
sys.path.insert(0, str(_xppython3_root))
sys.path.insert(1, str(_plugins_root))
sys.path.insert(2, str(_pyplugins_root))
