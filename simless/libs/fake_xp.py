# simless/libs/fake_xp/fakexp.py
# ===========================================================================
# FakeXP — unified xp.* façade for simless plugin execution
#
# ROLE
#   Provide a deterministic, minimal, X‑Plane‑authentic façade for simless
#   execution. FakeXP must mirror the public API surface of the real
#   XPPython3 xp.* API (as described by SimlessXPInterface) without adding
#   behavior, inference, or hidden state. It enables plugin code to run
#   identically in headless mode.
#
# CORE INVARIANTS
#   - Will use the Public API as much as possible
#   - FakeXP must match real xp.* method names, signatures, and return
#     types as defined by SimlessXPInterface.
#   - FakeXP must never mutate XPLMDataRefInfo_t or any SDK‑shaped object.
#   - FakeXP must not introduce fields, flags, or attributes not present in
#     the real X‑Plane API.
#   - FakeXP must not infer semantics or perform validation; it only
#     simulates the minimal behavior required for deterministic execution.
#
# DATAREF RULES
#   - FakeXP must not compute or infer array_size; callers must supply it.
#   - FakeXP must return values in the same shape and type as real X‑Plane:
#         scalars → Python primitives
#         arrays  → lists of primitives
#   - FakeXP must not normalize, coerce, or transform values.
#   - FakeXP must not create dummy DataRefs unless explicitly requested by
#     the DataRefManager.
#
# METADATA RULES
#   - FakeXP.getDataRefInfo() must return an XPLMDataRefInfo_t‑shaped object
#     with only the real X‑Plane fields (name, type, writable).
#   - FakeXP must not add array_size or any other synthetic metadata.
#   - All normalization of metadata belongs to DataRefSpec.
#
# VALUE ACCESS RULES
#   - FakeXP.getData*() methods must return deterministic values based on
#     internal storage only.
#   - FakeXP.setData*() methods must update internal storage without side
#     effects.
#   - FakeXP must not perform bounds checking or type validation; that is
#     the responsibility of DataRefSpec/DataRefManager.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable

import XPPython3
from XPPython3.xp_typing import (
    XPLMFlightLoopID,
    XPLMFlightLoopPhaseType,
    XPWidgetID,
)

from sshd_extensions.datarefs import DataRefManager
from simless.libs.runner import SimlessRunner
from simless.libs.fake_xp_constants import bind_xp_constants
from simless.libs.fake_xp_dataref import FakeXPDataRef
from simless.libs.fake_xp_widget import FakeXPWidget
from simless.libs.fake_xp_graphics import FakeXPGraphics
from simless.libs.fake_xp_flightloop import FakeXPFlightLoop
from simless.libs.fake_xp_utilities import FakeXPUtilities
from simless.libs.fake_xp_interface import FakeXPInterface


# For alignment with SimlessXPInterface
FlightLoopCallback = Callable[[float, float, int, Any], float]


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

    This class is intended to satisfy:
      • SimlessXPInterface
      • FakeXPInterface
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

        # Track disabled plugins (XPLMDisablePlugin)
        self._disabled_plugins: set[int] = set()

        self._sim_time: float = 0.0
        self._keyboard_focus: XPWidgetID | None = None

        # ------------------------------------------------------------------
        # Initialize subsystems
        # ------------------------------------------------------------------
        self._init_dataref()
        self._init_widgets()
        self._init_graphics()
        self._init_flightloop()
        self._init_utilities()

        # ------------------------------------------------------------------
        # Bind xp.* namespace
        # ------------------------------------------------------------------
        XPPython3.xp = self
        self.xp: FakeXPInterface  = XPPython3.xp  # type: ignore[arg-type]

        bind_xp_constants(self.xp)

        # Bind subsystem public APIs into xp.* ONLY
        for subsystem in (
            FakeXPDataRef,
            FakeXPWidget,
            FakeXPGraphics,
            FakeXPFlightLoop,
            FakeXPUtilities,
        ):
            for name in getattr(subsystem, "public_api_names", []):
                fn = getattr(self, name)
                setattr(self.xp, name, fn)

        # destroyWidget wrapper (XPPython3-style)
        def destroyWidget(self_: FakeXP, wid: XPWidgetID, destroy_children: int = 1) -> None:
            # XPPython3's xp.destroyWidget delegates to killWidget; we mirror that.
            self_.killWidget(wid)

        self.xp.destroyWidget = destroyWidget.__get__(self)

        # ------------------------------------------------------------------
        # Create the SimlessRunner automatically
        # ------------------------------------------------------------------
        self._runner = SimlessRunner(self.xp, run_time=run_time)

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug:
            print(f"[FakeXP] {msg}")

    def _quit(self) -> None:
        """
        Stop the internal runner.
        """
        if self._runner is not None:
            self._runner.end_run_loop()

    # ----------------------------------------------------------------------
    # Lifecycle runner
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(
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


    # ----------------------------------------------------------------------
    # Base xp methods (XPPython3-compatible, SimlessXPInterface)
    # ----------------------------------------------------------------------
    def getMyID(self) -> int:
        """
        XPLMGetMyID()
        In this simless environment we treat the current plugin as ID 1.
        """
        return 1

    def disablePlugin(self, plugin_id: int) -> None:
        """
        XPLMDisablePlugin(plugin_id)
        Marks the plugin as disabled.
        """
        self._disabled_plugins.add(plugin_id)
        self._dbg(f"disablePlugin({plugin_id})")

    def isPluginEnabled(self, plugin_id: int) -> int:
        """
        XPLMIsPluginEnabled(plugin_id)
        Returns 1 if enabled, 0 if disabled.
        """
        return 0 if plugin_id in self._disabled_plugins else 1

    def findPluginBySignature(self, signature: str) -> int:
        """
        XPLMFindPluginBySignature(signature)
        Returns plugin ID or -1.
        """
        if self._runner is None or self._runner.loader is None:
            return -1
        return self._runner.loader.find_plugin_by_signature(signature)

    def findPluginByPath(self, path: str) -> int:
        """
        XPLMFindPluginByPath(path)
        Returns plugin ID or -1.
        """
        if self._runner is None or self._runner.loader is None:
            return -1
        return self._runner.loader.find_plugin_by_path(path)

    def getPluginInfo(self, plugin_id: int) -> tuple[str, str, str, str]:
        """
        XPLMGetPluginInfo(plugin_id)
        Returns (name, signature, description, path).
        Raises RuntimeError if plugin_id is invalid.
        """
        if self._runner is None or self._runner.loader is None:
            raise RuntimeError("FakeXP: getPluginInfo called before runner initialized")

        plugin = self._runner.loader.get_plugin(plugin_id)
        if plugin is None:
            raise RuntimeError(f"FakeXP: No plugin with ID {plugin_id}")

        module_path = getattr(plugin.module, "__file__", "<inline>")

        return (
            plugin.name,
            plugin.signature,
            plugin.description,
            module_path,
        )

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # DataRefManager binding (FakeXPInterface)
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        self._dataref_manager = mgr
        self._dbg("[DataRef] DataRefManager bound to FakeXP")

    # ----------------------------------------------------------------------
    # Time (SimlessXPInterface)
    # ----------------------------------------------------------------------
    def getElapsedTime(self) -> float:
        return self._sim_time

    # ----------------------------------------------------------------------
    # Keyboard focus (SimlessXPInterface-compatible)
    # ----------------------------------------------------------------------
    def getKeyboardFocus(self) -> XPWidgetID | None:
        return self._keyboard_focus

    def setKeyboardFocus(self, wid: XPWidgetID | None) -> None:
        """
        SimlessXPInterface: setKeyboardFocus(self, wid: XPWidgetID | None) -> None
        """
        self._keyboard_focus = wid
        self._dbg(f"Keyboard focus → {wid}")

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        """
        SimlessXPInterface: loseKeyboardFocus(self, wid: XPWidgetID) -> None
        """
        if self._keyboard_focus == wid:
            self._keyboard_focus = None
            self._dbg("Keyboard focus cleared")

    # ----------------------------------------------------------------------
    # Flightloop forwarding to SimlessRunner (SimlessXPInterface)
    # ----------------------------------------------------------------------
    def createFlightLoop(
        self,
        callback: FlightLoopCallback
        | tuple[int, FlightLoopCallback, Any]
        | list[Any],
        phase: XPLMFlightLoopPhaseType = XPLMFlightLoopPhaseType(0),
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID:
        """
        XPPython3-style createFlightLoop wrapper.

        Accepts either:
          • a bare callback: xp.createFlightLoop(callback)
          • a tuple:        xp.createFlightLoop((phase, callback, refCon))
          • a list:         xp.createFlightLoop([phase, callback, refCon])
        """
        if self._runner is None:
            raise RuntimeError("FakeXP._runner must exist before createFlightLoop")

        # Normalize into the internal struct dict expected by SimlessRunner.
        if callable(callback):
            params = {
                "callback": callback,
                "refcon": refCon,
                "phase": phase,
                "structSize": 1,
            }
        elif isinstance(callback, (tuple, list)) and len(callback) >= 2:
            cb_phase = int(callback[0])
            cb_func = callback[1]
            cb_refcon = callback[2] if len(callback) > 2 else refCon
            params = {
                "callback": cb_func,
                "refcon": cb_refcon,
                "phase": cb_phase,
                "structSize": 1,
            }
        else:
            # Fallback: treat as a dict-like struct if someone passes that in.
            params = dict(callback)  # type: ignore[arg-type]
            params.setdefault("refcon", refCon)
            params.setdefault("phase", phase)
            params.setdefault("structSize", 1)

        fid = self._runner.create_flightloop(2, params)
        return XPLMFlightLoopID(fid)

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval: float,
        relativeToNow: int = 1,
    ) -> None:
        """
        XPPython3-style scheduleFlightLoop wrapper.

        The runner owns all real scheduling; FakeXP just forwards.
        """
        if self._runner is None:
            raise RuntimeError("FakeXP._runner must exist before scheduleFlightLoop")
        # relativeToNow is ignored in simless mode; runner controls timing.
        self._runner.schedule_flightloop(loop_id, interval)

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None:
        """
        XPPython3-style destroyFlightLoop wrapper.

        The runner owns the registry of active flightloops.
        """
        if self._runner is None:
            raise RuntimeError("FakeXP._runner must exist before destroyFlightLoop")
        self._runner.destroy_flightloop(loop_id)
