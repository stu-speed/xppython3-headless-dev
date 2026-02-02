# plugins/dev_ota_gui.py
#
# Development OTA GUI plugin, written exactly like a production XPPython3 plugin.
# Uses only public xp APIs and follows real X-Plane plugin structure.

from typing import Any
from XPPython3 import xp


class PythonInterface:
    def XPluginStart(self):
        self.Name = "Dev OTA GUI"
        self.Sig = "simless.dev.ota.gui"
        self.Desc = "Development GUI for adjusting Outside Air Temperature"

        # Widget IDs
        self.win = None
        self.slider = None
        self.quit_btn = None

        # Dataref handle
        self.oat_handle = None

        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self):
        xp.log("[dev_ota_gui] Enabling OTA GUI plugin")

        # Resolve OAT dataref (production-style)
        self.oat_handle = xp.findDataRef("sim/cockpit2/temperature/outside_air_temp_degc")
        if self.oat_handle is None:
            xp.log("[dev_ota_gui] ERROR: Missing OAT dataref")
            return 0

        # ---------------- GUI BUILD ----------------
        self.win = xp.createWidget(
            100, 500, 500, 100,
            1,
            "Simless OTA Control",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )

        xp.createWidget(
            120, 460, 480, 430,
            1,
            "Adjust Outside Air Temperature (°C)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        self.slider = xp.createWidget(
            120, 420, 480, 380,
            1,
            "OAT Slider",
            0,
            self.win,
            xp.WidgetClass_ScrollBar,
        )

        xp.setWidgetProperty(self.slider, xp.Property_ScrollMin, -50)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollMax, 50)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollValue, 0)

        self.quit_btn = xp.createWidget(
            120, 340, 260, 300,
            1,
            "Close",
            0,
            self.win,
            xp.WidgetClass_Button,
        )

        # ---------------- Callbacks ----------------
        def slider_callback(wid: int, msg: int, p1: Any, p2: Any):
            if msg != xp.Msg_MouseDrag:
                return
            temp = xp.getWidgetProperty(self.slider, xp.Property_ScrollValue)
            xp.setDataf(self.oat_handle, float(temp))
            xp.log(f"[dev_ota_gui] OAT override → {temp}°C")

        xp.addWidgetCallback(self.slider, slider_callback)

        def quit_callback(wid: int, msg: int, p1: Any, p2: Any):
            if msg == xp.Msg_MouseDown:
                xp.log("[dev_ota_gui] Closing OTA GUI window")
                if self.win is not None:
                    xp.killWidget(self.win)
                    self.win = None

                # Request FakeXP to end the sim loop
                xp._end_run_loop()

        xp.addWidgetCallback(self.quit_btn, quit_callback)

        xp.log("[dev_ota_gui] OTA GUI enabled")
        return 1

    def XPluginDisable(self):
        xp.log("[dev_ota_gui] Disabling OTA GUI")
        if self.win is not None:
            xp.killWidget(self.win)
            self.win = None

    def XPluginStop(self):
        xp.log("[dev_ota_gui] Stopping OTA GUI plugin")
