# 📘 xppython3-headless-dev
### IDE and AI friendly workflow • Sim‑less execution and debugging • Live X‑Plane DataRef injection

A structured development environment for building and debugging XPPython3 plugins natively in
an IDE (PyCharm) through runtime emulation of the XPPython3 API.

XPPython3 is ideal for AI assisted coding of X-plane plugins.  The python syntax is highly compatible with LLM models
as well as having a large validated public code base for training.

This project provides:

• A X‑Plane‑compatible plugin folder structure  
• Sim‑less execution and debugging of plugins with a runner that simulates the full plugin lifecycle  
• Live X‑Plane DataRef streaming through a bridge plugin  
• A complete XPWidget + XPLMGraphics emulation layer (DearPyGui‑backed)  
• Auto‑created, managed, and bridged DataRefs  
• stubs and .pyi files for strong datatyping and code introspection  
• A simless multi‑plugin environment for integration testing  

The goal is fast, maintainable plugin development with behavior identical inside and outside X‑Plane.

---

## 📁 Directory Structure
```
xppython3-headless-dev/
│
├── plugins/                                # All XPPython3 plugins (production-style)
│   ├── PI_sshd_ota.py                      # Example plugin with managed DataRefs
│   ├── PI_sshd_dev_ota_gui                 # Example XPWidget GUI plugin
│   │
│   ├── sshd_extlibs/                       # Shared modules
│   │   ├── ss_serial_device.py
│   │   └── ...
│   │
│   └── sshd_extensions/                    # Shared plugin architecture (namespaced)
│       ├── datarefs.py                     # Managed DataRefs
│       ├── xp_interface.py                 # Runtime placeholder for XPInterface (prod-safe)
│       └── ...
│
├── simless/                                # Sim‑less execution harnesses
│   ├── __init__.pyi                        # Declares xp: FakeXPInterface for IDE/mypy visibility
│   │
│   ├── run_standalone_oat.py               # FakeXP only (no bridge)
│   ├── run_bridged_oat.py                  # FakeXP + live DataRef bridge
│   │
│   └── libs/                               # Simless-only runtime + typing contracts
│       ├── fake_xp.py                      # FakeXP: public xp.* API façade
│       ├── fake_xp_runner.py               # Lifecycle, plugin loading, timing
│       ├── fake_xp_widget.py               # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py             # XPLMDisplay/XPLMGraphics simulation
│       ├── fake_xp_dataref.py              # DataRef engine (managed + inferred + bridged)
│       ├── fake_xp_utilities.py            # Commands, menus, misc XPLM shims
│       ├── fake_xp_interface.py            # Runtime shim (TYPE_CHECKING guard)
│       ├── simless_xp_interface.pyi        # Subset of xp API implemented for simless
│       └── fake_xp_interface.pyi           # FakeXPInterface + FakeRefInfo typing
│
├── stubs/                                  # IDE-visible stubs for real XPPython3 + simless Protocols
│   ├── sshd_extensions/
│   │   └── xp_interface.pyi                # Generated Protocol: full xp.* API surface
│   │
│   └── XPPython3/
│       ├── xp.pyi                          # Full XPPython3 API surface
│       ├── xp_types.pyi                    # XPLM typedefs, enums, structs
│       └── ...
│
├── tests/                                  # Unit tests for FakeXP + plugin lifecycle
│
└── pyproject.toml                          # Poetry package management
```

---

## 🧩 IDE (PyCharm) Development Workflow

Development workflow features:

• **Strong datatyping and code inspection with xp.pyi and xp_typing.pyi, xp_interface.pyi**  
• **Structured to generate and validate AI generated code**  
• **Debug plugins in the IDE debugger using a simless runner**  
• **Run with live X-plane datarefs through a dataref bridge**

See **[PYCHARM CONFIGURATION GUIDE](docs/PYCHARM_CONFIGURATION.md)** for full setup instructions, including how to enable XPPython3 stubs, configure Sources Roots, and run sim‑less scripts from the project root.

See **[DEVELOPER NOTES](docs/DEVELOPER_NOTES.md)** for special considerations for running python in X-Plane.

See **[AI CODING GUIDE](docs/AI_CODING_GUIDE.md)** for generating AI code within this project structure.

See **[GUI EMULATION NOTES](docs/GUI_EMULATION.md)** for special considerations for GUI usage.

---

## 🧩 Managed DataRefs (XPPython3 extension)

Managed DataRefs provide:

• Automatic waiting for required DataRefs during startup  
• Defaults used until X‑Plane provides real values  
• Automatic handle and metadata retrieval  
• Unified, type‑safe get/set access  

Managed DataRefs define the plugin’s contract with X‑Plane and are production‑safe.

See **[MANAGED DATAREFS](docs/DATAREF_MODEL.md#managed-datarefs)** for full details.

---

## 🔌 Bridged DataRefs (Live X‑Plane integration)

Bridged DataRefs allow a sim‑less FakeXP environment to mirror live X‑Plane DataRefs in real time.

This enables:

• Running plugins in an IDE while X‑Plane is running  
• Injecting real simulator values into FakeXP  
• Debugging plugin logic against live aircraft state  
• Seamless transition between sim‑less and in‑sim execution  

See **[BRIDGED DATAREFS](docs/DATAREF_MODEL.md#bridge-enabled-datarefs)** for full details.

### Key properties

• Bridged DataRefs are non‑blocking  
• Fake values are always available  
• Authority is established explicitly by X‑Plane  
• Type and value become authoritative together  
• Disconnects safely revert DataRefs to dummy state  

Bridged DataRefs integrate transparently with:

• Managed DataRefs  
• Auto‑created DataRefs  
• The standard xp.* API  

No plugin code changes are required.

---

## ▶️ Minimal Sim‑less Runner

A simple runner script is all that’s needed to execute plugins outside X‑Plane.
```python
import sys
import XPPython3
from simless.libs.fake_xp import FakeXP
from pathlib import Path

# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))

def run_simless_oat_gui() -> None:
    xp = FakeXP(debug=True, enable_gui=True)
    XPPython3.xp = xp

    plugins = [
        "PI_sshd_OAT",
        "PI_sshd_dev_oat_gui",
    ]
    xp.simless_runner.run_plugin_lifecycle(plugins)

if __name__ == "__main__":
    run_simless_oat_gui()
```

This runner:

• Boots FakeXP which emulates the X‑Plane xp module  
• Loads any number of plugins that will share the same dataref namespace
• Executes the full lifecycle (start/enable/flight_loop/disable/stop)   
• Runs in GUI or headless mode  

---

## 🚀 Deployment to X‑Plane

Copy plugin contents into:

X‑Plane 12/Resources/plugins/PythonPlugins/

Example:

PI_sshd_ota.py  
extensions/  
extlibs/
