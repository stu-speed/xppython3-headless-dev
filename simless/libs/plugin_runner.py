# simless/libs/runner.py
# ===========================================================================
# SimlessRunner — production‑parity X‑Plane plugin lifecycle harness
#
# ROLE
#   Provide a deterministic, single‑source‑of‑truth execution environment
#   for XPPython3 plugins outside of X‑Plane. The runner owns lifecycle
#   sequencing, timing, flightloop scheduling, bridge synchronization, and
#   graphics frame dispatch. All simulation behavior is delegated to FakeXP
#   and DataRefManager.
#
# DESIGN
#   • Production‑parity ordering: graphics root is initialized BEFORE any
#     plugin load, start, or enable, matching X‑Plane’s widget subsystem.
#   • Plugins are fully independent: each receives a fresh xp interface and
#     may create windows or widgets during XPluginEnable without restriction.
#   • Runner drives a fixed‑rate simulation clock (60 Hz) and executes all
#     modern flightloops according to XPLM scheduling semantics.
#   • Bridge synchronization is runner‑owned: inbound META/UPDATE/ERROR
#     events are dispatched to DataRefManager before flightloops run.
#
#   • IMPORT ROOT BOOTSTRAP (simless/__init__.py):
#       simless/__init__.py inserts the production‑authentic XPPython3 import
#       roots into sys.path BEFORE any simless module is imported. This ensures:
#
#         - XPPython3 is always treated as a real package (never a namespace)
#         - xp_typing, utils, and all package submodules remain importable
#         - plugin imports behave identically to X‑Plane’s embedded Python
#
#       The bootstrap is transparent to all run scripts and requires no
#       participation from FakeXP or the runner.
#
#   • XPPython3.xp FAÇADE WIRING (simless/xppython3_runtime.py):
#       The façade is installed during simless bootstrap, not by FakeXP.
#       The real XPPython3 package is preserved intact; only the `xp`
#       submodule is synthetic. simless/xppython3_runtime.py installs a
#       dynamic proxy module into:
#
#         • sys.modules["xp"]
#         • sys.modules["XPPython3.xp"]
#         • XPPython3.xp
#
#       The façade implements module‑level __getattr__ and __dir__ so that:
#
#         import xp
#         from XPPython3 import xp
#         from XPPython3.xp import foo
#
#       all resolve to a proxy whose attribute access forwards to the active
#       FakeXP instance. This mirrors XPPython3’s dynamic attribute model
#       while preserving the rest of the package unchanged.
#
# CORE INVARIANTS
#   • No inference, no hidden state: runner behavior is explicit and
#     deterministic across all environments.
#   • No plugin‑specific branching: lifecycle is identical for every plugin.
#   • Graphics, widgets, and DataRefManager are always initialized before
#     XPluginEnable, ensuring production‑authentic UI behavior.
#   • Flightloops, bridge sync, and graphics frames are executed in a strict,
#     documented order each frame.
#   • XPPython3 package integrity is preserved; only the `xp` submodule is
#     synthetic and always forwards to the active FakeXP instance.
#   • sys.path bootstrap ensures import stability and prevents namespace
#     package creation across all environments.
#
# LIFECYCLE SEQUENCE
#   1. xp.init_graphics_root()        — graphics + widget system ready
#   2. loader.load_plugins()          — import plugin modules
#   3. xp._bind_datarefs()            — establish DataRefManager
#   4. XPluginStart()                 — plugin metadata only
#   5. XPluginEnable()                — plugins may create windows/UI
#   6. Main loop (flightloops → widgets → graphics)
#   7. XPluginDisable()
#   8. XPluginStop()
# ===========================================================================

from __future__ import annotations

import os
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from XPPython3.xp_typing import XPLMMenuID, XPLMPluginID
from simless.libs.dataref import DataRefManager
from simless.libs.fake_xp_types import XPShutdown
from simless.libs.plugin_loader import LoadedPlugin

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class SimlessRunner:
    """Deterministic simless execution harness.

    The runner provides a minimal, explicit, single‑source‑of‑truth
    execution environment for plugin code outside of X‑Plane. It owns
    timing, callback scheduling, lifecycle sequencing, and bridge
    synchronization. All simulation behavior is delegated to FakeXP and
    DataRefManager.
    """

    main_menu: XPLMMenuID | None

    def __init__(
            self,
            fake_xp: FakeXP,
            enable_dataref_bridge: bool = False,
            bridge_host: Optional[str] = None,
            bridge_port: Optional[int] = None,
    ) -> None:
        self.fake_xp = fake_xp
        self._enable_dataref_bridge: bool = enable_dataref_bridge

        # ------------------------------------------------------------------
        # Core state
        # ------------------------------------------------------------------
        self._running: bool = False
        self._sim_time = 0.0

        # ------------------------------------------------------------------
        # 1. Install synthetic XPPython3 runtime BEFORE importing plugin code
        # ------------------------------------------------------------------
        #
        # This ensures that:
        #   from XPPython3 import xp
        #   from XPPython3.xp import drawString
        #   import xp
        #
        # all resolve to the FakeXP façade, not plugins/XPPython3/xp.py.
        #
        from simless.libs.xppython3_runtime import wire_xppython3_runtime
        wire_xppython3_runtime(self.fake_xp)

        # ------------------------------------------------------------------
        # 2. Now it is safe to import bridge_protocol
        # ------------------------------------------------------------------
        #
        # bridge_protocol imports:
        #       from XPPython3 import xp
        #
        # If we imported it earlier, Python would load the real
        # plugins/XPPython3/xp.py and crash on:
        #       import XPLMCamera
        #
        from simless.libs.bridge_client import XPBridgeClient
        from simless.libs.dataref_viewer import FakeXPDataRefViewerClient

        self.dataref_viewer = FakeXPDataRefViewerClient(self.fake_xp)
        self.bridge_client = XPBridgeClient(self.fake_xp, host=bridge_host, port=bridge_port)

        # ------------------------------------------------------------------
        # 4. Plugin loader (safe now that XPPython3 is synthetic)
        # ------------------------------------------------------------------
        from simless.libs.plugin_loader import SimlessPluginLoader
        self.loader: SimlessPluginLoader = SimlessPluginLoader(self.fake_xp)

        # ------------------------------------------------------------------
        # 5. Flightloop state
        # ------------------------------------------------------------------
        self._next_flightloop_id: int = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time: float = 0.0
        self._cycles: int = 0
        # No plugin executing by default
        self._current_plugin_id: XPLMPluginID | None = None

    @property
    def dm(self) -> DataRefManager:
        return self.fake_xp.dataref_manager

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @sim_time.setter
    def sim_time(self, value: float):
        self._sim_time = value

    @property
    def cycles(self) -> int:
        return self._cycles

    @cycles.setter
    def cycles(self, value: int):
        self._cycles = value

    @property
    def active_plugin(self) -> LoadedPlugin | None:
        if self._current_plugin_id is None:
            return None
        return self.loader.get_plugin(self._current_plugin_id)

    @contextmanager
    def plugin_context(self, plugin_id: XPLMPluginID):
        """
        Context manager that temporarily sets the active plugin identity for the
        duration of a callback, matching XPPython3 and X‑Plane execution semantics.

        X‑Plane always executes plugin callbacks (flightloops, widget handlers,
        message receivers, draw callbacks, etc.) with a specific "current plugin"
        in scope. This identity determines:

          • xp.getMyID() return value
          • which plugin owns newly created flightloops, widgets, and datarefs
          • which plugin receives log attribution
          • which plugin receives synchronous message replies
          • correct routing of nested plugin→plugin calls

        Because plugin callbacks may be nested (e.g., Plugin A sends a message to
        Plugin B, and Plugin B calls back into the SDK), the context manager must
        restore the previous plugin ID after the callback completes. Without this
        push/pop behavior, subsequent API calls would execute under the wrong
        plugin identity, breaking ownership, logging, and message routing.

        This context manager therefore:

          1. Saves the currently active plugin ID.
          2. Sets the active plugin to `plugin_id` for the duration of the block.
          3. Restores the previous plugin ID on exit, even if an exception occurs.

        All plugin lifecycle calls (XPluginStart, XPluginEnable, XPluginDisable,
        XPluginStop), message dispatch (XPluginReceiveMessage), flightloop
        execution, and widget event handling must run inside this context to
        preserve X‑Plane‑authentic behavior.
        """

        prev = self._current_plugin_id
        self._current_plugin_id = plugin_id
        try:
            yield
        finally:
            self._current_plugin_id = prev

    # ----------------------------------------------------------------------
    # Stop loop
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        self._running = False
        self.fake_xp.log("[Runner] end_run_loop() called — stopping main loop")

    # ----------------------------------------------------------------------
    # One frame
    # ----------------------------------------------------------------------

    def _run_one_frame(self) -> None:
        xp = self.fake_xp

        # ------------------------------------------------------------
        # 1) Advance sim time
        # ------------------------------------------------------------
        dt = 1.0 / 60.0
        self.sim_time += dt
        xp._sim_time = self.sim_time
        now = self.sim_time

        # Advance cycle counter
        self._cycles += 1
        cycle = self._cycles

        # ------------------------------------------------------------
        # 2) Bridge sync
        # ------------------------------------------------------------
        if self.bridge_client.ready_for_processing():
            self.bridge_client.manage_bridged_datarefs()

        # ------------------------------------------------------------
        # 3) Run flightloops (under plugin context)
        # ------------------------------------------------------------
        for fl in xp.all_flightloop():
            try:
                # noinspection PyArgumentList
                with self.plugin_context(fl.plugin_id):
                    fl.check_and_run(now, cycle)
            except Exception:
                tb = traceback.format_exc()
                plugin = self.loader.get_plugin(fl.plugin_id)
                name = plugin.name if plugin else "<unknown plugin>"
                xp.log(f"[FlightLoop:{name}] callback exception:\n{tb}")
                fl.schedule(0.0, True, now, cycle)
                continue

        # 5. Dataref viewer
        if self.dataref_viewer.attached:
            self.dataref_viewer.update()

        # ------------------------------------------------------------
        # 6) Graphics frame (draw callbacks, XP→DPG sync, DPG flush, render)
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.graphics_manager.draw_frame()

    def run_plugin_lifecycle(
            self,
            plugin_names: List[str],
            run_time: float = -1,
    ) -> None:
        """
        Full X‑Plane‑style plugin lifecycle runner.

        Phases:
          1. Optional GUI initialization
          2. XPluginStart (via loader)
          3. XPluginEnable
          4. Main loop (flightloop + XP→DPG sync + draw dispatch)
          5. XPluginDisable
          6. XPluginStop
          7. Optional GUI teardown
        """

        xp = self.fake_xp

        if not plugin_names:
            xp.log("[Runner] No plugins to run")
            return

        self.bridge_client.set_enabled(self._enable_dataref_bridge)

        # ------------------------------------------------------------
        # 1. GUI Initialization (optional)
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.graphics_manager.init_graphics_root()
            xp.log("[Runner] GUI enabled (FakeXPGraphics manages DearPyGui)")

            self.create_main_menu()

        # ------------------------------------------------------------
        # 2. XPluginStart (loader handles this)
        # ------------------------------------------------------------
        self.loader.load_plugins(plugin_names)
        plugins = self.loader.loaded_plugins

        os.chdir(self.loader.plugins_root)

        # ------------------------------------------------------------
        # 3. XPluginEnable
        # ------------------------------------------------------------
        xp.log("[Runner] === XPluginEnable ===")

        for p in plugins:
            try:
                # noinspection PyArgumentList
                with self.plugin_context(p.plugin_id):
                    result = p.instance.XPluginEnable()
                xp.log(f"[Runner] → XPluginEnable: {p.name} ret={result}")
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginEnable failed for {p.name}: {exc!r}"
                )

            p.enabled = bool(result)
            if not p.enabled:
                xp.log(f"[Runner] Plugin disabled by XPluginEnable: {p.name}")

        # ------------------------------------------------------------
        # 4. Main loop
        # ------------------------------------------------------------
        xp.log("[Runner] === Flight Loop ===")
        self._running = True
        xplane_broadcast_sent = False
        start = time.monotonic()
        target_dt = 1.0 / 60.0

        while self._running:
            frame_start = time.monotonic()

            try:
                # Flightloop + XPWidgets sync + draw dispatch
                self._run_one_frame()
            except XPShutdown:
                xp.log("[Runner] Fligh loop exit: shutdown")
                break
            except Exception as exc:
                tb = traceback.format_exc()
                xp.log(f"[Runner] graphics/frame error: {exc!r}\n{tb}")
                break

            # Optional timed exit
            if 0 <= run_time <= (time.time() - start):
                xp.log("[Runner] Flight loop exit: run_time reached")
                break

            # Maintain ~60 FPS
            elapsed = time.monotonic() - frame_start
            remaining = target_dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

            if not xplane_broadcast_sent and time.monotonic() - start > 5:
                xp.log("[Runner] === Send X-Plane Broadcasts ===")
                self.send_initial_xplane_broadcasts()
                xplane_broadcast_sent = True

        # ------------------------------------------------------------
        # 5. XPluginDisable
        # ------------------------------------------------------------
        xp.log("[Runner] === XPluginDisable ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginDisable: {p.name}")
                # noinspection PyArgumentList
                with self.plugin_context(p.plugin_id):
                    p.instance.XPluginDisable()
                p.enabled = False
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginDisable failed for {p.name}: {exc!r}"
                )

        # ------------------------------------------------------------
        # 6. XPluginStop
        # ------------------------------------------------------------
        xp.log("[Runner] === XPluginStop ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginStop: {p.name}")
                p.instance.XPluginStop()
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginStop failed for {p.name}: {exc!r}"
                )

        # ------------------------------------------------------------
        # 7. GUI teardown
        # ------------------------------------------------------------

        if xp.enable_gui:
            xp.log("[Runner] === GUI Teardown ===")
            self.dataref_viewer.detach()

    def broadcast_message(self, sender_id: int, msg: int, param) -> None:
        """Broadcast to all enabled plugins."""
        for p in self.loader.loaded_plugins:
            self.dispatch_message_to_plugin(p, sender_id, msg, param)

    def dispatch_message_to_plugin(
            self,
            plugin: LoadedPlugin,
            sender_id: int,
            msg: int,
            param,
    ) -> None:
        """Execute XPluginReceiveMessage using the same workflow as Start/Enable."""
        if not plugin.enabled or not plugin.has_receive():
            return

        try:
            # noinspection PyArgumentList
            with self.plugin_context(plugin.plugin_id):
                plugin.receive_message(sender_id, msg, param)
        except Exception as exc:
            raise RuntimeError(
                f"[Runner] XPluginReceiveMessage failed for {plugin.name}: {exc!r}"
            )

    def send_initial_xplane_broadcasts(self) -> None:
        xp = self.fake_xp

        initial_msgs = [
            xp.MSG_PLANE_LOADED,
            xp.MSG_AIRPORT_LOADED,
            xp.MSG_SCENERY_LOADED,
        ]

        for msg in initial_msgs:
            # sender is X‑Plane itself
            self.broadcast_message(0, msg, xp.PLUGIN_XPLANE)

    def create_main_menu(self) -> None:
        self.main_menu = self.fake_xp.createMenu(name="FakeXP")

        cmd_toggle_bridge = self.fake_xp.createCommand(
            "FakeXP/Bridge/Toggle",
            "Toggle the dataref bridge"
        )
        self.fake_xp.registerCommandHandler(
            cmd_toggle_bridge,
            self._cmd_toggle_bridge,
            1,
            None
        )
        self.fake_xp.appendMenuItemWithCommand(
            self.main_menu,
            self.bridge_client.menu_label,
            cmd_toggle_bridge
        )

        cmd_toggle_viewer = self.fake_xp.createCommand(
            "FakeXP/DatarefViewer/Toggle",
            "Toggle Dataref Viewer window"
        )
        self.fake_xp.registerCommandHandler(
            cmd_toggle_viewer,
            self._cmd_toggle_viewer,
            1,  # before
            None
        )
        self.fake_xp.appendMenuItemWithCommand(self.main_menu, 'Dataref Viewer', cmd_toggle_viewer)

    def _cmd_toggle_bridge(self, cmd, phase, refcon):
        if phase == self.fake_xp.CommandBegin:
            self.bridge_client.set_enabled(not self.bridge_client.enabled)
            self.fake_xp.setMenuItemName(self.main_menu, 0, self.bridge_client.menu_label)
        return 1

    def _cmd_toggle_viewer(self, commandRef, phase, refCon):
        if phase == self.fake_xp.CommandBegin:
            if self.dataref_viewer.attached:
                self.dataref_viewer.detach()
            else:
                self.dataref_viewer.attach()
        return 1
