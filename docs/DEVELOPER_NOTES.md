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
