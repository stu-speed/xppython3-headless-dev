# simless/libs/fake_xp_graphics.py
# ===========================================================================
# FakeXPGraphics — DearPyGui-backed graphics subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLMGraphics-like façade for simless
#   execution. This subsystem mirrors the public xp graphics API surface
#   without inference, layout logic, or hidden state.
#
# CORE INVARIANTS
#   - Must match the production xp.* graphics API contract (xp.pyi).
#   - Must not infer semantics or perform validation.
#   - Must not mutate SDK-shaped objects.
#   - Must return deterministic values based solely on internal storage.
#
# LIFECYCLE INVARIANTS
#   - context_ready gates legality: any dpg.* call requires context_ready.
#   - layout_ready gates correctness: any geometry/layout-dependent operation
#     requires layout_ready (first DPG frame rendered).
#   - Violations raise immediately; nothing fails silently.
#
# SIMLESS RULES
#   - DearPyGui is used only for visualization; never exposed to plugins.
#   - DPG context + viewport + graphics surface are created BEFORE plugin enable.
#   - No automatic layout, no coordinate transforms.
#   - XP draw callbacks are driven by FakeXP, not DPG.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_interface import FakeXPInterface


DPGCallback = Callable[[int | str, Any, Any], Any]


class FakeXPGraphics:
    """DearPyGui-backed graphics subsystem mixin for FakeXP.

    This class owns the DearPyGui lifecycle and exposes:
      - An XPLMGraphics-like API surface (xp.* semantics)
      - A small, explicit set of graphics-owned DearPyGui helpers (dpg_*)

    The design is intentionally strict:
      - Any DPG call before context_ready raises.
      - Any geometry/layout-dependent operation before layout_ready raises.
      - No silent failure paths.
    """

    xp: FakeXPInterface  # established in FakeXP

    _draw_callbacks: List[tuple[Callable[[int, int], Any], int, int]]
    _next_tex_id: int
    _textures: dict[int, Any]
    _context_ready: bool
    _layout_ready: bool
    _drawlist_id: Optional[int]

    public_api_names = [
        # ------------------------------------------------------------------
        # XP Graphics API (XPLM-style semantics)
        # ------------------------------------------------------------------
        "registerDrawCallback",
        "unregisterDrawCallback",
        "getScreenSize",
        "getMouseLocation",
        "drawString",
        "drawNumber",
        "setGraphicsState",
        "bindTexture2d",
        "generateTextureNumbers",
        "deleteTexture",
        # ------------------------------------------------------------------
        # Raw DearPyGui helpers (graphics-owned, explicit)
        # ------------------------------------------------------------------
        "dpg_add_window",
        "dpg_add_child_window",
        "dpg_add_text",
        "dpg_add_input_text",
        "dpg_add_slider_int",
        "dpg_add_button",
        "dpg_configure_item",
        "dpg_set_value",
        "dpg_delete_item",
        "dpg_show_item",
        "dpg_hide_item",
        "dpg_is_item_shown",
    ]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_graphics(self) -> None:
        """Initialize internal graphics state.

        Called by FakeXP during construction.
        """
        # XP draw callbacks: (cb, phase, wantsBefore)
        self._draw_callbacks = []

        # Texture bookkeeping (simless stub)
        self._next_tex_id = 1
        self._textures = {}

        # DPG lifecycle state
        self._context_ready = False
        self._layout_ready = False

        # Viewport-attached drawlist used as the FakeXP "background surface"
        self._drawlist_id = None

    # ----------------------------------------------------------------------
    # LIFECYCLE FLAGS
    # ----------------------------------------------------------------------
    @property
    def context_ready(self) -> bool:
        """Whether the DearPyGui context + viewport are initialized."""
        return self._context_ready

    @property
    def layout_ready(self) -> bool:
        """Whether at least one DPG frame has rendered (layout is valid)."""
        return self._layout_ready

    # ----------------------------------------------------------------------
    # INTERNAL GUARDS
    # ----------------------------------------------------------------------
    def _require_context(self) -> None:
        """Raise if any DPG call is attempted before context initialization."""
        if not self._context_ready:
            raise RuntimeError(
                "DearPyGui context not ready. Call init_graphics_root() before any dpg_* helper or DPG-backed XP API."
            )

    def _require_layout(self) -> None:
        """Raise if geometry/layout-dependent work is attempted too early."""
        if not self._layout_ready:
            raise RuntimeError(
                "DearPyGui layout not ready. Wait until after the first render_dearpygui_frame() before geometry/layout-dependent operations."
            )

    def _require_running(self) -> None:
        """Raise if DPG is no longer running (viewport closed / shutdown)."""
        self._require_context()
        if not dpg.is_dearpygui_running():
            raise RuntimeError("DearPyGui is not running (viewport closed or shutdown).")

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION
    # ----------------------------------------------------------------------
    def init_graphics_root(self) -> None:
        """Initialize DearPyGui and create the viewport-attached graphics root.

        This creates:
          - DPG context
          - DPG viewport
          - A viewport-attached drawlist used as the FakeXP background surface

        Notes:
          - This must run before plugin enable (simless rule).
          - This does not imply layout_ready; layout_ready becomes true only
            after the first rendered frame.
        """
        if self._context_ready:
            return

        dpg.create_context()
        dpg.create_viewport(
            title="Fake X-Plane",
            width=1920,
            height=1080,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()

        # Viewport-attached graphics root (NOT a window)
        self._drawlist_id = dpg.add_viewport_drawlist(front=False)

        self._context_ready = True
        self._layout_ready = False

    # ----------------------------------------------------------------------
    # DPG HELPERS (GRAPHICS-OWNED, FAIL-FAST)
    # ----------------------------------------------------------------------
    def dpg_delete_item(self, item: int | str) -> None:
        # Deletion during shutdown is legal and must be tolerant
        if not self._context_ready:
            return
        if not dpg.is_dearpygui_running():
            return
        dpg.delete_item(item)

    def dpg_add_window(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_window(**kwargs)

    def dpg_add_child_window(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_child_window(**kwargs)

    def dpg_add_text(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_text(**kwargs)

    def dpg_add_input_text(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_input_text(**kwargs)

    def dpg_add_slider_int(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_slider_int(**kwargs)

    def dpg_add_button(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_button(**kwargs)

    def dpg_configure_item(self, item: int | str, **kwargs: Any) -> None:
        self._require_context()
        dpg.configure_item(item, **kwargs)

    def dpg_set_value(self, item: int | str, value: Any, **kwargs: Any) -> None:
        self._require_context()
        dpg.set_value(item, value, **kwargs)

    def dpg_show_item(self, item: int | str) -> None:
        self._require_context()
        dpg.show_item(item)

    def dpg_hide_item(self, item: int | str) -> None:
        self._require_context()
        dpg.hide_item(item)

    def dpg_is_item_shown(self, item: int | str) -> bool:
        self._require_context()
        return dpg.is_item_shown(item)

    # ----------------------------------------------------------------------
    # DRAW CALLBACK REGISTRATION (XP SEMANTICS)
    # ----------------------------------------------------------------------
    def registerDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        self._draw_callbacks.append((cb, phase, wantsBefore))

    def unregisterDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        self._draw_callbacks = [
            entry
            for entry in self._draw_callbacks
            if not (entry[0] is cb and entry[1] == phase and entry[2] == wantsBefore)
        ]

    # ----------------------------------------------------------------------
    # TEXT DRAWING (DPG DRAWLIST)
    # ----------------------------------------------------------------------
    def drawString(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        text: str,
        wordWrap: int,
        fontID: int,
    ) -> None:
        self._require_context()
        if self._drawlist_id is None:
            raise RuntimeError("Graphics drawlist not initialized (init_graphics_root not completed).")

        dpg.draw_text(
            pos=(x, y),
            text=text,
            color=(
                int(color[0] * 255),
                int(color[1] * 255),
                int(color[2] * 255),
                255,
            ),
            parent=self._drawlist_id,
        )

    def drawNumber(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None:
        fmt = f"{{:{digits}.{decimals}f}}"
        self.drawString(color, x, y, fmt.format(number), 0, 0)

    # ----------------------------------------------------------------------
    # GRAPHICS STATE (STUB)
    # ----------------------------------------------------------------------
    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        smooth: int,
        texUnits: int,
        texMode: int,
        depth: int,
    ) -> None:
        return

    # ----------------------------------------------------------------------
    # TEXTURE API (STUB)
    # ----------------------------------------------------------------------
    def generateTextureNumbers(self, count: int) -> List[int]:
        ids: List[int] = []
        for _ in range(count):
            tid = self._next_tex_id
            self._next_tex_id += 1
            self._textures[tid] = None
            ids.append(tid)
        return ids

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        return

    def deleteTexture(self, textureID: int) -> None:
        self._textures.pop(textureID, None)

    # ----------------------------------------------------------------------
    # SCREEN + MOUSE (XP API) — DPG AS SOURCE OF TRUTH
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> Tuple[int, int]:
        self._require_context()
        return dpg.get_viewport_width(), dpg.get_viewport_height()

    def getMouseLocation(self) -> Tuple[int, int]:
        self._require_context()
        x, y = dpg.get_mouse_pos()
        return int(x), int(y)

    # ----------------------------------------------------------------------
    # FRAME RENDERING
    # ----------------------------------------------------------------------
    def draw_frame(self) -> None:
        """Render one simless frame.

        Ordering:
          1) If viewport closed, end run loop.
          2) Execute XP draw callbacks (FakeXP-driven).
          3) Render one DPG frame.
          4) On first rendered frame, set layout_ready and return.
          5) After layout_ready, render widget frame (geometry may apply there).

        Raises:
            RuntimeError: If context is not ready.
        """
        self._require_context()

        # If DPG window closed, end run loop
        if not dpg.is_dearpygui_running():
            self.xp.simless_runner.end_run_loop()
            return

        # Execute draw callbacks (pre-DPG-frame)
        for cb, phase, wantsBefore in list(self._draw_callbacks):
            cb(phase, wantsBefore)

        # Render DPG frame
        dpg.render_dearpygui_frame()

        # First frame establishes layout
        if not self._layout_ready:
            self._layout_ready = True
            return

        # Widget rendering/geometry is only legal after layout_ready
        self.xp.render_widget_frame()
