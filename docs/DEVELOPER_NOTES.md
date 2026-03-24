# 🛠️ Developer Notes

These notes define the architectural rules for writing XPPython3 plugins that behave
identically in real‑sim and simless environments.

---------------------------------------------------------------------

## 📦 Directory Structure & Namespacing

This project uses uniquely prefixed directories:

- sshd_extensions/ — shared plugin architecture (DataRefs, xp interface, helpers)
- sshd_extlibs/ — vendor libraries, hardware drivers, FakeXP support code

These names avoid collisions with other plugins and ensure deterministic imports.

---------------------------------------------------------------------

## ⚠️ Import Safety

XPPython3 loads each plugin **once**, by filename, under `PythonPlugins.*`.

Duplicate plugin instances only occur when Python loads the plugin a *second time*
under a different name. This happens if your extension modules are imported
**from outside your plugin**.

Example of unsafe usage (from another plugin or external code):

    import sshd_extensions.datarefs
    from sshd_extensions import xp_interface

This triggers Python’s package loader and creates a second copy of your plugin:

    PythonPlugins.PI_yourPlugin
    sshd_extensions.PI_yourPlugin

Result:

- two plugin instances  
- two xp objects  
- two DataRefManagers  
- callbacks firing on the wrong instance  

### ✔ Safe

- `__init__.py` in your plugin directories  
- Absolute imports *within your own plugin*  
- Re‑importing XPPython3 (`import XPPython3`)  
- Using your extensions only from your plugin  

### ❌ Unsafe

- Importing your plugin’s extensions from another plugin  
- Importing your plugin directory as a package  
- Relative imports (`from .datarefs import X`)  

**Rule:** Your plugin’s extensions must only be imported by your plugin.

---------------------------------------------------------------------

## 📚 Import Rules (Inside Your Plugin)

Use absolute imports:

    from sshd_extensions.datarefs import DataRefManager
    from sshd_extlibs.fake_xp import FakeXP

Avoid relative imports:

    from .datarefs import DataRefManager

Relative imports reintroduce package semantics and can cause duplicate loads.

---------------------------------------------------------------------

## 🔌 Passing `xp` Explicitly

All subsystems receive the xp object explicitly:

    registry = DataRefRegistry(xp, DATAREFS)
    manager = DataRefManager(registry, xp)

This prevents:

- mismatched xp objects  
- FakeXP/real‑XP divergence  
- global‑state bugs  
- double‑import masking  

---------------------------------------------------------------------

## 🧪 Simless / FakeXP Parity

The simless environment provides:

- FakeXP API surface  
- FakeXPRunner lifecycle  
- XPWidget emulation  
- DataRef registration and timing  
- Graphics and utility shims  

Plugin code must behave identically in:

- real X‑Plane  
- FakeXP  
- unit tests  
- CI  

---------------------------------------------------------------------

## 🧩 Plugin Lifecycle Expectations

Plugins should:

- declare DataRefs up front  
- use DataRefManager.ready() for incremental binding  
- avoid reading/writing DataRefs before ready  
- schedule flight loops in XPluginEnable  
- disable themselves on hard failures  

### `ready()` runs inside the flight loop

`ready()` must not run inside XPluginEnable.  
It is invoked from the flight loop so that:

- DataRefs can appear incrementally  
- binding can retry safely  
- timeouts can be enforced  
- the plugin can disable itself deterministically
