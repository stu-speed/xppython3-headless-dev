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
All sim‑less scripts should run with the project root as the working directory.

Run → Edit Configurations → Working Directory = xplane-python-dev/

This ensures headless scripts resolve paths consistently and can locate the `plugins/` directory.

---

## 2. Mark `plugins/` as a Sources Root
X‑Plane treats the plugin directory as the import root.  
PyCharm must do the same.

Right‑click: plugins/ → Mark Directory As → Sources Root

This enables absolute imports such as:
    import PI_sshd_OTA
    import sshd_extensions.datarefs
    import sshd_extlibs.ss_serial_device

---

## 3. Sim‑less imports do NOT require marking `simless/libs` as a source root
All sim‑less scripts import FakeXP using:

    from simless.libs.fake_xp import FakeXP

Because `simless/` is inside the project root, PyCharm resolves this automatically.  
No additional configuration is required.

---

## 4. Configure XPPython3 stubs for autocomplete and type checking
Place the official XPPython3 `.pyi` stubs in:

    stubs/XPPython3/

Then configure PyCharm:

### 4.1 Exclude the `stubs/` directory
Right‑click stubs/ → Mark Directory As → Excluded

### 4.2 Add `stubs/` as a Content Root
Settings → Project Structure → Add Content Root → stubs/

### 4.3 Mark `stubs/XPPython3` as a Sources Root
Right‑click stubs/XPPython3 → Mark Directory As → Sources Root

This enables:
• xp.* autocomplete  
• mypy‑safe type checking  
• fast indexing without PyCharm freezes  

---

## 5. Headless execution: add `plugins/` to sys.path
Sim‑less runners live under `simless/`, so Python’s working directory is not the plugin root.  
To mirror X‑Plane’s import model, each headless runner must add the plugin root:

    from pathlib import Path
    import sys

    ROOT = Path(__file__).resolve().parent.parent
    PLUGIN_ROOT = ROOT / "plugins"
    sys.path.insert(0, str(PLUGIN_ROOT))

This makes headless execution behave exactly like X‑Plane:
• plugins load by name (`PI_sshd_OTA`, etc.)  
• `sshd_extensions` and `sshd_extlibs` resolve correctly  
• FakeXP can run multi‑plugin lifecycles without import errors  

---

## 6. Recommended PyCharm Run Configuration
For any sim‑less script (e.g., `simless/run_ota_gui.py`):

• Script path: simless/run_ota_gui.py  
• Working directory: xplane-python-dev/  
• Add content roots to PYTHONPATH: enabled  
• Add source roots to PYTHONPATH: enabled  

This ensures the same import behavior across:
• PyCharm  
• FakeXP  
• XPPython3 inside X‑Plane  

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
