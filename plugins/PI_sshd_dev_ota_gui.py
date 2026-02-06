# Development OTA GUI plugin, modeled after XplaneNoaaWeather widget patterns.
# Uses only public xp APIs and follows real X-Plane/XPPython3 widget behavior.

from typing import Any
from XPPython3 import xp


class PythonInterface:
    def XPluginStart(self):
        self.Name = "Dev OTA GUI"
        self.Sig = "simless.dev.ota.gui"
        self.Desc = "Development GUI for adjusting Outside Air Temperature"

        # Widget handles
        self.win = None
        self.slider = None
        self.slider_label = None
        self.current_oat_label = None
        self.bus_slider = None
        self.bus_label = None
        self.quit_btn = None

        # Datarefs
        self.oat_handle = None
        self.bus_array_handle = None

        # Callbacks
        self._win_handler_cb = None
        self._fl_id = None

        return self.Name, self.Sig, self.Desc

    # ----------------------------------------------------------------------
    # UI builder (moved out of XPluginEnable)
    # ----------------------------------------------------------------------
    def _build_ui(self):
        # Window
        self.win = xp.createWidget(
            100, 500, 650, 100,
            1,
            "Simless OTA Control",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )
        xp.setWidgetProperty(self.win, xp.Property_MainWindowHasCloseBoxes, 1)

        # --- OAT Caption ---
        xp.createWidget(
            120, 460, 480, 430,
            1,
            "Adjust Outside Air Temperature (°C)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # --- OAT Slider ---
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
        xp.setWidgetProperty(self.slider, xp.Property_ScrollBarSliderPosition, 10)

        # --- OAT Value Label ---
        self.slider_label = xp.createWidget(
            500, 420, 620, 380,
            1,
            "10°C",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # --- Current OAT Display ---
        try:
            current_oat = int(xp.getDataf(self.oat_handle))
        except Exception:
            current_oat = 10

        self.current_oat_label = xp.createWidget(
            120, 390, 480, 360,
            1,
            f"Current OAT: {current_oat}°C",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # --- Bus Volts Caption ---
        xp.createWidget(
            120, 360, 480, 330,
            1,
            "Adjust Avionics Bus Voltage (Volts)",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # --- Bus Volts Slider ---
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

        # --- Bus Volts Value Label ---
        self.bus_label = xp.createWidget(
            500, 320, 620, 280,
            1,
            "0 V",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        # --- Quit Button ---
        self.quit_btn = xp.createWidget(
            120, 240, 260, 200,
            1,
            "Quit",
            0,
            self.win,
            xp.WidgetClass_Button,
        )
        xp.setWidgetProperty(self.quit_btn, xp.Property_ButtonType, xp.PushButton)

    # ----------------------------------------------------------------------
    def XPluginEnable(self):

        # Datarefs
        self.oat_handle = xp.findDataRef("sim/cockpit2/temperature/outside_air_temp_degc")
        self.bus_array_handle = xp.findDataRef("sim/cockpit2/electrical/bus_volts")

        if not self.oat_handle or not self.bus_array_handle:
            xp.log("[dev_ota_gui] ERROR: Missing required datarefs")
            return 0

        # Build UI
        self._build_ui()

        # ---------------- WINDOW HANDLER ----------------
        def window_handler(msg: int, widget: int, param1: Any, param2: Any):

            if msg == xp.Message_CloseButtonPushed and widget == self.win:
                xp.hideWidget(self.win)
                return 1

            if msg == xp.Msg_ScrollBarSliderPositionChanged:

                if param1 == self.slider:
                    temp = xp.getWidgetProperty(self.slider, xp.Property_ScrollBarSliderPosition)
                    xp.setWidgetDescriptor(self.slider_label, f"{temp}°C")
                    xp.setDataf(self.oat_handle, float(temp))

                    # Read back actual sim value
                    try:
                        real_oat = xp.getDataf(self.oat_handle)
                        xp.setWidgetDescriptor(self.current_oat_label, f"Current OAT: {int(real_oat)}°C")
                    except Exception:
                        pass

                    return 1

                if param1 == self.bus_slider:
                    volts = xp.getWidgetProperty(self.bus_slider, xp.Property_ScrollBarSliderPosition)
                    xp.setWidgetDescriptor(self.bus_label, f"{volts} V")
                    xp.setDatavf(self.bus_array_handle, [float(volts)], 1, 1)
                    return 1

            if msg == xp.Msg_PushButtonPressed and param1 == self.quit_btn:
                xp.destroyWidget(self.win, 1)
                self.win = None
                if hasattr(xp, "_quit"):
                    xp._quit()
                return 1

            return 0

        self._win_handler_cb = window_handler
        xp.addWidgetCallback(self.win, self._win_handler_cb)

        # ---------------- FLIGHTLOOP: refresh Current OAT every second ----------------
        def flightloop_cb(elapsed, elapsed2, counter, refcon):
            if self.win and self.current_oat_label and self.oat_handle:
                try:
                    real_oat = xp.getDataf(self.oat_handle)
                    xp.setWidgetDescriptor(self.current_oat_label, f"Current OAT: {int(real_oat)}°C")
                except Exception:
                    pass
            return 1.0  # run again in 1 second

        self._fl_id = xp.createFlightLoop(flightloop_cb)
        xp.scheduleFlightLoop(self._fl_id, 1.0)

        return 1

    # ----------------------------------------------------------------------
    def XPluginDisable(self):
        if self.win:
            xp.destroyWidget(self.win, 1)
            self.win = None

        if self._fl_id is not None:
            try:
                xp.destroyFlightLoop(self._fl_id)
            except Exception:
                pass
            self._fl_id = None

    def XPluginStop(self):
        pass
