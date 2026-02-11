# 📘 xppython3-headless-dev
### IDE and AI friendly workflow • Sim‑less execution and debugging • Live X-Plane dataref injection

A structured development environment for building and debugging XPPython3 plugins natively in
an IDE (Pycharm) though runtime emulation of the XPPython3 API.

This project provides:

• A real X‑Plane‑compatible plugin folder structure  
• Sim-less execution/debugging of plugins with a runner simulates the full plugin lifecycle  
• Live X-plane dataref streaming through a bridge plugin  
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
│       ├── datarefs.py                     # Managed datarefs
│       └── ...                             
│
├── simless/                                # Sim-less execution harnesses
│   ├── __init__.pyi                        # Declares xp: FakeXPInterface for IDE/mypy visibility
│   │
│   ├── run_ota.py                          # Example runner: FakeXP + multiple plugins
│   │
│   └── libs/                               # Simless-only runtime + typing contracts
│       ├── fake_xp.py                      # FakeXP: public xp.* API façade
│       ├── fake_xp_runner.py               # Lifecycle, plugin loading, timing
│       ├── fake_xp_widget.py               # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py             # XPLMDisplay/XPLMGraphics simulation
│       ├── fake_xp_dataref.py              # DataRef engine (managed-spec consumer + inference)
│       ├── fake_xp_utilities.py            # Commands, menus, misc XPLM shims
│       └── fake_xp_interface.py            # Runtime shim (TYPE_CHECKING guard)
│
├── stubs/                                  # IDE-visible stubs for real XPPython3 + simless Protocols
│   ├── simless/
│   │   └── libs/
│   │       ├── simless_xp_interface.pyi    # Subset of xp API implemented for simless
│   │       └── fake_xp_interface.pyi       # FakeXPInterface + FakeRefInfo (simless-only typing)
│   │
│   └── XPPython3/
│       ├── xp.pyi                          # Full XPPython3 API surface
│       ├── xp_types.pyi                    # XPLM typedefs, enums, structs
│       └── ...                             # Other XPPython3-provided stubs
│
├── tests/                                  # Unit tests for FakeXP + plugin lifecycle
│
└── pyproject.toml                          # Poetry package management
```
---

## 🧩 IDE (PyCharm) Development Workflow

Development workflow features:

• **Strong datatyping and code inspection with xp.pyi and xp_typing.pyi**  
• **Structured to generate and validate AI generated code**  
• **Debug plugins in the IDE debugger using a simless runner**  
• **Run with live X-plane datarefs through a dataref bridge**

See **[PYCHARM CONFIGURATION GUIDE](docs/PYCHARM_CONFIGURATION.md)** for full setup instructions, including how to enable XPPython3 stubs, configure Sources Roots, and run sim‑less scripts from the project root.

See **[DEVELOPER NOTES](docs/DEVELOPER_NOTES.md)** for special considerations for running python in X-Plane.

See **[AI CODING GUIDE](docs/AI_CODING_GUIDE.md)** for generating AI code within this project structure.

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
    "PI_sshd_OAT",
    "PI_sshd_dev_oat_gui",
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
