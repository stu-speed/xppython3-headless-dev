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
        left = 40
        label_right = 400
        window_right = label_right + 20  # 10 px wider than temp display

        top = 700
        bottom = 460

        self.win = xp.createWidget(
            left, top,
            window_right, bottom,
            1,
            "Simless OAT Control",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )

        xp.setWidgetProperty(self.win, xp.Property_MainWindowHasCloseBoxes, 1)

        def window_handler(msg, widget, p1, p2):
            if msg == xp.Message_CloseButtonPushed:
                xp.hideWidget(self.win)
                return 1
            return 0

        xp.addWidgetCallback(self.win, window_handler)

    def _create_oat_controls(self):
        # Caption above OAT slider
        xp.createWidget(
            60, 670,   # left, top
            340, 650,   # right, bottom (20px tall caption)
            1,
            "Adjust Outside Air Temperature (°C)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        oat_value = 10
        xp.setDataf(self.oat_handle, oat_value)

        # OAT slider
        self.slider = xp.createWidget(
            60, 640,   # left, top
            360, 610,   # right, bottom (30px tall slider)
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

        # OAT label to the right of slider
        self.slider_label = xp.createWidget(
            370, 640,   # left, top
            400, 610,   # right, bottom
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
        # Caption above bus slider
        xp.createWidget(
            60, 580,
            360, 560,
            1,
            "Adjust Avionics Bus Voltage (Volts)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # Bus slider
        self.bus_slider = xp.createWidget(
            60, 550,
            360, 520,
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

        # Bus label to the right of slider
        self.bus_label = xp.createWidget(
            370, 550,
            400, 520,
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
                xp.showWidget(self.bus_label)

                xp.setDatavf(self.bus_array_handle, [float(volts)], 1, 1)
                return 1
            return 0

        xp.addWidgetCallback(self.bus_slider, bus_slider_handler)

    def _create_quit_button(self):
        self.quit_btn = xp.createWidget(
            60, 500,
            100, 470,
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
