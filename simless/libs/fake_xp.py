# simless/libs/fake_xp/fakexp.py
# ===========================================================================
# FakeXP — unified xp.* façade for simless plugin execution
# ===========================================================================

from __future__ import annotations

from typing import Any

import XPPython3
from XPPython3.xp_typing import XPWidgetID

from plugins.sshd_extensions.datarefs import DataRefManager

from .constants import bind_xp_constants
from .fake_xp_dataref import FakeXPDataRef
from .fake_xp_widget import FakeXPWidget
from .fake_xp_graphics import FakeXPGraphics
from .fake_xp_flightloop import FakeXPFlightLoop
from .fake_xp_utilities import FakeXPUtilities
from simless.libs.runner import SimlessRunner


class FakeXP(
    FakeXPDataRef,
    FakeXPWidget,
    FakeXPGraphics,
    FakeXPFlightLoop,
    FakeXPUtilities,
):
    """
    Unified xp.* façade for simless plugin execution.
    Subsystems are cooperative mixins with _init_*() initializers.
    FakeXP automatically creates and owns a SimlessRunner.
    """

    def __init__(
        self,
        *,
        debug: bool = False,
        enable_gui: bool = True,
        run_time: float = -1.0,
    ) -> None:

        self.debug = debug
        self.enable_gui = enable_gui

        # Core state
        self._dataref_manager: DataRefManager | None = None
        self._plugins: list[Any] = []
        self._disabled_plugins: set[int] = set()
        self._sim_time: float = 0.0
        self._keyboard_focus: int | None = None

        # Runner will be created after subsystems initialize
        self._runner: SimlessRunner | None = None

        # ------------------------------------------------------------------
        # Initialize subsystems
        # ------------------------------------------------------------------
        self._init_dataref()
        self._init_widgets()
        self._init_graphics()
        self._init_flightloop()
        self._init_utilities()

        # ------------------------------------------------------------------
        # Create the SimlessRunner automatically
        # ------------------------------------------------------------------
        self._runner = SimlessRunner(self, run_time=run_time)

        # ------------------------------------------------------------------
        # Bind xp.* namespace
        # ------------------------------------------------------------------
        XPPython3.xp = self
        xp = XPPython3.xp

        bind_xp_constants(xp)

        # Bind subsystem public APIs
        for subsystem in (
            FakeXPDataRef,
            FakeXPWidget,
            FakeXPGraphics,
            FakeXPFlightLoop,
            FakeXPUtilities,
        ):
            for name in getattr(subsystem, "public_api_names", []):
                fn = getattr(self, name)
                setattr(xp, name, fn)
                setattr(self, name, fn)

        # destroyWidget wrapper (XPPython3-style)
        def destroyWidget(self_: FakeXP, wid: XPWidgetID, destroy_children: int = 1) -> None:
            self_.killWidget(wid)

        xp.destroyWidget = destroyWidget.__get__(self)
        self.destroyWidget = destroyWidget.__get__(self)

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug:
            print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # Lifecycle helpers
    # ----------------------------------------------------------------------
    def _run_plugin_lifecycle(
        self,
        plugin_names: list[str],
        *,
        run_time: float = -1.0,
    ) -> None:
        """
        Delegate lifecycle execution to the internal SimlessRunner.
        """
        if self._runner is None:
            raise RuntimeError("FakeXP._runner must exist (internal error)")

        if run_time >= 0:
            self._runner.run_time = run_time

        self._runner.run_plugin_lifecycle(plugin_names)

    def _quit(self) -> None:
        """
        Stop the internal runner.
        """
        if self._runner is not None:
            self._runner.end_run_loop()

    # ----------------------------------------------------------------------
    # Base xp methods
    # ----------------------------------------------------------------------
    def getMyID(self) -> int:
        return 1

    def disablePlugin(self, plugin_id: int) -> None:
        self._disabled_plugins.add(plugin_id)
        self._dbg(f"disablePlugin({plugin_id})")

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # DataRefManager binding
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        self._dataref_manager = mgr
        self._dbg("[DataRef] DataRefManager bound to FakeXP")

    # ----------------------------------------------------------------------
    # Time
    # ----------------------------------------------------------------------
    def getElapsedTime(self) -> float:
        return self._sim_time

    # ----------------------------------------------------------------------
    # Keyboard focus
    # ----------------------------------------------------------------------
    def getKeyboardFocus(self) -> int | None:
        return self._keyboard_focus

    def setKeyboardFocus(self, widget_id: XPWidgetID) -> None:
        self._keyboard_focus = widget_id
        self._dbg(f"Keyboard focus → {widget_id}")

    def loseKeyboardFocus(self, widget_id: XPWidgetID) -> None:
        if self._keyboard_focus == widget_id:
            self._keyboard_focus = None
            self._dbg("Keyboard focus cleared")

    # ----------------------------------------------------------------------
    # Plugin info
    # ----------------------------------------------------------------------
    def getPluginInfo(self, plugin_id: int) -> tuple[str, str, str, str]:
        return ("Fake Plugin", "1.0", "FakeXP", "Simless")
