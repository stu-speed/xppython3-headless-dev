# ===========================================================================
# FakeXPProtocol — simless‑only extensions to XPInterface
#
# FakeXP implements XPInterface (the production‑safe API) plus a small set of
# simless‑only helpers used by DataRefManager, the simless runner, and test
# harnesses. These helpers are *not* part of the real XPPython3 API and must
# never appear in XPInterface.
#
# This Protocol allows:
#   • FakeXP to expose simless‑only methods without polluting XPInterface
#   • DataRefManager and simless tools to type‑check FakeXP‑specific calls
#   • XPInterface to remain clean, minimal, and production‑safe
#
# Production plugins do not import or depend on this Protocol.
# ===========================================================================

from __future__ import annotations

from typing import Protocol, Any

from sshd_extensions.datarefs import DataRefManager


class FakeXPInterface(Protocol):
    """
    Simless‑only API surface implemented by FakeXP.
    These methods do not exist in real XPPython3 and must not be added
    to XPInterface.
    """

    # ------------------------------------------------------------------
    # DataRef auto‑registration (simless only)
    # ------------------------------------------------------------------
    def fake_register_dataref(
        self,
        path: str,
        *,
        xp_type: int,
        is_array: bool = False,
        size: int = 1,
        writable: bool = True,
    ) -> Any:
        """
        Create a FakeDataRefInfo entry and allocate default storage.
        Used by DataRefRegistry during simless initialization.
        """
        ...

    # ------------------------------------------------------------------
    # DataRefManager binding (simless only)
    # ------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        """
        Attach the DataRefManager so FakeXP can notify it when values change.
        Real XPPython3 does not support this.
        """
        ...

    # ------------------------------------------------------------------
    # Optional simless lifecycle helpers
    # ------------------------------------------------------------------
    def _run_plugin_lifecycle(
        self,
        plugin_names: list[str],
        *,
        debug: bool = False,
        enable_gui: bool = True,
        run_time: float = -1.0,
    ) -> None:
        """
        Simless runner entry point. Not part of the real xp.* API.
        """
        ...

    def _quit(self) -> None:
        """
        Stop the simless run loop. No production equivalent.
        """
        ...
