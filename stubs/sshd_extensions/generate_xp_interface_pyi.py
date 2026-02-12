"""
generate_xp_interface.py
------------------------

This script generates a complete `xp_interface.pyi` file from the official
`XPPython3/xp.pyi` stub. The output file defines a single Protocol class
(`XPInterface`) containing one-line method signatures for every function
exposed by the XPPython3 `xp` module.

Purpose:
    • Provide strong typing and full IDE support for production plugin code.
    • Allow annotations such as `xp: XPInterface` to validate cleanly.
    • Ensure the interface stays synchronized with the upstream XPPython3 API.
    • Avoid shipping the full stub in production — only the `.py` shim is needed.

Runtime behavior:
    • The generated `.pyi` file is used only by type checkers and IDEs.
    • Production code imports `XPInterface` from the lightweight `.py` module.
    • No runtime dependency on XPPython3 is introduced by this script.

This script should be re-run whenever the upstream `xp.pyi` changes.
"""

import re
from pathlib import Path

# Path to your xp.pyi
XP_PYI = Path("../XPPython3/xp.pyi")

# Output path
OUT = Path("xp_interface.pyi")

# Regex to capture function signatures
FUNC_RE = re.compile(
    r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*->\s*([^:]+):",
    re.DOTALL
)

# Read xp.pyi
text = XP_PYI.read_text()

# Extract imports (everything before the first "def")
imports = ["from typing import Protocol"]
for line in text.splitlines():
    if line.startswith("def "):
        break
    imports.append(line)

# Extract all function signatures
functions = FUNC_RE.findall(text)

# Build Protocol file
out = []
out.extend(imports)
out.append("")
out.append("class XPInterface(Protocol):")

for name, args, ret in functions:
    # Insert self as first argument
    args = args.strip()
    if args:
        args = "self, " + args
    else:
        args = "self"
    out.append(f"    def {name}({args}) -> {ret.strip()}: ...")

# Write output
OUT.write_text("\n".join(out))

print(f"Generated {OUT}")
