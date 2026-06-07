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

from XPPython3.xp_typing import XPLMPluginID

from simless.libs.dataref import DataRefManager, FakeDataRef
from simless.libs.dataref_viewer import FakeXPDataRefViewerClient
from simless.libs.fake_xp_types import XPShutdown
from simless.libs.plugin_loader import LoadedPlugin

if TYPE_CHECKING:
    import sshd_extensions.bridge_protocol as bridge_type
    from simless.libs.fake_xp import FakeXP


class SimlessRunner:
    """Deterministic simless execution harness.

    The runner provides a minimal, explicit, single‑source‑of‑truth
    execution environment for plugin code outside of X‑Plane. It owns
    timing, callback scheduling, lifecycle sequencing, and bridge
    synchronization. All simulation behavior is delegated to FakeXP and
    DataRefManager.
    """

    _bridge_client: bridge_type.XPBridgeClient | None
    _dataref_viewer: FakeXPDataRefViewerClient | None

    def __init__(
        self,
        fake_xp: FakeXP,
        enable_dataref_bridge: bool = False,
        bridge_host: Optional[str] = None,
        bridge_port: Optional[int] = None,
    ) -> None:
        # ------------------------------------------------------------------
        # Core state
        # ------------------------------------------------------------------
        self.fake_xp = fake_xp

        self._running: bool = False
        self._sim_time = 0.0
        self._bridge_connected: bool = False
        self._bridge_last_error: str | None = None
        self._bridge_client = None
        self._dataref_viewer = None

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
        import sshd_extensions.bridge_protocol as bridge_mod
        self._bridge_mod = bridge_mod

        # ------------------------------------------------------------------
        # 3. Create the dataref bridge (optional)
        # ------------------------------------------------------------------
        if enable_dataref_bridge:
            self._bridge_client = self._bridge_mod.XPBridgeClient(
                host=bridge_host or self._bridge_mod.BRIDGE_HOST,
                port=bridge_port or self._bridge_mod.BRIDGE_PORT,
            )
            self._attach_bridge_handle_callback()

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

    def get_bridge_status(self) -> tuple[bool, bool, str | None]:
        """
        Return bridge status as enabled, connected, last_error.
        """
        if self._bridge_client is None:
            return False, False, "Bridge not enabled"
        return True, self._bridge_client.is_connected, self._bridge_client.conn_status

    # ----------------------------------------------------------------------
    # Bridge registration callback wiring
    # ----------------------------------------------------------------------
    def _attach_bridge_handle_callback(self) -> None:
        """Attach a handle‑created callback so DataRefs auto‑register with the bridge.

        The DataRef subsystem emits discovery events; the runner decides
        whether and how those paths are synchronized externally.
        """
        self.dm.attach_handle_callback(self._on_dataref_handle_created)

    def _on_dataref_handle_created(self, ref: FakeDataRef) -> None:
        """Called synchronously when FakeXPDataRef creates a handle."""
        if not self._bridge_connected:
            return
        if self._bridge_client is None:
            return

        try:
            self._bridge_client.add([ref.path])
        except Exception as exc:
            try:
                self.fake_xp.log(f"[Runner] Bridge registration failed for {ref.path}: {exc}")
            except Exception:
                pass

    def _register_all_datarefs_with_bridge(self) -> None:
        """Register all known DataRef paths with the bridge.

        Called once on initial bridge connection and again on reconnect.
        """
        if self._bridge_client is None:
            return
        all_handle_paths = self.dm.all_handle_paths()

        try:
            self._bridge_client.add(all_handle_paths)
        except Exception:
            try:
                self.fake_xp.log(f"[Runner] Bridge registration failed for {all_handle_paths}")
            except Exception:
                pass

    # ----------------------------------------------------------------------
    # Bridge management
    # ----------------------------------------------------------------------
    # NOTE:
    # is_dummy means both type and value are provisional.
    # It flips to False only on the first provider‑originated UPDATE,
    # never on META.
    def _manage_bridged_datarefs(self) -> None:
        """Poll bridge events and update DataRefManager state.

        Connection management is handled entirely by XPBridgeClient.poll().
        This method only:
          • polls for inbound events,
          • applies META/UPDATE changes,
          • marks DataRefs dummy on disconnect,
          • logs bridge errors.
        """

        try:
            events: List[bridge_type.BridgeData] = self._bridge_client.poll_data()
        except ConnectionResetError as exc:
            self.fake_xp.log("[Runner] Bridge disconnected")
            self._bridge_connected = False
            self._bridge_last_error = f"connection reset: {exc}"
            return

        if not self._bridge_connected:
            self._bridge_connected = True
            self._bridge_last_error = None
            self._register_all_datarefs_with_bridge()

        for ev in events:
            if not ev.path:
                continue
            if ev.type is self._bridge_mod.BridgeDataType.META:
                ref = self.dm.get_handle(ev.path)
                if not ref or not ev.dtype:
                    continue

                # Promote TYPE authority only
                self.dm.promote_type(
                    ref=ref,
                    dtype=ev.dtype,
                    writable=bool(ev.writable),
                )

            elif ev.type is self._bridge_mod.BridgeDataType.UPDATE:
                ref = self.dm.get_handle(ev.path)
                assert ref is not None, f"Unknown handle: {ev.path}"
                value = ev.value

                is_array = isinstance(value, (list, tuple, bytearray))
                size = len(value) if is_array else 1

                # Promote shape if needed (first time or shape change)
                if (
                    not ref.shape_known
                    or ref.is_array != is_array
                    or ref.size != size
                ):
                    self.dm.promote_shape_from_value(
                        ref=ref,
                        value=value,
                    )
                else:
                    ref.value = value

            elif ev.type is self._bridge_mod.BridgeDataType.ERROR:
                self._bridge_last_error = ev.text
                self.fake_xp.log(f"[Bridge] ERROR: {ev.text}")

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
        # 2) Bridge sync (if any)
        # ------------------------------------------------------------
        if self._bridge_client is not None:
            self._manage_bridged_datarefs()

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
        if self._dataref_viewer:
            self._dataref_viewer.update()

        # ------------------------------------------------------------
        # 6) Graphics frame (draw callbacks, XP→DPG sync, DPG flush, render)
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.graphics_manager.draw_frame()

    def run_plugin_lifecycle(
        self,
        plugin_names: List[str],
        enable_dataref_viewer: bool = False,
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

        # ------------------------------------------------------------
        # 1. GUI Initialization (optional)
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.graphics_manager.init_graphics_root()
            xp.log("[Runner] GUI enabled (FakeXPGraphics manages DearPyGui)")

            if enable_dataref_viewer:
                self._dataref_viewer = FakeXPDataRefViewerClient(xp)
                self._dataref_viewer.attach()

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
        self._xplane_broadcast_sent = False
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

            if not self._xplane_broadcast_sent and time.monotonic() - start > 5:
                xp.log("[Runner] === Send X-Plane Broadcasts ===")
                self.send_initial_xplane_broadcasts()
                self._xplane_broadcast_sent = True

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
        if self._dataref_viewer:
            self._dataref_viewer.detach()
            self._dataref_viewer = None

        if xp.enable_gui:
            xp.log("[Runner] === GUI Teardown ===")

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
