# Development OTA Widget GUI dataref reader/writer

from __future__ import annotations

from typing import Any, Callable

from XPPython3 import xp
from XPPython3.xp_typing import XPLMFlightLoopID, XPWidgetID


XPWidgetMessageHandler_f = Callable[[int, int, Any, Any], int]


class PythonInterface:
    Name: str
    Sig: str
    Desc: str

    win: XPWidgetID | None
    slider: XPWidgetID | None
    slider_label: XPWidgetID | None
    current_oat_label: XPWidgetID | None
    bus_slider: XPWidgetID | None
    bus_label: XPWidgetID | None
    quit_btn: XPWidgetID | None

    oat_handle: Any | None
    bus_array_handle: Any | None

    _fl_id: XPLMFlightLoopID | None

    # ------------------------------------------------------------------
    def XPluginStart(self):
        self.Name = "OAT GUI"
        self.Sig = "sshd.oat.gui"
        self.Desc = "Development GUI for adjusting Outside Air Temperature"

        self.win = None
        self.slider = None
        self.slider_label = None
        self.current_oat_label = None
        self.bus_slider = None
        self.bus_label = None
        self.quit_btn = None

        self.oat_handle = None
        self.bus_array_handle = None
        self._fl_id = None

        return self.Name, self.Sig, self.Desc

    # ------------------------------------------------------------------
    # UI BUILD
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._create_window()
        self._create_oat_controls()
        self._create_bus_controls()
        if hasattr(xp, "simless_runner"):
            self._create_quit_button()

    def _create_window(self):
        self.win = xp.createWidget(
            100, 500, 650, 240,
            1,
            "Simless OAT Control",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )
        xp.setWidgetProperty(self.win, xp.Property_MainWindowHasCloseBoxes, 1)

        # Window handler only handles close box
        def window_handler(msg, widget, p1, p2):
            if msg == xp.Message_CloseButtonPushed:
                xp.hideWidget(self.win)
                return 1
            return 0

        xp.addWidgetCallback(self.win, window_handler)

    def _create_oat_controls(self):
        xp.createWidget(
            120, 460, 480, 430,
            1,
            "Adjust Outside Air Temperature (°C)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        oat_value = 10
        xp.setDataf(self.oat_handle, oat_value)

        self.slider = xp.createWidget(
            120, 420, 480, 380,
            1,
            "",
            0,
            self.win,
            xp.WidgetClass_ScrollBar,
        )
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarType, xp.ScrollBarTypeSlider)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarMin, -50)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarMax, 50)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarPageAmount, 1)
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarSliderPosition, oat_value)

        self.slider_label = xp.createWidget(
            500, 420, 620, 380,
            1,
            f"{oat_value}°C",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # Child callback for OAT slider
        def oat_slider_handler(msg, widget, p1, p2):
            if msg == xp.Msg_ScrollBarSliderPositionChanged:
                pos = xp.getWidgetProperty(self.slider, xp.Property_ScrollBarSliderPosition)
                temp = int(pos)
                xp.setWidgetDescriptor(self.slider_label, f"{temp}°C")
                xp.showWidget(self.slider_label)

                xp.setDataf(self.oat_handle, float(temp))
                return 1
            return 0

        xp.addWidgetCallback(self.slider, oat_slider_handler)

    def _create_bus_controls(self):
        xp.createWidget(
            120, 360, 480, 330,
            1,
            "Adjust Avionics Bus Voltage (Volts)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        self.bus_slider = xp.createWidget(
            120, 320, 480, 280,
            1,
            "",
            0,
            self.win,
            xp.WidgetClass_ScrollBar,
        )
        xp.setWidgetProperty(self.bus_slider, xp.Property_ScrollBarType, xp.ScrollBarTypeSlider)
        xp.setWidgetProperty(self.bus_slider, xp.Property_ScrollBarMin, 0)
        xp.setWidgetProperty(self.bus_slider, xp.Property_ScrollBarMax, 30)
        xp.setWidgetProperty(self.bus_slider, xp.Property_ScrollBarPageAmount, 1)
        xp.setWidgetProperty(self.bus_slider, xp.Property_ScrollBarSliderPosition, 0)

        self.bus_label = xp.createWidget(
            500, 320, 620, 280,
            1,
            "0 V",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # Child callback for bus slider
        def bus_slider_handler(msg, widget, p1, p2):
            if msg == xp.Msg_ScrollBarSliderPositionChanged:
                pos = xp.getWidgetProperty(self.bus_slider, xp.Property_ScrollBarSliderPosition)
                volts = int(pos)
                xp.setWidgetDescriptor(self.bus_label, f"{volts} V")
                xp.showWidget(self.slider_label)

                xp.setDatavf(self.bus_array_handle, [float(volts)], 1, 1)
                return 1
            return 0

        xp.addWidgetCallback(self.bus_slider, bus_slider_handler)

    def _create_quit_button(self):
        self.quit_btn = xp.createWidget(
            120, 280, 260, 240,
            1,
            "Quit",
            0,
            self.win,
            xp.WidgetClass_Button,
        )
        xp.setWidgetProperty(self.quit_btn, xp.Property_ButtonType, xp.PushButton)

        def quit_handler(msg, widget, p1, p2):
            if msg == xp.Msg_PushButtonPressed:
                xp.destroyWidget(self.win, 1)
                self.win = None
                if hasattr(xp, "simless_runner"):
                    xp.simless_runner.end_run_loop()
                return 1
            return 0

        xp.addWidgetCallback(self.quit_btn, quit_handler)

    # ------------------------------------------------------------------
    # ENABLE
    # ------------------------------------------------------------------
    def XPluginEnable(self):
        self.oat_handle = xp.findDataRef("sim/cockpit2/temperature/outside_air_temp_degc")
        self.bus_array_handle = xp.findDataRef("sim/cockpit2/electrical/bus_volts")

        if not self.oat_handle or not self.bus_array_handle:
            xp.log("[dev_ota_gui] ERROR: Missing required datarefs")
            return 0

        self._build_ui()

        return 1

    # ------------------------------------------------------------------
    def XPluginDisable(self):
        if self.win:
            xp.destroyWidget(self.win, 1)
            self.win = None

        if self._fl_id:
            try:
                xp.destroyFlightLoop(self._fl_id)
            except Exception:
                pass
            self._fl_id = None

    def XPluginStop(self):
        pass
