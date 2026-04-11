"""
generate_fake_xp_interface.py
-----------------------------

Generate a complete `fake_xp.pyi` stub for simless execution.

This stub contains:
    • All constants from production XPPython3 xp.pyi
    • All public methods from simless FakeXP / plugin loader / runner
    • All imports collected from those modules (deduped, merged)
    • A single FakeXP class exposing the xp.* façade
    • A top-level `xp: FakeXP` declaration
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

XP_PYI = Path("../plugins/XPPython3/xp.pyi")
SIMLESS_DIR = Path("../simless/libs")

SIMLESS_SOURCES = {
    *SIMLESS_DIR.glob("fake_xp_*.py"),
    SIMLESS_DIR / "fake_xp.py",
}

SIMLESS_SOURCES = [
    p for p in SIMLESS_SOURCES
    if p.exists() and not p.name.endswith("_types.py")
]

OUT = SIMLESS_DIR / "fake_xp.pyi"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

CONST_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^=\n]+)$")

PROTOCOL_CLASS_RE = re.compile(
    r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\):"
)


# ---------------------------------------------------------------------------
# Extract constants from production xp.pyi
# ---------------------------------------------------------------------------

def extract_constants():
    text = XP_PYI.read_text(encoding="utf-8")
    constants = []
    imports = []

    for line in text.splitlines():
        if line.startswith("def "):
            break

        imports.append(line)

        m = CONST_RE.match(line.strip())
        if m:
            name, typ = m.groups()
            constants.append((name, typ.strip()))

    return imports, constants


# ---------------------------------------------------------------------------
# Extract imports from all simless sources
# Handles:
#   • import X
#   • import X as Y
#   • from X import A, B
#   • from X import (
#         A,
#         B,
#     )
# ---------------------------------------------------------------------------

def extract_all_imports():
    from_imports: dict[str, set[str]] = {}
    plain_imports: set[str] = set()

    for src in SIMLESS_SOURCES:
        lines = src.read_text(encoding="utf-8").splitlines()
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Multi-line from-import: from X import (
            if line.startswith("from ") and line.endswith("import ("):
                parts = line.split()
                mod = parts[1]
                names: list[str] = []

                i += 1
                while i < len(lines):
                    inner = lines[i].strip()
                    if inner == ")":
                        break
                    names.append(inner.rstrip(","))
                    i += 1

                from_imports.setdefault(mod, set()).update(names)
                i += 1
                continue

            # Single-line from-import
            m = re.match(r"from\s+([A-Za-z0-9_.]+)\s+import\s+(.+)", line)
            if m:
                mod, names = m.groups()
                parts = [n.strip() for n in names.split(",")]
                from_imports.setdefault(mod, set()).update(parts)
                i += 1
                continue

            # Plain import (with optional alias)
            m = re.match(r"import\s+([A-Za-z0-9_.]+(?:\s+as\s+[A-Za-z0-9_]+)?)", line)
            if m:
                plain_imports.add(m.group(1).strip())
                i += 1
                continue

            i += 1

    lines: list[str] = []

    for mod in sorted(plain_imports):
        lines.append(f"import {mod}")

    for mod in sorted(from_imports):
        names = sorted(from_imports[mod])
        lines.append(f"from {mod} import {', '.join(names)}")

    return lines


# ---------------------------------------------------------------------------
# Extract methods from simless sources
#  • multi-line signatures
#  • skip @property
#  • skip private methods
#  • skip Protocol classes entirely
# ---------------------------------------------------------------------------

def extract_methods():
    methods: list[tuple[str, str, str]] = []

    for src in SIMLESS_SOURCES:
        code = src.read_text(encoding="utf-8")
        lines = code.splitlines()

        # Find Protocol class blocks to skip
        protocol_blocks: list[tuple[int, int]] = []
        for match in PROTOCOL_CLASS_RE.finditer(code):
            cls_name, bases = match.groups()
            if "Protocol" not in bases and "typing.Protocol" not in bases:
                continue

            start = match.start()
            after = code[match.end():]
            offset = match.end()
            indent = None

            for ln in after.splitlines(True):
                if ln.strip() == "":
                    offset += len(ln)
                    continue

                leading = len(ln) - len(ln.lstrip())
                if indent is None:
                    indent = leading
                    offset += len(ln)
                    continue

                if leading < indent:
                    break

                offset += len(ln)

            protocol_blocks.append((start, offset))

        def in_protocol_block(pos: int) -> bool:
            return any(start <= pos < end for start, end in protocol_blocks)

        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.lstrip()

            # Skip if inside a Protocol block
            pos = code.find(raw_line)
            if in_protocol_block(pos):
                i += 1
                continue

            if line.startswith("def ") and "(" in line:
                sig_lines = [raw_line]

                while not sig_lines[-1].rstrip().endswith(":"):
                    i += 1
                    if i >= len(lines):
                        break
                    sig_lines.append(lines[i])

                signature = " ".join(l.strip() for l in sig_lines)

                m = re.match(
                    r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*(?:->\s*([^:]+))?:",
                    signature,
                )
                if m:
                    name, args, ret = m.groups()

                    if name.startswith("_"):
                        i += 1
                        continue

                    # Skip @property
                    start_idx = code.find(sig_lines[0])
                    before = code[:start_idx].rstrip().splitlines()
                    if before and before[-1].strip() == "@property":
                        i += 1
                        continue

                    args = args.strip()
                    if args.startswith("self,"):
                        args = args[len("self,"):].strip()
                    elif args == "self":
                        args = ""

                    ret = ret.strip() if ret else "None"
                    methods.append((name, args, ret))

            i += 1

    return methods


# ---------------------------------------------------------------------------
# Build fake_xp.pyi
# ---------------------------------------------------------------------------

def generate_fake_xp_pyi():
    prod_imports, constants = extract_constants()
    methods = extract_methods()
    simless_imports = extract_all_imports()

    out: list[str] = []
    out.append("# Auto-generated by generate_fake_xp_interface.py")
    out.append("from typing import Any, Callable, Dict, List, Optional, Tuple")
    out.append("")

    out.extend(prod_imports)
    out.append("")

    out.extend(simless_imports)
    out.append("from simless.libs.plugin_runner import SimlessRunner")
    out.append("")

    out.append("class FakeXP:")
    out.append('    """Simless xp.* façade (auto-generated)."""')
    out.append("")

    # FakeXP instance attributes
    out.append("    debug: bool")
    out.append("    enable_gui: bool")
    out.append("")
    out.append("    enable_dataref_bridge: bool")
    out.append("    bridge_host: str")
    out.append("    bridge_port: int")
    out.append("")
    out.append("    simless_runner: SimlessRunner")
    out.append("    window_manager: WindowManager")
    out.append("    graphics_manager: GraphicsManager")
    out.append("    input_manager: InputManager")
    out.append("    widget_manager: WidgetManager")
    out.append("    dataref_manager: DataRefManager")
    out.append("")
    out.append("    _debug: bool")
    out.append("    _sim_time: float")
    out.append("")

    # Explicit constructor so PyCharm knows FakeXP accepts these arguments
    out.append("    def __init__(")
    out.append("        self,")
    out.append("        debug: bool = False,")
    out.append("        enable_gui: bool = True,")
    out.append("        enable_dataref_bridge: bool = False,")
    out.append("        bridge_host: Optional[str] = None,")
    out.append("        bridge_port: Optional[int] = None,")
    out.append("    ) -> None: ...")
    out.append("")
    out.append("    def _init_flightloop(self) -> None: ...")
    out.append("    def _init_utilities(self) -> None: ...")
    out.append("    def _init_command(self) -> None: ...")
    out.append("")

    for name, typ in constants:
        out.append(f"    {name}: {typ}")

    out.append("")

    for name, args, ret in methods:
        if args:
            sig = f"self, {args}"
        else:
            sig = "self"
        out.append(f"    def {name}({sig}) -> {ret}: ...")

    out.append("")
    out.append("xp: FakeXP")
    out.append("")

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"Generated {OUT}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    generate_fake_xp_pyi()
