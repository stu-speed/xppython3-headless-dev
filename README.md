# 📘 xppython3-headless-dev
### IDE and AI friendly workflow • Sim‑less execution and debugging • Live X‑Plane DataRef injection

A structured development environment for building and debugging XPPython3 plugins natively in
an IDE (PyCharm) through runtime emulation of the XPPython3 API.

XPPython3 is ideal for AI assisted coding of X‑Plane plugins. The Python syntax is highly compatible with LLM models
as well as having a large validated public code base for training.

This project provides:

• A X‑Plane‑compatible plugin folder structure  
• Sim‑less execution and debugging of plugins with a runner that simulates the full plugin lifecycle  
• Live X‑Plane DataRef streaming through a bridge plugin  
• A complete XPWidget + XPLMGraphics emulation layer (DearPyGui‑backed)  
• Auto‑created, managed, and bridged DataRefs  
• Stubs and .pyi files for strong datatyping and code introspection  
• A simless multi‑plugin environment for integration testing  

The goal is fast, maintainable plugin development with behavior identical inside and outside X‑Plane.

---------------------------------------------------------------------

# 🚀 Installation

Follow these steps to set up a fully functional sim‑less XPPython3 development environment.

1. Copy this package into your IDE project directory  
   Place the entire xppython3-headless-dev folder inside your IDE project root.

   Example:
   my-project/
       xppython3-headless-dev/
       your-other-code/

2. Copy the real XPPython3 package into stubs  
   Download or extract the official XPPython3 distribution and place the entire XPPython3 folder into:
   xppython3-headless-dev/stubs/XPPython3/

   This provides xp.pyi, xp_types.pyi, and all official API signatures for IDE autocompletion.

3. Develop plugins inside the headless-dev plugins directory  
   All plugin modules must be placed in:
   xppython3-headless-dev/plugins/

   The simless runner loads plugins directly from this directory and executes their full lifecycle.

4. (Optional) Install Poetry for dependency management  
   If you want a reproducible environment:
   pip install --user poetry
   poetry install
   poetry shell

5. Run a sim‑less runner  
   Example:
   python simless/run_standalone_oat.py
   or
   python simless/run_bridged_oat.py

---------------------------------------------------------------------

# 📁 Directory Structure
```
xppython3-headless-dev/
│
├── plugins/                                # All XPPython3 plugins go here
│   ├── PI_sshd_ota.py                      # Example plugin with managed DataRefs
│   ├── PI_sshd_dev_ota_gui                 # Example XPWidget GUI plugin
│   │
│   ├── sshd_extlibs/                       # Shared modules
│   │   ├── ss_serial_device.py
│   │   └── ...
│   │
│   └── sshd_extensions/                    # Shared plugin architecture
│       ├── datarefs.py                     # Managed DataRefs
│       ├── xp_interface.py                 # Runtime placeholder for XPInterface
│       └── ...
│
├── simless/                                # Sim‑less execution harnesses
│   ├── __init__.pyi                        # Declares xp: FakeXPInterface for IDE/mypy visibility
│   │
│   ├── run_standalone_oat.py               # FakeXP only + GUI dataref updates
│   ├── run_bridged_oat.py                  # FakeXP + live DataRef bridge
│   │
│   └── libs/                               # Simless-only runtime + typing contracts
│       ├── fake_xp.py                      # FakeXP: public xp.* API façade
│       ├── plugin_runner.py                # Lifecycle, plugin loading, timing
│       ├── plugin_loader.py                # Load plugin compatible environment
│       ├── fake_xp_widget.py               # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py             # XPLMDisplay/XPLMGraphics simulation
│       ├── fake_xp_dataref.py              # DataRef engine (managed + inferred + bridged)
│       ├── fake_xp_utilities.py            # Commands, menus, misc XPLM shims
│       └── fake_xp_interface.pyi           # FakeXPInterface + FakeRefInfo typing
│
├── stubs/                                  # IDE-visible stubs for real XPPython3 + simless Protocols
│   ├── sshd_extensions/
│   │   └── xp_interface.pyi                # Generated Protocol: full xp.* API surface
│   │
│   └── XPPython3/                          # Install the complete package here
│       ├── xp.pyi                          # Full XPPython3 API surface
│       ├── xp_types.pyi                    # XPLM typedefs, enums, structs
│       └── ...
│
├── tests/                                  # Unit tests for FakeXP + plugin lifecycle
│
└── pyproject.toml                          # Poetry package management
```
---------------------------------------------------------------------

# 🧩 IDE (PyCharm) Development Workflow

Development workflow features:

• Strong datatyping and code inspection with xp.pyi and xp_interface.pyi  
• Structured to generate and validate AI‑generated code  
• Debug plugins in the IDE debugger using a simless runner  
• Run with live X‑Plane DataRefs through a dataref bridge  

See PYCHARM_CONFIGURATION.md for full setup instructions.

See DEVELOPER_NOTES.md for special considerations for running Python in X‑Plane.

See AI_CODING_GUIDE.md for generating AI code within this project structure.

See GUI_EMULATION.md for special considerations for GUI usage.

---------------------------------------------------------------------

# 🧩 Managed DataRefs (XPPython3 extension)

Managed DataRefs provide:

• Automatic waiting for required DataRefs during startup  
• Defaults used until X‑Plane provides real values  
• Automatic handle and metadata retrieval  
• Unified, type‑safe get/set access  

Managed DataRefs define the plugin’s contract with X‑Plane and are production‑safe.

See DATAREF_MODEL.md#managed-datarefs for full details.

---------------------------------------------------------------------

# 🔌 Bridged DataRefs (Live X‑Plane integration)

Bridged DataRefs allow a sim‑less FakeXP environment to mirror live X‑Plane DataRefs in real time.

This enables:

• Running plugins in an IDE while X‑Plane is running  
• Injecting real simulator values into FakeXP  
• Debugging plugin logic against live aircraft state  
• Seamless transition between sim‑less and in‑sim execution  

See DATAREF_MODEL.md#bridge-enabled-datarefs for full details.

Key properties:

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

---------------------------------------------------------------------

# ▶️ Minimal Sim‑less Runner

A simple runner script is all that’s needed to execute plugins outside X‑Plane.

import XPPython3
from simless.libs.fake_xp import FakeXP

def run_gui_sample() -> None:
    xp = FakeXP(enable_gui=True)
    XPPython3.xp = xp

    plugins = [
        "PI_sshd_gui_sample",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)

if __name__ == "__main__":
    run_gui_sample()

This runner:

• Boots FakeXP which emulates the X‑Plane xp module  
• Loads any number of plugins that will share the same DataRef namespace  
• Executes the full lifecycle (start/enable/flight_loop/disable/stop)  
• Runs in GUI or headless mode  

---------------------------------------------------------------------

# 🚀 Deployment to X‑Plane

Copy plugin contents into:

X‑Plane 12/Resources/plugins/PythonPlugins/

Example:

PI_sshd_ota.py  
extensions/  
extlibs/
