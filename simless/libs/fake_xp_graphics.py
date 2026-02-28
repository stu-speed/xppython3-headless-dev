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
# SIMLESS RULES
#   - DearPyGui is used only for visualization; never exposed to plugins.
#   - DPG context + viewport + graphics surface are created BEFORE plugin enable.
#   - No automatic layout, no coordinate transforms.
#   - Background FakeXP Graphics Surface supports XPLMGraphics emulation.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_interface import FakeXPInterface


class FakeXPGraphics:
    """
    DearPyGui-backed graphics subsystem mixin for FakeXP.
    Provides a minimal XPLMGraphics-like API surface for simless GUI testing.
    """
    xp: FakeXPInterface  # established in FakeXP

    public_api_names = [
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
        "draw_frame"
    ]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_graphics(self) -> None:
        """
        Initialize internal graphics state.
        Called by FakeXP during construction.
        """
        self._draw_callbacks: List[tuple[Callable[[int, int], Any], int, int]] = []

        # Texture bookkeeping (simless stub)
        self._next_tex_id: int = 1
        self._textures: dict[int, Any] = {}

        # Screen + mouse state
        self._mouse_x: int = 0
        self._mouse_y: int = 0
        self._screen_w: int = 1920
        self._screen_h: int = 1080

        # DearPyGui state
        self._dpg_initialized: bool = False
        self._graphics_window: Optional[int] = None
        self._drawlist_id: Optional[int] = None

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION (PRODUCTION-PARITY)
    # ----------------------------------------------------------------------
    def init_graphics_root(self) -> None:
        """
        Initialize DearPyGui context, viewport, and root graphics surface
        BEFORE any plugin enable. This matches production X-Plane behavior:
        the widget system is fully ready before plugins run.
        """
        if self._dpg_initialized:
            return

        try:
            # Create DPG context + viewport
            dpg.create_context()
            dpg.create_viewport(
                title="Fake X-Plane",
                width=self._screen_w,
                height=self._screen_h,
            )
            dpg.setup_dearpygui()
            dpg.show_viewport()

            # Root window at top level
            with dpg.window(
                label="##gfx_root",
                pos=(0, 0),
                width=self._screen_w,
                height=self._screen_h,
                no_title_bar=True,
                no_resize=True,
                no_move=True,
                no_scrollbar=True,
                no_collapse=True,
            ) as root:
                self._graphics_window = root

                # Drawlist inside the root window
                self._drawlist_id = dpg.add_drawlist(
                    parent=self._graphics_window,
                    width=self._screen_w,
                    height=self._screen_h,
                )

            dpg.set_primary_window(self._graphics_window, True)
            self._dpg_initialized = True

        except Exception as exc:
            self.xp.log(f"[Graphics] DPG init error: {exc!r}")

    # ----------------------------------------------------------------------
    # DRAW CALLBACK REGISTRATION
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
    # TEXT DRAWING
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
        if not self._dpg_initialized or self._drawlist_id is None:
            return

        try:
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
        except Exception as exc:
            self.xp.log(f"[Graphics] drawString error: {exc!r}")

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
    # SCREEN + MOUSE
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> Tuple[int, int]:
        return (self._screen_w, self._screen_h)

    def getMouseLocation(self) -> Tuple[int, int]:
        return (self._mouse_x, self._mouse_y)

    def _update_mouse(self) -> None:
        if not self._dpg_initialized:
            return
        try:
            pos = dpg.get_mouse_pos()
            self._mouse_x, self._mouse_y = int(pos[0]), int(pos[1])
        except Exception:
            pass

    # ----------------------------------------------------------------------
    # FRAME RENDERING
    # ----------------------------------------------------------------------
    def draw_frame(self) -> None:
        """
        Called by SimlessRunner once per frame.
        Executes draw callbacks, renders widgets, and renders DearPyGui.
        """
        if self._dpg_initialized and not dpg.is_dearpygui_running():
            self.xp.simless_runner.end_run_loop()
            return

        self._update_mouse()

        # Execute draw callbacks
        for cb, phase, wantsBefore in list(self._draw_callbacks):
            try:
                cb(phase, wantsBefore)
            except Exception as exc:
                self.xp.log(f"[Graphics] draw callback error: {exc!r}")

        # Render DPG frame FIRST (establishes valid item state/layout)
        if self._dpg_initialized:
            try:
                dpg.render_dearpygui_frame()
            except Exception as exc:
                self.xp.log(f"[Graphics] frame render error: {exc!r}")
                return

        # Mark widget layout ready AFTER first successful frame
        if hasattr(self, "_layout_ready") and not getattr(self, "_layout_ready"):
            self._layout_ready = True

        # Render widgets (safe now)
        if hasattr(self, "_draw_all_widgets"):
            try:
                self._draw_all_widgets()
            except Exception as exc:
                self.xp.log(f"[Graphics] widget render error: {exc!r}")
