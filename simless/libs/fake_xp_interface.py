
# simless/libs/fake_xp_interface.py
# Runtime shim so Python can import FakeXPInterface.
# The real Protocol lives in the stubs/simless/libs

from typing import TYPE_CHECKING

if not TYPE_CHECKING:
    class FakeXPInterface:
        """Runtime placeholder; FakeXP implements the real methods."""
        pass
