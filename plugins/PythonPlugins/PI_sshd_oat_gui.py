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

    # Menu fields
    menu_id: int | None
    menu_item_index: int | None
    _window_visible: bool

    # ------------------------------------------------------------------
    def XPluginStart(self):
        self.Name = "OAT GUI"
        self.Sig = "sshd.oat.gui"
        self.Desc = "Development GUI for adjusting Outside Air Temperature"

        # UI state
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

        # Start visible
        self._window_visible = True

        # --------------------------------------------------------------
        # Create plugin menu under Plugins root
        # --------------------------------------------------------------
        self.menu_id = xp.createMenu(
            name="OAT GUI",
            parentMenuID=None,     # attaches to Plugins menu
            parentItem=0,
            handler=self._menu_handler,
            refCon=None,
        )

        self.menu_item_index = xp.appendMenuItem(
            self.menu_id,
            "Hide Window",
            refCon=None,
        )

        return self.Name, self.Sig, self.Desc

    # ------------------------------------------------------------------
    # MENU HANDLER
    # ------------------------------------------------------------------
    def _menu_handler(self, menu_refcon: Any, item_refcon: Any) -> None:
        """Strongly-typed XP menu handler: (refCon, itemRefCon) -> None."""
        self._window_visible = not self._window_visible

        if self._window_visible:
            xp.showWidget(self.win)
            xp.setMenuItemName(self.menu_id, self.menu_item_index, "Hide Window")
        else:
            xp.hideWidget(self.win)
            xp.setMenuItemName(self.menu_id, self.menu_item_index, "Show Window")

    # ------------------------------------------------------------------
    # UI BUILD
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._create_window()
        self._create_oat_controls()
        self._create_bus_controls()

    def _create_window(self):
        left = 40
        label_right = 400
        window_right = label_right + 20

        top = 700
        bottom = 500

        self.win = xp.createWidget(
            left, top,
            window_right, bottom,
            1,
            "Simless OAT Control",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )

    def _create_oat_controls(self):
        xp.createWidget(
            60, 670,
            340, 650,
            1,
            "Adjust Outside Air Temperature (°C)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        oat_value = 10
        xp.setDataf(self.oat_handle, oat_value)

        self.slider = xp.createWidget(
            60, 640,
            360, 610,
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
            370, 640,
            400, 610,
            1,
            f"{oat_value}°C",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

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
            60, 580,
            360, 560,
            1,
            "Adjust Avionics Bus Voltage (Volts)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

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

        self.bus_label = xp.createWidget(
            370, 550,
            400, 520,
            1,
            "0 V",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

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

        # ⭐ Start visible
        xp.showWidget(self.win)
        self._window_visible = True
        xp.setMenuItemName(self.menu_id, self.menu_item_index, "Hide Window")

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
