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

2. Copy the real XPPython3 package into the project
   Download or extract the official XPPython3 distribution and place the entire XPPython3 folder into:
   xppython3-headless-dev/Resources/plugins/PythonPlugins/XPPython3/

   This provides xp.pyi, xp_types.pyi, and all official API signatures for IDE autocompletion.
   
   This provides plugins access to package modules (utils)

4. Develop plugins inside the headless-dev plugins directory  
   All plugin modules must be placed in:
   xppython3-headless-dev/Resources/plugins/PythonPlugins

   The simless runner loads plugins directly from this directory and executes their full lifecycle.

5. (Optional) Install Poetry for dependency management  
   If you want a reproducible environment:
   pip install --user poetry
   poetry install
   poetry shell

---------------------------------------------------------------------

# 📁 Directory Structure
```
xppython3-headless-dev/                      # Runner treats as X=plane root dir
│
├── Resources/                               # Mirrors X-plane dir
│   └── plugins/                             # X‑Plane plugins dir
│       ├── XPPython3/                       # *** Copy complete package ***                      
│       │   └── ...
│       │
│       └── PythonPlugins/                   # ALL XPPython3 plugins live here
│           ├── PI_sshd_ota.py               # Example plugin with managed DataRefs
│           ├── PI_sshd_dev_ota_gui.py       # Example XPWidget GUI plugin
│           │
│           ├── sshd_extlibs/                # Shared modules
│           │   ├── ss_serial_device.py
│           │   └── ...
│           │
│           └── sshd_extensions/             # Shared plugin architecture (production)
│               ├── datarefs.py              # Managed DataRefs (maybe should use EasyDataRefs)
│               ├── bridge_protocol.py       # Bridge datarefs to X-Plane
│               └── ...
│
├── Output/                                  # Mirrors X‑Plane dir
│   └── real weather/                        # NOAA expects this directory to exist
│
├── simless/                                 # Sim‑less execution harness (development‑only)
│   │
│   ├── __init__.py                          # Bootstraps paths expected by plugins
│   ├── run_oat_control.py                   # example run script for plugins
│   ├── DataRefCache.txt                     # Cached DataRefs from bridge to work offline
│   │
│   └── libs/
│       ├── fake_xp.py                       # FakeXP: public xp.* API façade
│       ├── fake_xp.pyi                      # Typing surface for FakeXP API
│       ├── plugin_runner.py                 # Runs full lifecycles for plugins
│       ├── plugin_loader.py                 # Load plugin compatible environment
│       ├── xppython3_runtime.py             # Monkey-patch xp.* API methods with fake emulators
│       ├── fake_xp_widget.py                # XPWidget emulation (DearPyGui-backed)
│       ├── fake_xp_graphics.py              # XPLMDisplay/XPLMGraphics simulation
│       ├── fake_xp_dataref.py               # DataRef engine (managed + inferred + bridged)
│       ├── fake_xp_utilities.py             # Commands, menus, misc XPLM shims
│       └── fake_xp_input.py                 # mouse / keyboard
│
├── tests/                                   # Unit tests for FakeXP + plugin lifecycle
│
└── pyproject.toml                           # Poetry package management
```
---------------------------------------------------------------------

# 🧩 IDE (PyCharm) Development Workflow

Development workflow features:

• Strong datatyping and code inspection with xp.pyi and xp_interface.pyi  
• Structured to generate and validate AI‑generated code  
• Debug plugins in the IDE debugger using a simless runner  
• Run with live X‑Plane DataRefs through a dataref bridge  

See [PYCHARM_CONFIGURATION.md](docs/PYCHARM_CONFIGURATION.md) for full setup instructions.

See [DEVELOPER_NOTES.md](docs/DEVELOPER_NOTES.md) for special considerations for running Python in X‑Plane.

See [AI_CODING_GUIDE.md](docs/AI_CODING_GUIDE.md) for generating AI code within this project structure.

See [GUI_EMULATION.md](docs/GUI_EMULATION.md) for special considerations for GUI usage.

---------------------------------------------------------------------

# ▶️ Minimal Sim‑less Runner

A simple runner script is all that’s needed to execute plugins outside X‑Plane.

```python
from simless.libs.fake_xp import FakeXP

def run_gui_sample() -> None:
    # log to terminal instead of log files for IDE debugging
    xp = FakeXP(terminal_logging=True)

    plugins = [
        "PI_sshd_gui_sample",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)

if __name__ == "__main__":
    run_gui_sample()
```

This runner:

• Boots FakeXP which emulates the X‑Plane xp module  
• Loads any number of plugins that will share the same DataRef namespace  
• Executes the full lifecycle (start/enable/flight_loop/disable/stop)  
• Runs in GUI or headless mode

---------------------------------------------------------------------

# 🔌 Bridged DataRefs (Live X‑Plane integration)

Bridged DataRefs allow a sim‑less FakeXP environment to mirror live X‑Plane DataRefs in real time.
The live DataRefs can be cached to a file to allow for subsequent offline debugging sessions
with properly shaped data.

This enables:

• Running plugins in an IDE while X‑Plane is running  
• Injecting real simulator values into FakeXP  
• Debugging plugin logic against live aircraft state  
• Debugging plugin logic against cached plausible data
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

# 🔍 DataRef Viewer (Plugin Menu Tool)

A lightweight in‑sim DataRef Viewer is included for debugging.  
It appears under:

Plugins → FakeXP → Dataref Viewer

The viewer automatically catalogs **all DataRefs used by the plugin**, including:

Features:

• Search and filter  
• Real‑time updates when bridged to X‑Plane  
• Safe fallback to cached values when offline  

---------------------------------------------------------------------

# 🧩 Managed DataRefs (extension)

Managed DataRefs provide:

• Automatic waiting for required DataRefs during startup  
• Defaults used until X‑Plane provides real values  
• Automatic handle and metadata retrieval  
• Unified, type‑safe get/set access

Managed DataRefs define the plugin’s contract with X‑Plane and are production‑safe.

See DATAREF_MODEL.md#managed-datarefs for full details.

---------------------------------------------------------------------

# 🚀 Deployment to X‑Plane

Copy plugin contents into:

X‑Plane 12/Resources/plugins/PythonPlugins/

Example:

PI_sshd_ota.py  
extensions/  
extlibs/
