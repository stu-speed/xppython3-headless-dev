# PyCharm Configuration Guide
This project mirrors X‑Plane’s plugin environment while supporting full sim‑less execution.  
PyCharm must treat the **project root (`xplane-python-dev/`)** as the execution root for all headless scripts.

The following configuration ensures:
• correct imports for plugins and shared architecture  
• correct resolution of XPPython3 stubs  
• correct FakeXP behavior  
• identical import semantics in PyCharm, FakeXP, and X‑Plane  

---

## 1. Use the project root as the Working Directory
All sim‑less runners and plugin imports assume the project root is the working directory.
Do not open PyCharm inside `plugins/` or `simless/`.

---

## 2. Configure plugins to run as under PythonPlugins
XPPython treats the plugin directory as the import root.  
PyCharm must mirror this behavior.

Right‑click: plugins/ → Mark Directory As → Sources Root

This enables headless absolute imports in plugins such as:
    import sshd_extensions.datarefs
    import sshd_extlibs.ss_serial_device

---

## 3. Configure XPPython3 stubs for autocomplete and type checking
Place the official XPPython3 `.pyi` stubs and python code in:

    stubs/XPPython3/
    stubs/sshd_extensions

Right‑click stubs → Mark Directory As → Sources Root

This enables:
• xp.* autocomplete  
• mypy‑safe type checking  

---

## 4. Headless execution: add `plugins/` to sys.path
Sim‑less runners execute from inside `simless/`, not the plugin root.  
To mirror X‑Plane’s import model, each runner must prepend the plugin root:

    from pathlib import Path
    import sys

    ROOT = Path(__file__).resolve().parent.parent
    PLUGIN_ROOT = ROOT / "plugins"
    sys.path.insert(0, str(PLUGIN_ROOT))

This ensures:
• plugins import by name (`PI_sshd_OTA`, etc.)  
• `sshd_extensions` and `sshd_extlibs` resolve correctly  
• FakeXP can run multi‑plugin lifecycles without import errors

---

## Summary
Your project now has a unified import model:

![Structure](structure.png)

| Environment         | Import Root                         |
|---------------------|-------------------------------------|
| X‑Plane (XPPython3) | plugins/                            |
| PyCharm             | project, plugins/, stubs/           |
| FakeXP headless     | plugins/ (via sys.path)             |
| Working directory   | project root (`xplane-python-dev/`) |

This guarantees:
• deterministic imports  
• correct type checking  
• correct stub resolution  
• identical behavior in sim‑less and production  
