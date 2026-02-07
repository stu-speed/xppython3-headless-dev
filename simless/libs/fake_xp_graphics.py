# simless/libs/fake_xp_graphics.py

from __future__ import annotations
from typing import Any, Callable, List, Tuple

import dearpygui.dearpygui as dpg


class FakeXPGraphics:
    """
    DearPyGui-backed graphics subsystem mixin for FakeXP.
    Provides a minimal XPLMGraphics-like API surface for simless GUI testing.
    """

    public_api_names = [
        # Drawing callbacks
        "registerDrawCallback",
        "unregisterDrawCallback",

        # Screen + mouse queries
        "getScreenSize",
        "getMouseLocation",

        # Drawing primitives
        "drawString",
        "drawNumber",

        # Graphics state
        "setGraphicsState",
    ]

    def _init_graphics(self) -> None:
        # Draw callbacks: (callback, phase, before)
        self._draw_callbacks: List[tuple[Callable, int, int]] = []

        # Texture bookkeeping (stub)
        self._next_tex_id: int = 1
        self._textures: dict[int, Any] = {}

        # Screen + mouse state
        self._mouse_x: int = 0
        self._mouse_y: int = 0
        self._screen_w: int = 1920
        self._screen_h: int = 1080

        # DearPyGui context is created lazily when GUI is enabled
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

        dpg.create_context()
        dpg.create_viewport(
            title="FakeXP Graphics",
            width=self._screen_w,
            height=self._screen_h,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._dpg_initialized = True

    # ----------------------------------------------------------------------
    # Draw callback registration
    # ----------------------------------------------------------------------
    def registerDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self._draw_callbacks.append((cb, phase, wantsBefore))

    def unregisterDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self._draw_callbacks = [
            entry for entry in self._draw_callbacks
            if not (entry[0] is cb and entry[1] == phase and entry[2] == wantsBefore)
        ]

    # ----------------------------------------------------------------------
    # Text drawing
    # ----------------------------------------------------------------------
    def drawString(
        self,
        color: List[float],
        x: int,
        y: int,
        text: str,
        wordWrapWidth: int,
    ) -> None:
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
            if hasattr(self, "log"):
                self.log(f"[Graphics] drawString error: {exc!r}")

    def drawNumber(
        self,
        color: List[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None:
        fmt = f"{{:{digits}.{decimals}f}}"
        self.drawString(color, x, y, fmt.format(number), 0)

    # ----------------------------------------------------------------------
    # Graphics state (stub)
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
        pass

    # ----------------------------------------------------------------------
    # Texture API (stub)
    # ----------------------------------------------------------------------
    def generateTextureNumbers(self, count: int) -> List[int]:
        ids = []
        for _ in range(count):
            tid = self._next_tex_id
            self._next_tex_id += 1
            self._textures[tid] = None
            ids.append(tid)
        return ids

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        pass

    def deleteTexture(self, textureID: int) -> None:
        self._textures.pop(textureID, None)

    # ----------------------------------------------------------------------
    # Screen + mouse
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
    # Frame rendering
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
                if hasattr(self, "log"):
                    self.log(f"[Graphics] draw callback error: {exc!r}")

        # Render X-Plane-style widgets into DearPyGui, if the widget subsystem is present
        if hasattr(self, "_draw_all_widgets"):
            try:
                self._draw_all_widgets()
            except Exception as exc:
                if hasattr(self, "log"):
                    self.log(f"[Graphics] widget render error: {exc!r}")

        # Render DPG frame
        if self._dpg_initialized:
            try:
                dpg.render_dearpygui_frame()
            except Exception as exc:
                if hasattr(self, "log"):
                    self.log(f"[Graphics] frame render error: {exc!r}")
