# 🛠️ Developer Notes

These notes document the architectural rules and expectations for contributors.  
They ensure deterministic behavior under XPPython3, prevent double‑import issues,  
and maintain parity between real‑sim and simless environments.

---

## 📦 Directory Structure & Namespacing

This project uses uniquely prefixed directories:

- `sshd_extensions/` — shared plugin architecture (DataRefs, xp interface, helpers)
- `sshd_extlibs/` — vendor libraries, hardware drivers, FakeXP support code

These names avoid namespace collisions with other XPPython3 plugins and ensure  
deterministic imports across all deployments.

---

## 🚫 No `__init__.py` Anywhere

XPPython3 loads Python plugins **by filename**, not as packages.  
It does *not* use Python’s package loader and does *not* treat plugin directories  
as importable packages.

Python only activates package semantics when:

- a directory contains `__init__.py`, or  
- a module uses a relative import (`from .module import X`)

Either of these signals to Python that the directory is a package.  
Once that happens, Python may import plugin modules **under multiple names**, e.g.:

- `PythonPlugins.PI_ss_ota` (loaded by XPPython3’s filename loader)
- `PythonPlugins.sshd_extensions.PI_ss_ota` (loaded by Python’s package resolver)

This results in:

- two plugin instances  
- two `xp` objects  
- two DataRefManagers  
- logs disappearing  
- callbacks firing on the wrong instance  

To avoid this, **no python code directory in the plugin tree may contain `__init__.py`**, and  
**no relative imports may be used**. This keeps the plugin tree non‑package and  
ensures XPPython3’s filename‑based import is the *only* import path.

This differs from C++ modules, where packages are expected.  

---

## 📚 Import Rules

Because the plugin tree is intentionally *not* a package, all imports must be  
**absolute**, not relative.

Correct:

    from sshd_extensions.datarefs import DataRefManager
    from sshd_extlibs.fake_xp import FakeXP

Incorrect:

    from .datarefs import DataRefManager
    from .extensions.datarefs import DataRefManager

Relative imports are forbidden because they reintroduce package semantics and  
can cause duplicate module loads.

---

## 🔌 Passing `xp` Explicitly

All subsystems receive the XPPython3 API object explicitly:

    registry = DataRefRegistry(xp, DATAREFS)
    manager = DataRefManager(registry, xp)

This avoids:

- global state  
- mismatched xp objects  
- FakeXP/real‑XP divergence  
- double‑import masking  

Every subsystem uses the exact same xp object the plugin instance received.

---

## 🧪 Simless / FakeXP Parity

The simless environment (`simless/libs/`) provides:

- FakeXP API surface  
- FakeXPRunner lifecycle  
- XPWidget emulation  
- DataRef registration and timing  
- Graphics and utility shims  

All plugin code must behave identically in:

- real X‑Plane  
- FakeXP  
- unit tests  
- CI  

This is why the DataRef layer, xp interface, and plugin lifecycle are explicit  
and deterministic.

---

## 🧩 Plugin Lifecycle Expectations

Plugins should:

- declare DataRefs up front  
- use `DataRefManager.ready()` for incremental binding  
- avoid reading/writing DataRefs before ready  
- schedule flight loops in `XPluginEnable`  
- disable themselves on hard failures (timeouts, missing hardware, etc.)

### Important: `ready()` runs inside the flight loop  
`ready()` **must not** run inside `XPluginEnable`.  
It is invoked from the plugin’s flight loop callback so that:

- DataRefs can appear incrementally  
- binding can retry safely  
- timeouts can be enforced  
- the plugin can disable itself deterministically  
