# 📘 xppython3-headless-dev
### Multi‑Plugin Workspace • Sim‑less Execution • Unified FakeXP API • Deterministic Headless Runner

A clean, scalable development environment for building multiple XPPython3 plugins **without launching X‑Plane**.

This workspace provides:

• A real X‑Plane‑compatible plugin folder structure  
• A unified FakeXP API surface that mirrors xp.*  
• A standalone FakeXPRunner that simulates the full plugin lifecycle  
• Deterministic 60 Hz execution in headless or GUI mode  
• A complete XPWidget + XPLMGraphics emulation layer (DearPyGui‑backed)  
• Auto‑creating, registered, and managed DataRefs  
• A multi‑plugin environment for integration testing  

The goal is **fast, maintainable plugin development** with behavior identical inside and outside X‑Plane.

---

# 📦 Requirements

Runtime dependencies are intentionally minimal:

• python 3.12+  
• dearpygui (only required when GUI mode is enabled)

All dependencies are declared in pyproject.toml.

---

# 📁 Directory Structure

```
xplane-python-dev/
│
├── plugins/                               # All XPPython3 plugins (production-style)
│   ├── PI_ss_ota.py                        # Example hardware plugin (serial OTA)
│   ├── dev_ota_gui.py                      # Example XPWidget GUI plugin (DPG-backed)
│   │
│   ├── sshd_extlibs/                       # Shared modules
│   │   ├── ss_serial_device.py             # Serial hardware driver
│   │   └── ...                             
│   │
│   └── sshd_extensions/                    # Shared plugin architecture (namespaced)
│       ├── xp_interface.py                 # Protocol describing xp.* API surface
│       ├── datarefs.py                     # DataRefSpec, TypedAccessor, Registry, Manager
│       └── ...                             
│
├── simless/                                # Sim-less execution harnesses (no X‑Plane required)
│   ├── run_ota.py                          # Example runner: FakeXP + multiple plugins
│   │
│   └── libs/                               # Fake X‑Plane runtime (drop‑in xp module)
│       ├── fake_xp.py                      # FakeXP: public API surface
│       ├── fake_xp_runner.py               # Lifecycle, plugin loading, GUI, timing
│       ├── fake_xp_widget.py               # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py             # XPLMDisplay/XPLMGraphics simulation
│       └── fake_xp_utilities.py            # Misc XPLM utility shims (menus, commands, etc.)
│
├── stubs/
│   └── XPPython3/                           # XPPython3 .pyi stubs for IDE type checking
│
├── tests/                                   # Unit tests for FakeXP + plugin lifecycle
│
└── README.md
```

---

# 🧩 DataRef Model

FakeXP supports three interoperable dataref creation paths.

## 1. Managed DataRefs (recommended)

Defined using DataRefSpec and accessed via TypedAccessor.

Benefits:  
• Strong typing using common get/set method 
• Defaults for headless mode and easier testing  
• Required/optional semantics with readiness checking 
• Clean error handling  

## 2. Registered DataRefs (explicit)

Created by FakeXPRunner during plugin load or manually.

Benefits:  
• All the benefits above but only good for headless 

## 3. Auto‑Created DataRefs (fallback)

If a plugin accesses a missing dataref:

• FakeXPRunner promotes the dummy handle  
• Type inferred from accessor  
• Default value assigned  
• Stored globally  

All plugins share a single global dataref table.

---

## 🧩 IDE (PyCharm) Configuration

See **[docs/PYCHARM_CONFIGURATION.md](docs/PYCHARM_CONFIGURATION.md)** for full setup instructions, including how to enable XPPython3 stubs, configure Sources Roots, and run sim‑less scripts from the project root.

---

# ▶️ Minimal Sim‑less Runner

A simple runner script is all that’s needed to execute plugins outside X‑Plane.

```python
import XPPython3
from simless.libs.fake_xp import FakeXP
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))
 
xp = FakeXP(debug=True)
XPPython3.xp = xp # Replace X-Plane's xp module with FakeXP to run headless

plugins = [
    "PI_sshd_OTA",
    "PI_sshd_dev_ota_gui",
]
xp._run_plugin_lifecycle(plugins, debug=True, enable_gui=True)
```

This runner:

• Boots FakeXP  
• Replaces the real X‑Plane xp module  
• Loads any number of plugins  
• Executes the full lifecycle (start/enable/flight_loop/disable/stop)   
• Runs in GUI or headless mode  

For details on GUI behavior, see GUI_EMULATION.md.

---

# 🚀 Deployment to X‑Plane

Copy contents of plugin folder into:

X‑Plane 12/Resources/plugins/PythonPlugins/

Example:

    PI_ss_ota.py  
    extensions/  
    extlibs/  
