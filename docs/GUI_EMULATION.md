# 🖥️ GUI Emulation in FakeXP  
How FakeXP simulates X‑Plane’s widget + graphics stack using DearPyGui

FakeXP provides a complete GUI emulation layer that mirrors X‑Plane’s
XPWidgets and XPLMGraphics systems. This enables plugin authors to build and
debug GUI‑heavy plugins without launching X‑Plane.

This document explains:

- how GUI emulation works  
- how FakeXP integrates DearPyGui  
- how the FakeXPRunner owns the GUI lifecycle  
- how the unified 60 Hz loop drives rendering  
- how headless mode avoids GUI entirely  

---

# ⚠️ Critical Warning: FakeXPRunner Must Own DearPyGui

Plugins and scripts must never call DearPyGui APIs directly.  
Only FakeXPRunner manages the DPG context, viewport, and render loop.

If a plugin or script attempts to:

- create or destroy a DPG context  
- create or close a viewport  
- call render_dearpygui_frame  
- create or delete DPG items  
- modify the DPG event loop  

…it can corrupt the GUI state, freeze the simless runner, or crash Python.

DPG is not designed for multi‑owner control.  
FakeXPRunner must manage all DPG operations to ensure stability and determinism.

---

# 🧩 Architecture Overview

```
Plugins (PythonInterface)  
        │  
        ▼  
FakeXP (Public API Surface)  
  - Datarefs  
  - Widgets  
  - Graphics  
  - Flightloops  
        │  
        ▼  
FakeXPRunner (Simulation Engine)  
  - Plugin Loader  
  - DataRef Registration  
  - Dummy Promotion  
  - DataRefManager Binding  
  - 60 Hz Main Loop  
  - DearPyGui Lifecycle (sole owner)  
        │  
        ▼  
DearPyGui Backend
  - Viewport  
  - Rendering  
  - Input Events  
```

This separation ensures:

- FakeXP stays a clean, X‑Plane‑accurate API surface  
- FakeXPRunner handles orchestration, lifecycle, and GUI ownership  
- Plugins never interact with DearPyGui directly  

---

# 🪟 DearPyGui Lifecycle (Owned Exclusively by FakeXPRunner)

When GUI mode is enabled (enable_gui=True), FakeXPRunner performs:

1. create_context  
2. create_viewport  
3. setup_dearpygui  
4. per‑frame rendering  
5. destroy_context  

FakeXP does not call any of these functions.

FakeXPRunner guarantees:

- context created exactly once  
- viewport created exactly once  
- render loop executed exactly once per frame  
- context destroyed exactly once at shutdown  

This mirrors X‑Plane’s rule:  
plugins never interact with the graphics backend directly.

---

# 🧱 XPWidget Emulation Layer

FakeXP implements a full XPWidget simulation:

- widget creation  
- parent/child hierarchy  
- geometry and visibility  
- message dispatch  
- hit‑testing and focus  
- callback routing  
- DPG item creation for rendering  

Widgets are rendered passively each frame by DPG, but all logic remains under
FakeXP’s control.  
FakeXPRunner simply triggers the draw pass each frame.

---

# 🎨 Graphics Overlay (XPLMDisplay Simulation)

FakeXP simulates:

- XPLMDisplay  
- XPLMGraphics  
- draw callbacks  
- overlay windows  
- plugin‑drawn HUDs and debug elements  

Plugins register draw callbacks exactly as they would in X‑Plane.  
FakeXPRunner invokes these callbacks during each frame.

---

# 🔄 Unified 60 Hz Simulation Loop (Owned by FakeXPRunner)

FakeXPRunner runs a deterministic loop shared by GUI and headless modes:

run_frame()                     # flightloops, widgets, graphics  
if GUI enabled:  
    render_dearpygui_frame()  
sleep_to_maintain_60Hz()  

The loop ends when:

- the plugin calls xp.end_run_loop(), or  
- the user closes the viewport (GUI mode only)  

This matches real X‑Plane environment.

---

# 🧪 Headless Mode (No GUI)

When enable_gui=False:

- no DPG context is created  
- no viewport exists  
- no widget or graphics code runs  
- the system remains deterministic and CI‑friendly  

Headless mode is ideal for:

- automated tests  
- hardware integration  
- non‑GUI plugins  
- CI environments without GPU access  

---

# 🧭 Summary

FakeXP’s GUI emulation system provides:

- a realistic XPWidget environment  
- a functional graphics overlay  
- deterministic 60 Hz rendering  
- strict DearPyGui lifecycle ownership via FakeXPRunner  
- safe GUI mode  
- fully deterministic headless mode  

By centralizing all DPG operations inside FakeXPRunner, the system remains:

- stable  
- deterministic  
- plugin‑safe  
- CI‑friendly  
- X‑Plane‑accurate  

This architecture ensures plugin authors can develop and debug GUI‑heavy
plugins without launching X‑Plane, while maintaining compatibility with the
real simulator.
