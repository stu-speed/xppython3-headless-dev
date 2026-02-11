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
#   - DPG context is initialized lazily and exactly once.
#   - No automatic layout, no coordinate transforms.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, List, Tuple

import dearpygui.dearpygui as dpg
import XPPython3


class FakeXPGraphics:
    """
    DearPyGui-backed graphics subsystem mixin for FakeXP.
    Provides a minimal XPLMGraphics-like API surface for simless GUI testing.
    """

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
    ]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_graphics(self) -> None:
        """
        Initialize internal graphics state.
        Called by FakeXP during construction.
        """
        # Draw callbacks: (callback, phase, wantsBefore)
        self._draw_callbacks: List[tuple[Callable, int, int]] = []

        # Texture bookkeeping (simless stub)
        self._next_tex_id: int = 1
        self._textures: dict[int, Any] = {}

        # Screen + mouse state (static unless overridden)
        self._mouse_x: int = 0
        self._mouse_y: int = 0
        self._screen_w: int = 1920
        self._screen_h: int = 1080

        # DearPyGui context is created lazily
        self._dpg_initialized: bool = False

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION
    # ----------------------------------------------------------------------
    def _ensure_dpg(self) -> None:
        """
        Initialize DearPyGui exactly once.
        Called automatically when GUI mode is enabled.
        """
        if self._dpg_initialized:
            return

        try:
            dpg.create_context()
            dpg.create_viewport(
                title="FakeXP Graphics",
                width=self._screen_w,
                height=self._screen_h,
            )
            dpg.setup_dearpygui()
            dpg.show_viewport()
            self._dpg_initialized = True
        except Exception as exc:
            XPPython3.xp.log(f"[Graphics] DPG init error: {exc!r}")

    # ----------------------------------------------------------------------
    # DRAW CALLBACK REGISTRATION
    # ----------------------------------------------------------------------
    def registerDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        """
        Register a draw callback.
        FakeXP calls these once per frame in _draw_frame().
        """
        self._draw_callbacks.append((cb, phase, wantsBefore))

    def unregisterDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        """
        Remove a previously registered draw callback.
        """
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
        color: List[float],
        x: int,
        y: int,
        text: str,
        wordWrapWidth: int,
    ) -> None:
        """
        Draw a string at (x, y) using DearPyGui.
        wordWrapWidth is ignored (simless stub).
        """
        if not self._dpg_initialized:
            return

        try:
            with dpg.draw_layer():
                dpg.draw_text(
                    pos=(x, y),
                    text=text,
                    color=(
                        int(color[0] * 255),
                        int(color[1] * 255),
                        int(color[2] * 255),
                        255,
                    ),
                )
        except Exception as exc:
            XPPython3.xp.log(f"[Graphics] drawString error: {exc!r}")

    def drawNumber(
        self,
        color: List[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None:
        """
        Draw a formatted number using drawString().
        """
        fmt = f"{{:{digits}.{decimals}f}}"
        self.drawString(color, x, y, fmt.format(number), 0)

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
        """
        Stub: X-Plane graphics state flags are ignored in simless mode.
        """
        return

    # ----------------------------------------------------------------------
    # TEXTURE API (STUB)
    # ----------------------------------------------------------------------
    def generateTextureNumbers(self, count: int) -> List[int]:
        """
        Allocate texture IDs (simless stub).
        """
        ids: List[int] = []
        for _ in range(count):
            tid = self._next_tex_id
            self._next_tex_id += 1
            self._textures[tid] = None
            ids.append(tid)
        return ids

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        """
        Stub: No real texture binding in simless mode.
        """
        return

    def deleteTexture(self, textureID: int) -> None:
        """
        Remove a texture ID from bookkeeping.
        """
        self._textures.pop(textureID, None)

    # ----------------------------------------------------------------------
    # SCREEN + MOUSE
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> Tuple[int, int]:
        return (self._screen_w, self._screen_h)

    def getMouseLocation(self) -> Tuple[int, int]:
        return (self._mouse_x, self._mouse_y)

    def _update_mouse(self) -> None:
        """
        Update mouse position from DearPyGui.
        """
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
    def _draw_frame(self) -> None:
        """
        Called by SimlessRunner once per frame.
        Executes draw callbacks, renders widgets, and renders DearPyGui.
        """
        if getattr(self, "enable_gui", False):
            self._ensure_dpg()

        self._update_mouse()

        # Execute draw callbacks
        for cb, phase, wantsBefore in list(self._draw_callbacks):
            try:
                cb(phase, wantsBefore)
            except Exception as exc:
                XPPython3.xp.log(f"[Graphics] draw callback error: {exc!r}")

        # Render widgets if widget subsystem is present
        if hasattr(self, "_draw_all_widgets"):
            try:
                self._draw_all_widgets()
            except Exception as exc:
                XPPython3.xp.log(f"[Graphics] widget render error: {exc!r}")

        # Render DPG frame
        if self._dpg_initialized:
            try:
                dpg.render_dearpygui_frame()
            except Exception as exc:
                XPPython3.xp.log(f"[Graphics] frame render error: {exc!r}")
