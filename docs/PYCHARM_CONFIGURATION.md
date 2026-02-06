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

## 2. Configure the `plugins/` directory
X‑Plane treats the plugin directory as the import root.  
PyCharm must mirror this behavior.

### 2.1 Mark `plugins/` as a Source
Right‑click: plugins/ → Mark Directory As → Sources Root

This enables absolute imports such as:
    import PI_sshd_OTA
    import sshd_extensions.datarefs
    import sshd_extlibs.ss_serial_device

### 2.2 Exclude plugin build artifacts (optional)
If you generate logs, cache files, or compiled artifacts under plugins/,
mark those subdirectories as Excluded.

---

## 3. Configure XPPython3 stubs for autocomplete and type checking
Place the official XPPython3 `.pyi` stubs and python code in:

    stubs/XPPython3/

PyCharm must treat this directory as a source root, but the parent `stubs/`
must be excluded to avoid indexing noise.

### 3.1 Exclude the `stubs/` directory
Right‑click stubs/ → Mark Directory As → Excluded

### 3.2 Add `stubs/` as a Content Root
Settings → Project Structure → Add Content Root → stubs/

### 3.3 Mark `stubs/XPPython3` as a Source
Right‑click stubs/XPPython3 → Mark Directory As → Sources Root

![Structure](docs/structure.png)

This enables:
• xp.* autocomplete  
• mypy‑safe type checking  
• fast indexing without PyCharm freezes  

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

| Environment         | Import Root                         |
|---------------------|-------------------------------------|
| X‑Plane (XPPython3) | plugins/                            |
| PyCharm             | plugins/                            |
| FakeXP headless     | plugins/ (via sys.path)             |
| Working directory   | project root (`xplane-python-dev/`) |

This guarantees:
• deterministic imports  
• correct type checking  
• correct stub resolution  
• identical behavior in sim‑less and production  
