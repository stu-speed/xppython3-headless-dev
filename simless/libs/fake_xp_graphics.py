# ===========================================================================
# FakeXPGraphics — DearPyGui-backed XPLMGraphics emulator (prod-compatible)
#
# Minimal, safe, simless implementation of the subset of XPLMGraphics used by
# XPPython3 plugins. DearPyGui context/viewport are initialized exactly once
# using the non-deprecated is_* APIs to avoid native crashes.
# ===========================================================================

from __future__ import annotations
from typing import Any, Callable, Dict, List, Tuple

import dearpygui.dearpygui as dpg


class FakeXPGraphics:
    """
    Minimal DearPyGui-backed graphics layer that emulates the subset of
    XPLMGraphics used by XPPython3 plugins. This is NOT a full renderer —
    it only provides the API surface needed for simless GUI plugin testing.
    """

    def __init__(self, fakexp) -> None:
        self.xp = fakexp

        self._draw_callbacks: list[tuple[Callable, int, int]] = []
        self._next_tex_id: int = 1
        self._textures: dict[int, Any] = {}

        self._mouse_x: int = 0
        self._mouse_y: int = 0
        self._screen_w: int = 1920
        self._screen_h: int = 1080

        # Minimal, robust DearPyGui init: assume single graphics instance
        dpg.create_context()
        dpg.create_viewport(
            title="FakeXP Graphics",
            width=self._screen_w,
            height=self._screen_h,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()

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
            self.xp.log(f"[Graphics] drawString error: {exc!r}")

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
        # No-op; included for API compatibility
        pass

    # ----------------------------------------------------------------------
    # Texture API
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
        # No real texture binding — stubbed for compatibility
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
        try:
            if dpg.is_viewport_ok():
                pos = dpg.get_mouse_pos()
                self._mouse_x, self._mouse_y = int(pos[0]), int(pos[1])
        except Exception as exc:
            self.xp.log(f"[Graphics] mouse update error: {exc!r}")

    # ----------------------------------------------------------------------
    # Frame rendering
    # ----------------------------------------------------------------------
    def _draw_frame(self) -> None:
        """
        Called by FakeXPRunner once per frame.
        Executes all registered draw callbacks and renders DearPyGui.
        """
        self._update_mouse()

        # Execute draw callbacks
        for cb, phase, wantsBefore in self._draw_callbacks:
            try:
                cb(phase, wantsBefore)
            except Exception as exc:
                self.xp.log(f"[Graphics] draw callback error: {exc!r}")

        # Render DPG frame
        try:
            dpg.render_dearpygui_frame()
        except Exception as exc:
            self.xp.log(f"[Graphics] frame render error: {exc!r}")
