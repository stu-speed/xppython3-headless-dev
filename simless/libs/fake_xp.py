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

from typing import Optional

from simless.libs.fake_xp_command import FakeXPCommand
from simless.libs.fake_xp_constants import bind_xp_constants
from simless.libs.fake_xp_dataref import FakeXPDataRef
from simless.libs.fake_xp_flightloop import FakeXPFlightLoop
from simless.libs.fake_xp_graphics import FakeXPGraphics
from simless.libs.fake_xp_input import FakeXPInput
from simless.libs.fake_xp_utilities import FakeXPUtilities
from simless.libs.fake_xp_widget import FakeXPWidget
from simless.libs.plugin_runner import SimlessRunner


class FakeXP(
    FakeXPDataRef,
    FakeXPWidget,
    FakeXPGraphics,
    FakeXPFlightLoop,
    FakeXPUtilities,
    FakeXPInput,
    FakeXPCommand,
):
    """
    Unified xp.* façade for simless plugin execution.

    FakeXP mirrors the public API surface of XPPython3's xp.* namespace
    while delegating all simulation behavior to FakeXP subsystems and the
    SimlessRunner. It provides deterministic, headless execution for
    plugin development and testing.
    """

    enable_gui: bool

    enable_dataref_bridge: bool
    bridge_host: str
    bridge_port: int

    simless_runner: SimlessRunner

    _debug: bool
    _sim_time: float

    def __init__(
        self,
        debug: bool = False,
        enable_gui: bool = True,
        enable_dataref_bridge: bool = False,
        bridge_host: Optional[str] = None,
        bridge_port: Optional[int] = None,
    ) -> None:
        """Initialize the FakeXP façade.

        Args:
            debug (bool, optional):
                Enable verbose logging and additional diagnostics useful
                during simless development. Defaults to False.

            enable_gui (bool, optional):
                Enable DearPyGui-backed rendering via FakeXPGraphics.
                When False, all GUI drawing calls become no-ops.
                Defaults to True.

            enable_dataref_bridge (bool, optional):
                Enable the external DataRef bridge used to synchronize
                real X‑Plane DataRefs into the simless environment.
                When True, the SimlessRunner will create and manage an
                XPBridgeClient and forward metadata/value updates into
                the DataRefManager. Defaults to False.

            bridge_host (str, optional):
                Hostname or IP address of the DataRef bridge server.

            bridge_port (int, optional):
                TCP port of the DataRef bridge server.

            run_time (float, optional):
                Maximum wall‑clock duration (in seconds) for the simless
                main loop. A negative value disables the limit and allows
                execution to continue until a plugin calls
                xp.end_run_loop(). Defaults to -1.0.
        """

        self.enable_gui = enable_gui
        self._debug = debug
        self._sim_time = 0.0

        # ------------------------------------------------------------------
        # Initialize subsystems
        # ------------------------------------------------------------------
        self._init_dataref()
        self._init_widgets()
        self._init_graphics()
        self._init_flightloop()
        self._init_utilities()
        self._init_input()
        self._init_command()

        # ------------------------------------------------------------------
        # Bind constants
        # ------------------------------------------------------------------
        bind_xp_constants(self)

        # ------------------------------------------------------------------
        # Bind SimlessRunner
        # ------------------------------------------------------------------
        self.simless_runner = SimlessRunner(self, enable_dataref_bridge, bridge_host, bridge_port)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    def dbg(self, msg: str) -> None:
        if self._debug:
            print(f"[FakeXP] {msg}")

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
        p = self.simless_runner.loader.get_plugin(plugin_id)
        if not p:
            return
        p.enabled = False

    def isPluginEnabled(self, plugin_id: int) -> int:
        """
        XPLMIsPluginEnabled(plugin_id)
        Returns 1 if enabled, 0 if disabled.
        """
        p = self.simless_runner.loader.get_plugin(plugin_id)
        if not p:
            return 0
        return 1 if p.enabled else 0

    def findPluginBySignature(self, signature: str) -> int:
        """
        XPLMFindPluginBySignature(signature)
        Returns plugin ID or -1.
        """
        return self.simless_runner.loader.find_plugin_by_signature(signature)

    def findPluginByPath(self, path: str) -> int:
        """
        XPLMFindPluginByPath(path)
        Returns plugin ID or -1.
        """
        return self.simless_runner.loader.find_plugin_by_path(path)

    def getPluginInfo(self, plugin_id: int) -> tuple[str, str, str, str]:
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
