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

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from simless.libs.dataref_viewer import DataRefCache
from simless.libs.dataref import DataRefManager
from simless.libs.fake_xp_constants import bind_xp_constants
from simless.libs.fake_xp_dataref import FakeXPDataRef
from simless.libs.fake_xp_flightloop import FakeXPFlightLoop
from simless.libs.fake_xp_graphics import FakeXPGraphics
from simless.libs.fake_xp_menu import FakeXPMenu, MenuManager
from simless.libs.fake_xp_utilities import FakeXPUtilities
from simless.libs.fake_xp_widget import FakeXPWidget
from simless.libs.graphics import GraphicsManager
from simless.libs.input import InputManager
from simless.libs.plugin_runner import SimlessRunner
from simless.libs.widget import WidgetManager
from simless.libs.window import WindowManager
from xp_typing import XPLMPluginID


class FakeXP(
    FakeXPDataRef,
    FakeXPWidget,
    FakeXPGraphics,
    FakeXPFlightLoop,
    FakeXPUtilities,
    FakeXPMenu,
):
    """
    Unified xp.* façade for simless plugin execution.

    FakeXP mirrors the public API surface of XPPython3's xp.* namespace
    while delegating all simulation behavior to FakeXP subsystems and the
    SimlessRunner. It provides deterministic, headless execution for
    plugin development and testing.
    """

    def __init__(
            self,
            enable_dataref_bridge: bool = False,
            bridge_host: Optional[str] = None,
            bridge_port: Optional[int] = None,
            enable_gui: bool = True,
            terminal_logging: bool = True,
            debug_logging: bool = False,
    ) -> None:
        self.enable_gui = enable_gui
        self.terminal_logging = terminal_logging
        self.debug_logging = debug_logging

        self._xplane_root = Path(__file__).resolve().parents[2]
        self._xpp_log = self._xplane_root / "XPPython3Log.txt"
        self._sim_log = self._xplane_root / "Log.txt"
        self._dataref_cache_path = self._xplane_root / "simless" / "DataRefCache.txt"

        self._xplane_version = 12050  # Pretend XP12.05
        self._xplm_version = 303  # XPLM 3.0.3
        self._host_id = 1  # Host_XPlane

        if not self.terminal_logging:
            # Fresh logs every run
            self._xpp_log.write_text("")
            self._sim_log.write_text("")

        # ------------------------------------------------------------------
        # Initialize subsystems
        # ------------------------------------------------------------------
        self._init_flightloop()
        self._init_utilities()

        # ------------------------------------------------------------------
        # Bind constants
        # ------------------------------------------------------------------
        bind_xp_constants(self)

        # ------------------------------------------------------------------
        # Bind Modules
        # ------------------------------------------------------------------
        self.dataref_manager = DataRefManager(self)
        self.graphics_manager = GraphicsManager(self)
        self.input_manager = InputManager(self)
        self.window_manager = WindowManager(self)
        self.widget_manager = WidgetManager(self)
        self.menu_manager = MenuManager(self)
        self.dataref_cache = DataRefCache(self)

        # Must be done last as it builds the FakeXP facade with what has been instantiated to this point
        self.simless_runner = SimlessRunner(self, enable_dataref_bridge, bridge_host, bridge_port)

    # ------------------------------------------------------------------
    # Plugin‑aware log → XPPython3Log.txt OR terminal
    # ------------------------------------------------------------------
    def log(self, msg: str, debug: bool = False) -> None:
        # Debug suppression
        if debug and not self.debug_logging:
            return

        try:
            plugin = self.simless_runner.active_plugin
        except AttributeError:
            plugin = None  # not instantiated yet
        prefix = plugin.name if plugin else "FakeXP"

        # Format line
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} {prefix}: {msg}\n"

        # Terminal-only mode
        if self.terminal_logging:
            print(line, end="")
            return

        # File output (XPPython3 log only)
        with self._xpp_log.open("a", encoding="utf-8") as f:
            f.write(line)

    def dbg(self, msg: str) -> None:
        self.log(msg, debug=True)

    # ------------------------------------------------------------------
    # System log → Log.txt OR terminal
    # ------------------------------------------------------------------
    def systemLog(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} FakeXP: {msg}\n"

        # Terminal-only mode
        if self.terminal_logging:
            print(line, end="")
            return

        # File output (X‑Plane Log.txt only)
        with self._sim_log.open("a", encoding="utf-8") as f:
            f.write(line)

    def sys_log(self, msg: str) -> None:
        self.systemLog(msg)

    def getVersions(self):
        """
        FakeXP implementation of xp.getVersions()

        Returns:
            tuple[int, int, int]:
                (xplaneVersion, xplmVersion, hostID)

        Meaning:
            xplaneVersion : integer revision of X‑Plane
                            e.g. 12050 → X‑Plane 12.05
            xplmVersion   : XPLM SDK version (e.g. 303 → 3.0.3)
            hostID        : 1 = Host_XPlane, 0 = Host_Unknown
        """
        # These values are configurable inside FakeXP so plugins can
        # special‑case XP11 vs XP12 behavior during sim‑less execution.

        return (
            self._xplane_version,  # int
            self._xplm_version,  # int
            self._host_id  # int
        )

    # ----------------------------------------------------------------------
    # Base xp methods (XPPython3-compatible, SimlessXPInterface)
    # ----------------------------------------------------------------------
    def getMyID(self) -> XPLMPluginID:
        """
        XPLMGetMyID()
        Returns the plugin ID of the currently executing plugin.
        """
        plugin = self.simless_runner.active_plugin
        return plugin.plugin_id if plugin else XPLMPluginID(0)

    def disablePlugin(self, plugin_id: XPLMPluginID) -> None:
        """
        XPLMDisablePlugin(plugin_id)
        Marks the plugin as disabled.
        """
        p = self.simless_runner.loader.get_plugin(plugin_id)
        if not p:
            return
        p.enabled = False

    def isPluginEnabled(self, plugin_id: XPLMPluginID) -> int:
        """
        XPLMIsPluginEnabled(plugin_id)
        Returns 1 if enabled, 0 if disabled.
        """
        p = self.simless_runner.loader.get_plugin(plugin_id)
        if not p:
            return 0
        return 1 if p.enabled else 0

    def findPluginBySignature(self, signature: str) -> XPLMPluginID:
        """
        XPLMFindPluginBySignature(signature)
        Returns plugin ID or -1.
        """
        return self.simless_runner.loader.find_plugin_by_signature(signature)

    def findPluginByPath(self, path: str) -> XPLMPluginID:
        """
        XPLMFindPluginByPath(path)
        Returns plugin ID or -1.
        """
        return self.simless_runner.loader.find_plugin_by_path(path)

    def getPluginInfo(self, plugin_id: XPLMPluginID) -> tuple[str, str, str, str]:
        """
        XPLMGetPluginInfo(plugin_id)
        Returns (name, signature, description, path).
        Raises RuntimeError if plugin_id is invalid.
        """

        plugin = self.simless_runner.loader.get_plugin(plugin_id)
        if plugin is None:
            raise RuntimeError(f"FakeXP: No plugin with ID {plugin_id}")

        module_path = getattr(plugin.module, "__file__", "<inline>")

        return (
            plugin.name,
            plugin.signature,
            plugin.description,
            module_path,
        )

    def sendMessageToPlugin(self, pluginID: XPLMPluginID, message: int, param: Optional[Any]) -> None:
        plugin = self.simless_runner.loader.get_plugin(pluginID)
        if plugin is None:
            return
        sender = self.getMyID()
        self.simless_runner.dispatch_message_to_plugin(plugin, sender, message, param)
