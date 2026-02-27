"""
xp_interface.py
----------------

This module provides a lightweight runtime placeholder for the XPInterface
type so production plugins and bridge-connected modules can safely import it.

XPPython3 loads plugins strictly by filename. The plugin directory is not a
Python package, and must not contain `__init__.py` or use relative imports.
If Python is allowed to treat the plugin tree as a package, the same plugin
module can be imported under multiple names, which results in multiple plugin
instances and multiple `xp` objects.

The bridge architecture relies on a single shared `xp` handle created by the
host. A plugin obtains that handle by doing:

    from XPPython3 import xp

This is the only correct way to receive the real xp object. Plugins must not
import XPPython3 in any other way, and must not attempt to create their own
copy. The bridge and any helper modules must receive the same xp reference
that the plugin received from the host.

Because plugins cannot rely on package semantics, the xp handle must be
passed explicitly to any module that needs it, for example:

Using XPInterface in annotations makes this pattern clear while keeping the
runtime environment minimal and import-safe.

Do not add behavior or imports here. This module must remain lightweight and
safe to load in all production plugin environments.
"""
"""
xp_interface.py
----------------

This module provides a lightweight runtime placeholder for the XPInterface
type so production plugins and bridge-connected modules can safely import it.

XPPython3 loads plugins strictly by filename. The plugin directory is not a
Python package and must not contain `__init__.py` or use relative imports.
If Python is allowed to treat the plugin tree as a package, the same plugin
module can be imported under multiple names, which leads to multiple plugin
instances and multiple `xp` objects.

The host imports XPPython3 exactly once and creates the shared `xp` handle.
A plugin obtains that handle by doing:

    from XPPython3 import xp

This is the only correct way to receive the real xp object. Plugins must not
import XPPython3 in any other way, and must not attempt to create their own
copy. Any module that needs access to `xp` must receive the same reference
explicitly. For example, a plugin may pass the handle into a bridge client:

    bridge = BridgeClient(xp)
    class BridgeClient:
        def __init__( self, xp_interface: XPInterface ) -> None:
            self.xp = xp_interface

This ensures that the bridge and all helper modules operate on the same
xp reference the host created.

During development, a corresponding `.pyi` file defines the full XPInterface
surface for static analysis. Editors and type checkers use that stub to
provide strong type checking and autocomplete. At runtime, only this `.py`
file is loaded, keeping the X-plane environment minimal and import‑safe.
"""


class XPInterface:
    """
    Runtime placeholder for the XPInterface type.
    """
    pass
