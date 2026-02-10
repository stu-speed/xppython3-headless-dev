# 📘 xppython3-headless-dev
### IDE workflow • Sim‑less execution and debugging • Live X-Plane dataref injection

A structured development environment for building and debugging XPPython3 plugins natively in
an IDE (Pycharm) though runtime emulation.  Plugins can run outside of X-plane.

This project provides:

• A real X‑Plane‑compatible plugin folder structure  
• A unified FakeXP API surface that mirrors xp.*  
• A standalone FakeXPRunner that simulates the full plugin lifecycle  
• Deterministic 60 Hz execution in headless or GUI mode  
• A complete XPWidget + XPLMGraphics emulation layer (DearPyGui‑backed)  
• Auto‑creating, registered, and managed DataRefs  
• A multi‑plugin environment for integration testing  

The goal is **fast, maintainable plugin development** with behavior identical inside and outside X‑Plane.

---

# 📁 Directory Structure
```
xppython3-headless-dev/
│
├── plugins/                                # All XPPython3 plugins (production-style)
│   ├── PI_sshd_ota.py                      # Example plugin with managed datarefs
│   ├── PI_sshd_dev_ota_gui                 # Example XPWidget GUI plugin
│   │
│   ├── sshd_extlibs/                       # Shared modules
│   │   ├── ss_serial_device.py
│   │   └── ...
│   │
│   └── sshd_extensions/                    # Shared plugin architecture (namespaced)
│       ├── xp_interface.py                 # Protocol describing xp.* API surface
│       ├── datarefs.py                     # DataRefSpec, TypedAccessor, Manager
│       └── ...
│
├── simless/                                # Sim-less execution harnesses
│   ├── run_ota.py                          # Example runner: FakeXP + multiple plugins
│   │
│   └── libs/
│       ├── fake_xp.py                      # FakeXP: public xp.* API façade
│       ├── fake_xp_runner.py               # Lifecycle, plugin loading, timing
│       ├── fake_xp_widget.py               # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py             # XPLMDisplay/XPLMGraphics simulation
│       ├── fake_xp_dataref.py              # DataRef engine (managed-spec consumer + inference)
│       └── fake_xp_utilities.py            # Commands, menus, misc XPLM shims
│
├── stubs/
│   └── XPPython3/                          # XPPython3 .pyi stubs for IDE type checking
│
├── tests/                                  # Unit tests for FakeXP + plugin lifecycle
│
└── pyproject.toml                          # Poetry package management  
```
---

## 🧩 IDE (PyCharm) Development Workflow

Development workflow features:

• **Strong datatyping and code inspection with xp_typing.pyi**  
• **Debug plugins with simless runners**  
• **Run with live X-plane datarefs through the dataref_bridge**

See **[PYCHARM CONFIGURATION GUIDE](docs/PYCHARM_CONFIGURATION.md)** for full setup instructions, including how to enable XPPython3 stubs, configure Sources Roots, and run sim‑less scripts from the project root.

See **[DEVELOPER NOTES](docs/DEVELOPER_NOTES.md)** for special considerations for running python in X-Plane.

---

# 🧩 Managed DataRefs (XPPython3 extension)

Managed DataRefs provide these features:

• **Automatic waiting for required DataRefs** during startup  
• **All other datarefs use defaults used until X‑Plane provides real values**  
• **Automatic retrieval of handle and info**  
• **Generalized get/set access**

See **[DATAREF MODEL](docs/DATAREF_MODEL.md)** for more details.

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

• Boots FakeXP which emulates the X‑Plane xp module  
• Loads any number of plugins that will share the same dataref namespace
• Executes the full lifecycle (start/enable/flight_loop/disable/stop)   
• Runs in GUI or headless mode  

For details on GUI behavior, see **[GUI EMULATION NOTES](docs/GUI_EMULATION.md)**.

---

# 🚀 Deployment to X‑Plane

Copy contents of plugin folder into:

X‑Plane 12/Resources/plugins/PythonPlugins/

Example:

    PI_ss_ota.py  
    extensions/  
    extlibs/  
