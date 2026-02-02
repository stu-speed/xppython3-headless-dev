from __future__ import annotations
from typing import Callable, List
import time

import dearpygui.dearpygui as dpg


class FakeXPGraphics:
    """
    Dear PyGui–backed graphics facade for FakeXP.

    Responsibilities:
      • Maintain a persistent overlay for draw calls
      • Provide simple text/number drawing
      • Provide optional debug HUD (FPS, draw calls, callback count)
      • Execute plugin draw callbacks each frame
      • Integrate with FakeXP debug logging

    NOTE:
      This class assumes DearPyGui context + viewport are already
      created and running by the harness (e.g. run_ota_gui.py).
      It does NOT touch DPG lifecycle at all.
    """

    def __init__(self, fakexp) -> None:
        self.xp = fakexp

        # Draw callbacks
        self._draw_callbacks: List[Callable[[], None]] = []

        # Overlay window
        self._overlay: int | None = None
        self._overlay_created: bool = False

        # Debug HUD state
        self._debug_enabled: bool = False
        self._last_frame_time: float = time.time()
        self._fps: float = 0.0
        self._draw_count: int = 0

    # ======================================================================
    # Public API
    # ======================================================================
    def enableDebug(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self.xp._dbg(f"[Graphics] Debug HUD {'enabled' if enabled else 'disabled'}")

    def registerDrawCallback(self, callback: Callable[[], None]) -> None:
        self._draw_callbacks.append(callback)
        self.xp._dbg(f"[Graphics] Registered draw callback: {callback}")

    def run_draw_callbacks(self) -> None:
        """Run all draw callbacks once per frame."""
        self._update_fps()
        self._ensure_overlay()

        # Clear overlay contents
        if self._overlay_created and dpg.does_item_exist(self._overlay):
            dpg.delete_item(self._overlay, children_only=True)

        self._draw_count = 0

        # Execute plugin draw callbacks
        for cb in list(self._draw_callbacks):
            try:
                self.xp._dbg(f"[Graphics] Running draw callback: {cb}")
                cb()
            except Exception as e:
                self.xp._dbg(f"[Graphics] Draw callback error: {e!r}")

        # Draw debug HUD
        if self._debug_enabled:
            self._draw_debug_hud()

    # ======================================================================
    # Drawing primitives
    # ======================================================================
    def drawString(self, x: int, y: int, text: str) -> None:
        self._ensure_overlay()
        self._draw_count += 1
        self.xp._dbg(f"[Graphics] drawString: '{text}' at ({x}, {y})")
        dpg.draw_text(pos=(x, y), text=text, parent=self._overlay)

    def drawNumber(self, x: int, y: int, number: float) -> None:
        self.drawString(x, y, f"{number}")

    def drawLine(self, x1: int, y1: int, x2: int, y2: int, color=(255, 255, 255, 255)) -> None:
        self._ensure_overlay()
        self._draw_count += 1
        dpg.draw_line((x1, y1), (x2, y2), color=color, parent=self._overlay)

    def drawRect(self, x: int, y: int, w: int, h: int, color=(255, 255, 255, 255)) -> None:
        self._ensure_overlay()
        self._draw_count += 1
        dpg.draw_rectangle((x, y), (x + w, y + h), color=color, parent=self._overlay)

    def drawCircle(self, x: int, y: int, radius: int, color=(255, 255, 255, 255)) -> None:
        self._ensure_overlay()
        self._draw_count += 1
        dpg.draw_circle((x, y), radius, color=color, parent=self._overlay)

    # ======================================================================
    # Private helpers
    # ======================================================================
    def _ensure_overlay(self) -> None:
        """Create the persistent overlay window once."""
        if self._overlay_created and dpg.does_item_exist(self._overlay):
            return

        self.xp._dbg("[Graphics] Creating overlay window")

        with dpg.window(
            label="FakeXP Draw Overlay",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_close=True,
            no_background=True,
            pos=(0, 0),
        ) as overlay:
            self._overlay = overlay

        self._overlay_created = True
        self.xp._dbg("[Graphics] Overlay created")

    def _update_fps(self) -> None:
        now = time.time()
        dt = now - self._last_frame_time
        self._last_frame_time = now

        if dt > 0:
            self._fps = 1.0 / dt

        if self._debug_enabled:
            self.xp._dbg(f"[Graphics] Updated FPS: {self._fps:.2f}")

    def _draw_debug_hud(self) -> None:
        self._ensure_overlay()

        lines = [
            f"FPS: {self._fps:6.2f}",
            f"Draw calls: {self._draw_count}",
            f"Callbacks: {len(self._draw_callbacks)}",
        ]

        y = 10
        for line in lines:
            dpg.draw_text(
                pos=(10, y),
                text=line,
                color=(255, 255, 0, 255),
                parent=self._overlay,
            )
            y += 18

        self.xp._dbg("[Graphics] Debug HUD drawn")
