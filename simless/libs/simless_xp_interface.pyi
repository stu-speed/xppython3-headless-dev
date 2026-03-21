# simless/libs/simless_xp_interface.pyi
# ===========================================================================
# SimlessXPInterface — typed, minimal API contract for xp.* in simless mode
#
# PURPOSE
#   Defines the subset of xp.* API surface that FakeXP can make available.
#   This Protocol exists solely for strong typing, IDE support, and
#   architectural clarity during simless development.
#
# NOTE (special): Because this runtime is a fake/test harness, the Protocol
#   below also exposes a small set of simless-only helper methods that are
#   implemented by FakeXP. These helpers are intended for test harnesses,
#   runners, and the bridge. Production plugins MUST NOT rely on these
#   helpers; they exist only to make testing and promotion of dummy
#   datarefs straightforward.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable, Sequence, Tuple, Optional

from simless.libs.fake_xp_types import FakeDataRef
from simless.libs.runner import SimlessRunner
from XPPython3.xp_typing import (
    XPDispatchMode,
    XPElementStyle,
    XPLMAudioBus,
    XPLMBankID,
    XPLMCameraControlDuration,
    XPLMCommandPhase,
    XPLMCursorStatus,
    XPLMDataFileType,
    XPLMDataRef,
    XPLMDataRefInfo_t,
    XPLMDataTypeID,
    XPLMDeviceID,
    XPLMDrawingPhase,
    XPLMFlightLoopID,
    XPLMFlightLoopPhaseType,
    XPLMFontID,
    XPLMHostApplicationID,
    XPLMKeyFlags,
    XPLMLanguageCode,
    XPLMMapLayerType,
    XPLMMapOrientation,
    XPLMMapStyle,
    XPLMMenuCheck,
    XPLMMouseStatus,
    XPLMNavFlightPlan,
    XPLMNavType,
    XPLMProbeResult,
    XPLMProbeType,
    XPLMTextureID,
    XPLMWindowDecoration,
    XPLMWindowID,
    XPLMWindowLayer,
    XPLMWindowPositioningMode,
    XPTrackStyle,
    XPWidgetClass,
    XPWidgetID,
    XPWidgetMessage,
    XPWidgetPropertyID,
    XPWindowStyle
)

# ===========================================================================
# DataRef handle / info types
# ===========================================================================
# DataRefHandle and DataRefInfo reflect the production XPLM types OR the
# FakeDataRef handle used by the simless FakeXP implementation.
DataRefHandle = XPLMDataRef | FakeDataRef
DataRefInfo = XPLMDataRefInfo_t | FakeDataRef

# ===========================================================================
# Flight loop callback type (XP11 legacy signature)
# ===========================================================================
FlightLoopCallback = Callable[[float, float, int, Any], float]


# ===========================================================================
# SimlessXPInterface Protocol
# ===========================================================================
@runtime_checkable
class SimlessXPInterface(Protocol):
    debug: bool
    enable_gui: bool

    simless_runner: SimlessRunner

    # Constants
    AircraftCarrier: int
    AudioExteriorAircraft: XPLMAudioBus
    AudioExteriorEnvironment: XPLMAudioBus
    AudioExteriorUnprocessed: XPLMAudioBus
    AudioGround: XPLMAudioBus
    AudioInterior: XPLMAudioBus
    AudioRadioCom1: XPLMAudioBus
    AudioRadioCom2: XPLMAudioBus
    AudioRadioCopilot: XPLMAudioBus
    AudioRadioPilot: XPLMAudioBus
    AudioUI: XPLMAudioBus
    Building: int
    ButtonBehaviorCheckBox: int
    ButtonBehaviorPushButton: int
    ButtonBehaviorRadioButton: int
    CommandBegin: XPLMCommandPhase
    CommandContinue: XPLMCommandPhase
    CommandEnd: XPLMCommandPhase
    ControlCameraForever: XPLMCameraControlDuration
    ControlCameraUntilViewChanges: XPLMCameraControlDuration
    ControlFlag: XPLMKeyFlags
    CoolingTower: int
    CursorArrow: XPLMCursorStatus
    CursorButton: XPLMCursorStatus
    CursorCustom: XPLMCursorStatus
    CursorDefault: XPLMCursorStatus
    CursorDown: XPLMCursorStatus
    CursorFourArrows: XPLMCursorStatus
    CursorHandle: XPLMCursorStatus
    CursorHidden: XPLMCursorStatus
    CursorLeft: XPLMCursorStatus
    CursorLeftRight: XPLMCursorStatus
    CursorRight: XPLMCursorStatus
    CursorRotateLarge: XPLMCursorStatus
    CursorRotateLargeLeft: XPLMCursorStatus
    CursorRotateLargeRight: XPLMCursorStatus
    CursorRotateMedium: XPLMCursorStatus
    CursorRotateMediumLeft: XPLMCursorStatus
    CursorRotateMediumRight: XPLMCursorStatus
    CursorRotateSmall: XPLMCursorStatus
    CursorRotateSmallLeft: XPLMCursorStatus
    CursorRotateSmallRight: XPLMCursorStatus
    CursorSplitterH: XPLMCursorStatus
    CursorSplitterV: XPLMCursorStatus
    CursorText: XPLMCursorStatus
    CursorUp: XPLMCursorStatus
    CursorUpDown: XPLMCursorStatus
    CustomObject: int
    DataFile_ReplayMovie: XPLMDataFileType
    DataFile_Situation: XPLMDataFileType
    DefaultWxrRadiusMslFt: int
    DefaultWxrRadiusNm: int
    Device_CDU739_1: XPLMDeviceID
    Device_CDU739_2: XPLMDeviceID
    Device_CDU815_1: XPLMDeviceID
    Device_CDU815_2: XPLMDeviceID
    Device_G1000_MFD: XPLMDeviceID
    Device_G1000_PFD_1: XPLMDeviceID
    Device_G1000_PFD_2: XPLMDeviceID
    Device_GNS430_1: XPLMDeviceID
    Device_GNS430_2: XPLMDeviceID
    Device_GNS530_1: XPLMDeviceID
    Device_GNS530_2: XPLMDeviceID
    Device_MCDU_1: XPLMDeviceID
    Device_MCDU_2: XPLMDeviceID
    Device_Primus_MFD_1: XPLMDeviceID
    Device_Primus_MFD_2: XPLMDeviceID
    Device_Primus_MFD_3: XPLMDeviceID
    Device_Primus_PFD_1: XPLMDeviceID
    Device_Primus_PFD_2: XPLMDeviceID
    Device_Primus_RMU_1: XPLMDeviceID
    Device_Primus_RMU_2: XPLMDeviceID
    DownFlag: XPLMKeyFlags
    Element_AircraftCarrier: XPElementStyle
    Element_Airport: XPElementStyle
    Element_Building: XPElementStyle
    Element_CheckBox: XPElementStyle
    Element_CheckBoxLit: XPElementStyle
    Element_CoolingTower: XPElementStyle
    Element_CopyButtons: XPElementStyle
    Element_CopyButtonsWithEditingGrid: XPElementStyle
    Element_CustomObject: XPElementStyle
    Element_EditingGrid: XPElementStyle
    Element_Fire: XPElementStyle
    Element_ILSGlideScope: XPElementStyle
    Element_LittleDownArrow: XPElementStyle
    Element_LittleUpArrow: XPElementStyle
    Element_MarkerLeft: XPElementStyle
    Element_MarkerRight: XPElementStyle
    Element_NDB: XPElementStyle
    Element_OilPlatform: XPElementStyle
    Element_OilPlatformSmall: XPElementStyle
    Element_PowerLine: XPElementStyle
    Element_PushButton: XPElementStyle
    Element_PushButtonLit: XPElementStyle
    Element_RadioTower: XPElementStyle
    Element_ScrollBar: XPElementStyle
    Element_Ship: XPElementStyle
    Element_SmokeStack: XPElementStyle
    Element_TextField: XPElementStyle
    Element_TextFieldMiddle: XPElementStyle
    Element_VOR: XPElementStyle
    Element_VORWithCompassRose: XPElementStyle
    Element_Waypoint: XPElementStyle
    Element_WindowCloseBox: XPElementStyle
    Element_WindowCloseBoxPressed: XPElementStyle
    Element_WindowDragBar: XPElementStyle
    Element_WindowDragBarSmooth: XPElementStyle
    Element_Zoomer: XPElementStyle
    FMOD_OK: int
    FMOD_SOUND_FORMAT_PCM16: int
    Fire: int
    FlightLoop_Phase_AfterFlightModel: XPLMFlightLoopPhaseType
    FlightLoop_Phase_BeforeFlightModel: XPLMFlightLoopPhaseType
    Font_Basic: XPLMFontID
    Font_Proportional: XPLMFontID
    Fpl_CoPilot_Approach: XPLMNavFlightPlan
    Fpl_CoPilot_Primary: XPLMNavFlightPlan
    Fpl_CoPilot_Temporary: XPLMNavFlightPlan
    Fpl_Pilot_Approach: XPLMNavFlightPlan
    Fpl_Pilot_Primary: XPLMNavFlightPlan
    Fpl_Pilot_Temporary: XPLMNavFlightPlan
    Host_Unknown: XPLMHostApplicationID
    Host_XPlane: XPLMHostApplicationID
    ILSGlideScope: int
    INTERNALPLUGINSPATH: str
    KEY_0: int
    KEY_1: int
    KEY_2: int
    KEY_3: int
    KEY_4: int
    KEY_5: int
    KEY_6: int
    KEY_7: int
    KEY_8: int
    KEY_9: int
    KEY_DECIMAL: int
    KEY_DELETE: int
    KEY_DOWN: int
    KEY_ESCAPE: int
    KEY_LEFT: int
    KEY_RETURN: int
    KEY_RIGHT: int
    KEY_TAB: int
    KEY_UP: int
    Language_Chinese: XPLMLanguageCode
    Language_English: XPLMLanguageCode
    Language_French: XPLMLanguageCode
    Language_German: XPLMLanguageCode
    Language_Greek: XPLMLanguageCode
    Language_Italian: XPLMLanguageCode
    Language_Japanese: XPLMLanguageCode
    Language_Korean: XPLMLanguageCode
    Language_Russian: XPLMLanguageCode
    Language_Spanish: XPLMLanguageCode
    Language_Ukrainian: XPLMLanguageCode
    Language_Unknown: XPLMLanguageCode
    LittleDownArrow: int
    LittleUpArrow: int
    MAP_IOS: str
    MAP_USER_INTERFACE: str
    MSG_AIRPLANE_COUNT_CHANGED: int
    MSG_AIRPORT_LOADED: int
    MSG_DATAREFS_ADDED: int
    MSG_ENTERED_VR: int
    MSG_EXITING_VR: int
    MSG_FMOD_BANK_LOADED: int
    MSG_FMOD_BANK_UNLOADING: int
    MSG_LIVERY_LOADED: int
    MSG_PLANE_CRASHED: int
    MSG_PLANE_LOADED: int
    MSG_PLANE_UNLOADED: int
    MSG_RELEASE_PLANES: int
    MSG_SCENERY_LOADED: int
    MSG_WILL_WRITE_PREFS: int
    MainWindowStyle_MainWindow: int
    MainWindowStyle_Translucent: int
    MapLayer_Fill: XPLMMapLayerType
    MapLayer_Markings: XPLMMapLayerType
    MapOrientation_Map: XPLMMapOrientation
    MapOrientation_UI: XPLMMapOrientation
    MapStyle_IFR_HighEnroute: XPLMMapStyle
    MapStyle_IFR_LowEnroute: XPLMMapStyle
    MapStyle_VFR_Sectional: XPLMMapStyle
    MarkerLeft: int
    MarkerRight: int
    Master: XPLMAudioBus
    MasterBank: XPLMBankID
    Menu_Checked: XPLMMenuCheck
    Menu_NoCheck: XPLMMenuCheck
    Menu_Unchecked: XPLMMenuCheck
    Message_CloseButtonPushed: int
    Mode_Direct: XPDispatchMode
    Mode_DirectAllCallbacks: XPDispatchMode
    Mode_Once: XPDispatchMode
    Mode_Recursive: XPDispatchMode
    Mode_UpChain: XPDispatchMode
    ModuleMTimes: object
    MouseDown: XPLMMouseStatus
    MouseDrag: XPLMMouseStatus
    MouseUp: XPLMMouseStatus
    MsgAirplaneCountChanged: int
    MsgAirportLoaded: int
    MsgDatarefsAdded: int
    MsgDatarefs_Added: int
    MsgEnteredVr: int
    MsgExitingVr: int
    MsgFmodBankLoaded: int
    MsgFmodBankUnloading: int
    MsgLivery_Loaded: int
    MsgPlaneCrashed: int
    MsgPlaneLoaded: int
    MsgPlaneUnloaded: int
    MsgReleasePlanes: int
    MsgSceneryLoaded: int
    MsgWillWritePrefs: int
    Msg_AcceptChild: XPWidgetMessage
    Msg_AcceptParent: XPWidgetMessage
    Msg_ButtonStateChanged: int
    Msg_Create: XPWidgetMessage
    Msg_CursorAdjust: XPWidgetMessage
    Msg_DescriptorChanged: XPWidgetMessage
    Msg_Destroy: XPWidgetMessage
    Msg_Draw: XPWidgetMessage
    Msg_ExposedChanged: XPWidgetMessage
    Msg_Hidden: XPWidgetMessage
    Msg_KeyLoseFocus: XPWidgetMessage
    Msg_KeyPress: XPWidgetMessage
    Msg_KeyTakeFocus: XPWidgetMessage
    Msg_LoseChild: XPWidgetMessage
    Msg_MouseDown: XPWidgetMessage
    Msg_MouseDrag: XPWidgetMessage
    Msg_MouseUp: XPWidgetMessage
    Msg_MouseWheel: XPWidgetMessage
    Msg_None: XPWidgetMessage
    Msg_Paint: XPWidgetMessage
    Msg_PropertyChanged: XPWidgetMessage
    Msg_PushButtonPressed: XPWidgetMessage
    Msg_Reshape: XPWidgetMessage
    Msg_ScrollBarSliderPositionChanged: XPWidgetMessage
    Msg_Shown: XPWidgetMessage
    Msg_TextFieldChanged: XPWidgetMessage
    Msg_UserStart: XPWidgetMessage
    NAV_NOT_FOUND: int
    NDB: int
    NO_PARENT: int
    NO_PLUGIN_ID: int
    Nav_Airport: XPLMNavType
    Nav_Any: XPLMNavType
    Nav_DME: XPLMNavType
    Nav_Fix: XPLMNavType
    Nav_GlideSlope: XPLMNavType
    Nav_ILS: XPLMNavType
    Nav_InnerMarker: XPLMNavType
    Nav_LatLon: XPLMNavType
    Nav_Localizer: XPLMNavType
    Nav_MiddleMarker: XPLMNavType
    Nav_NDB: XPLMNavType
    Nav_OuterMarker: XPLMNavType
    Nav_TACAN: XPLMNavType
    Nav_Unknown: XPLMNavType
    Nav_VOR: XPLMNavType
    NoFlag: XPLMKeyFlags
    NumCloudLayers: int
    NumTemperatureLayers: int
    NumWindLayers: int
    OilPlatform: int
    OilPlatformSmall: int
    OptionAltFlag: XPLMKeyFlags
    PARAM_PARENT: int
    PLUGINSPATH: str
    PLUGIN_XPLANE: int
    Phase_FirstCockpit: XPLMDrawingPhase
    Phase_Gauges: XPLMDrawingPhase
    Phase_LastCockpit: XPLMDrawingPhase
    Phase_LocalMap2D: XPLMDrawingPhase
    Phase_LocalMap3D: XPLMDrawingPhase
    Phase_LocalMapProfile: XPLMDrawingPhase
    Phase_Modern3D: XPLMDrawingPhase
    Phase_Panel: XPLMDrawingPhase
    Phase_Window: XPLMDrawingPhase
    PowerLine: int
    ProbeError: XPLMProbeResult
    ProbeHitTerrain: XPLMProbeResult
    ProbeMissed: XPLMProbeResult
    ProbeY: XPLMProbeType
    Property_ActiveEditSide: int
    Property_ButtonBehavior: int
    Property_ButtonState: int
    Property_ButtonType: int
    Property_CaptionLit: int
    Property_Clip: XPWidgetPropertyID
    Property_DragXOff: XPWidgetPropertyID
    Property_DragYOff: XPWidgetPropertyID
    Property_Dragging: XPWidgetPropertyID
    Property_EditFieldSelDragStart: int
    Property_EditFieldSelEnd: int
    Property_EditFieldSelStart: int
    Property_Enabled: XPWidgetPropertyID
    Property_Font: int
    Property_GeneralGraphicsType: int
    Property_Hilited: XPWidgetPropertyID
    Property_MainWindowHasCloseBoxes: int
    Property_MainWindowType: int
    Property_MaxCharacters: int
    Property_Object: XPWidgetPropertyID
    Property_PasswordMode: int
    Property_ProgressMax: int
    Property_ProgressMin: int
    Property_ProgressPosition: int
    Property_Refcon: XPWidgetPropertyID
    Property_ScrollBarMax: XPWidgetPropertyID
    Property_ScrollBarMin: XPWidgetPropertyID
    Property_ScrollBarPageAmount: XPWidgetPropertyID
    Property_ScrollBarSliderPosition: XPWidgetPropertyID
    Property_ScrollBarSlop: XPWidgetPropertyID
    Property_ScrollBarType: XPWidgetPropertyID
    Property_ScrollPosition: XPWidgetPropertyID
    Property_SubWindowType: XPWidgetPropertyID
    Property_TextFieldType: XPWidgetPropertyID
    Property_UserStart: XPWidgetPropertyID
    PushButton: int
    RadioBank: XPLMBankID
    RadioButton: int
    RadioTower: int
    ScrollBarTypeScrollBar: int
    ScrollBarTypeSlider: int
    ShiftFlag: XPLMKeyFlags
    Ship: int
    SmokeStack: int
    SubWindowStyle_ListView: int
    SubWindowStyle_Screen: int
    SubWindowStyle_SubWindow: int
    Tex_GeneralInterface: XPLMTextureID
    Tex_Radar_Copilot: XPLMTextureID
    Tex_Radar_Pilot: XPLMTextureID
    TextEntryField: int
    TextTranslucent: int
    TextTransparent: int
    Track_Progress: XPTrackStyle
    Track_ScrollBar: XPTrackStyle
    Track_Slider: XPTrackStyle
    Type_Data: XPLMDataTypeID
    Type_Double: XPLMDataTypeID
    Type_Float: XPLMDataTypeID
    Type_FloatArray: XPLMDataTypeID
    Type_Int: XPLMDataTypeID
    Type_IntArray: XPLMDataTypeID
    Type_Unknown: XPLMDataTypeID
    USER_AIRCRAFT: int
    UpFlag: XPLMKeyFlags
    VERSION: str
    VK_0: int
    VK_1: int
    VK_2: int
    VK_3: int
    VK_4: int
    VK_5: int
    VK_6: int
    VK_7: int
    VK_8: int
    VK_9: int
    VK_A: int
    VK_ADD: int
    VK_B: int
    VK_BACK: int
    VK_BACKQUOTE: int
    VK_BACKSLASH: int
    VK_C: int
    VK_CLEAR: int
    VK_COMMA: int
    VK_D: int
    VK_DECIMAL: int
    VK_DELETE: int
    VK_DIVIDE: int
    VK_DOWN: int
    VK_E: int
    VK_END: int
    VK_ENTER: int
    VK_EQUAL: int
    VK_ESCAPE: int
    VK_EXECUTE: int
    VK_F10: int
    VK_F11: int
    VK_F12: int
    VK_F13: int
    VK_F14: int
    VK_F15: int
    VK_F16: int
    VK_F17: int
    VK_F18: int
    VK_F19: int
    VK_F1: int
    VK_F20: int
    VK_F21: int
    VK_F22: int
    VK_F23: int
    VK_F24: int
    VK_F2: int
    VK_F3: int
    VK_F4: int
    VK_F5: int
    VK_F6: int
    VK_F7: int
    VK_F8: int
    VK_F9: int
    VK_F: int
    VK_G: int
    VK_H: int
    VK_HELP: int
    VK_HOME: int
    VK_I: int
    VK_INSERT: int
    VK_J: int
    VK_K: int
    VK_L: int
    VK_LBRACE: int
    VK_LEFT: int
    VK_M: int
    VK_MINUS: int
    VK_MULTIPLY: int
    VK_N: int
    VK_NEXT: int
    VK_NUMPAD0: int
    VK_NUMPAD1: int
    VK_NUMPAD2: int
    VK_NUMPAD3: int
    VK_NUMPAD4: int
    VK_NUMPAD5: int
    VK_NUMPAD6: int
    VK_NUMPAD7: int
    VK_NUMPAD8: int
    VK_NUMPAD9: int
    VK_NUMPAD_ENT: int
    VK_NUMPAD_EQ: int
    VK_O: int
    VK_P: int
    VK_PERIOD: int
    VK_PRINT: int
    VK_PRIOR: int
    VK_Q: int
    VK_QUOTE: int
    VK_R: int
    VK_RBRACE: int
    VK_RETURN: int
    VK_RIGHT: int
    VK_S: int
    VK_SELECT: int
    VK_SEMICOLON: int
    VK_SEPARATOR: int
    VK_SLASH: int
    VK_SNAPSHOT: int
    VK_SPACE: int
    VK_SUBTRACT: int
    VK_T: int
    VK_TAB: int
    VK_U: int
    VK_UP: int
    VK_V: int
    VK_W: int
    VK_X: int
    VK_Y: int
    VK_Z: int
    VOR: int
    VORWithCompassRose: int
    WayPoint: int
    WidgetClass_Button: XPWidgetClass
    WidgetClass_Caption: XPWidgetClass
    WidgetClass_GeneralGraphics: XPWidgetClass
    WidgetClass_MainWindow: XPWidgetClass
    WidgetClass_None: int
    WidgetClass_Progress: XPWidgetClass
    WidgetClass_ScrollBar: XPWidgetClass
    WidgetClass_SubWindow: XPWidgetClass
    WidgetClass_TextField: XPWidgetClass
    WindUndefinedLayer: int
    WindowCenterOnMonitor: XPLMWindowPositioningMode
    WindowCloseBox: int
    WindowDecorationNone: XPLMWindowDecoration
    WindowDecorationRoundRectangle: XPLMWindowDecoration
    WindowDecorationSelfDecorated: XPLMWindowDecoration
    WindowDecorationSelfDecoratedResizable: XPLMWindowDecoration
    WindowFullScreenOnAllMonitors: XPLMWindowPositioningMode
    WindowFullScreenOnMonitor: XPLMWindowPositioningMode
    WindowLayerFlightOverlay: XPLMWindowLayer
    WindowLayerFloatingWindows: XPLMWindowLayer
    WindowLayerGrowlNotifications: XPLMWindowLayer
    WindowLayerModal: XPLMWindowLayer
    WindowPopOut: XPLMWindowPositioningMode
    WindowPositionFree: XPLMWindowPositioningMode
    WindowVR: XPLMWindowPositioningMode
    Window_Help: XPWindowStyle
    Window_ListView: XPWindowStyle
    Window_MainWindow: XPWindowStyle
    Window_Screen: XPWindowStyle
    Window_SubWindow: XPWindowStyle
    _Airport: int
    kVersion: int
    kXPLM_Version: int
    pythonDebugLevel: int
    pythonExecutable: str

    # ------------------------------------------------------------------
    # Logging / lifecycle
    # ------------------------------------------------------------------
    def log(self, msg: str) -> None: ...

    def getMyID(self) -> int: ...

    def disablePlugin(self, plugin_id: int) -> None: ...

    # ------------------------------------------------------------------
    # Time / processing
    # ------------------------------------------------------------------
    def getElapsedTime(self) -> float: ...

    # ------------------------------------------------------------------
    # DataRef API (real XPPython3 contract)
    # ------------------------------------------------------------------
    # NOTE: Signatures mirror production: findDataRef accepts a string and
    # returns an opaque handle; all other accessors accept the handle only.
    def findDataRef(self, name: str) -> DataRefHandle | None: ...

    def getDataRefInfo(self, handle: DataRefHandle) -> DataRefInfo | None: ...

    # Scalar get/set
    def getDatai(self, handle: DataRefHandle) -> int: ...

    def setDatai(self, handle: DataRefHandle, value: int) -> None: ...

    def getDataf(self, handle: DataRefHandle) -> float: ...

    def setDataf(self, handle: DataRefHandle, value: float) -> None: ...

    def getDatad(self, handle: DataRefHandle) -> float: ...

    def setDatad(self, handle: DataRefHandle, value: float) -> None: ...

    # Array get/set
    def getDatavf(
        self,
        handle: DataRefHandle,
        out: Sequence[float] | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatavf(
        self,
        handle: DataRefHandle,
        values: Sequence[float],
        offset: int,
        count: int,
    ) -> None: ...

    def getDatavi(
        self,
        handle: DataRefHandle,
        out: Sequence[int] | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatavi(
        self,
        handle: DataRefHandle,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None: ...

    def getDatab(
        self,
        handle: DataRefHandle,
        out: bytearray | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatab(
        self,
        handle: DataRefHandle,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Flight loops (XP11 legacy signature)
    # ------------------------------------------------------------------
    def createFlightLoop(
        self,
        callback: FlightLoopCallback
                  | tuple[int, FlightLoopCallback, Any]
                  | list[Any],
        phase: XPLMFlightLoopPhaseType = XPLMFlightLoopPhaseType(0),
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID: ...

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval: float,
        relativeToNow: int = 1,
    ) -> None: ...

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None: ...

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    def createWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        container: XPWidgetID,
        widget_class: XPWidgetClass,
    ) -> XPWidgetID: ...

    def destroyWidget(self, wid: XPWidgetID, destroy_children: int = 1) -> None: ...

    def setWidgetGeometry(
        self,
        wid: XPWidgetID,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None: ...

    def getWidgetGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]: ...

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]: ...

    def showWidget(self, wid: XPWidgetID) -> None: ...

    def hideWidget(self, wid: XPWidgetID) -> None: ...

    def isWidgetVisible(self, wid: XPWidgetID) -> bool: ...

    def isWidgetInFront(self, wid: XPWidgetID) -> bool: ...

    def bringWidgetToFront(self, wid: XPWidgetID) -> None: ...

    def pushWidgetBehind(self, wid: XPWidgetID) -> None: ...

    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID | None: ...

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass: ...

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> XPLMWindowID | None: ...

    def setWidgetDescriptor(self, wid: XPWidgetID, desc: str) -> None: ...

    def getWidgetDescriptor(self, wid: XPWidgetID) -> str: ...

    def getWidgetForLocation(
        self,
        x: int,
        y: int,
        in_front: int,
    ) -> XPWidgetID | None: ...

    def setKeyboardFocus(self, wid: XPWidgetID | None) -> None: ...

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None: ...

    def setWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
        value: Any,
    ) -> None: ...

    def getWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
    ) -> Any: ...

    def addWidgetCallback(
        self,
        wid: XPWidgetID,
        callback: Callable[[XPWidgetMessage, XPWidgetID, Any, Any], Any],
    ) -> None: ...

    def sendWidgetMessage(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any | None = None,
        param2: Any | None = None,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Graphics
    # ------------------------------------------------------------------
    def createWindowEx(
        self,
        left: int = 100,
        top: int = 200,
        right: int = 200,
        bottom: int = 100,
        visible: int = 0,
        draw: Optional[Callable[[XPLMWindowID, Any], None]] = None,
        click: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ] = None,
        key: Optional[
            Callable[[XPLMWindowID, int, int, int, Any, int], int]
        ] = None,
        cursor: Optional[
            Callable[[XPLMWindowID, int, int, Any], XPLMCursorStatus]
        ] = None,
        wheel: Optional[
            Callable[[XPLMWindowID, int, int, int, int, Any], int]
        ] = None,
        refCon: Any = None,
        decoration: XPLMWindowDecoration = None,
        layer: XPLMWindowLayer = None,
        rightClick: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ] = None,
    ) -> XPLMWindowID: ...

    def destroyWindow(self, wid: XPLMWindowID) -> None: ...

    def getWindowGeometry(self, wid: XPLMWindowID) -> Tuple[int, int, int, int]: ...

    def setWindowGeometry(
        self,
        windowID: XPLMWindowID,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None: ...

    def getWindowRefCon(self, windowID: XPLMWindowID): ...

    def setWindowRefCon(self, windowID: XPLMWindowID, refCon) -> None: ...

    def takeKeyboardFocus(self, windowID: XPLMWindowID) -> None: ...

    def setWindowIsVisible(self, windowID: XPLMWindowID, visible: int) -> None: ...

    def getWindowIsVisible(self, windowID: XPLMWindowID) -> int: ...

    def registerDrawCallback(
        self,
        callback: Callable[[XPLMDrawingPhase, int, Any], int],
        phase: XPLMDrawingPhase,
        wantsBefore: int,
    ) -> None: ...

    def unregisterDrawCallback(
        self,
        callback: Callable[[XPLMDrawingPhase, int, Any], int],
        phase: XPLMDrawingPhase,
        wantsBefore: int,
    ) -> None: ...

    def drawString(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        text: str,
        wordWrapWidth: int,
    ) -> None: ...

    def drawNumber(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None: ...

    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        smooth: int,
        texUnits: int,
        texMode: int,
        depth: int,
    ) -> None: ...

    def bindTexture2d(self, textureID: XPLMTextureID, unit: int) -> None: ...

    def generateTextureNumbers(self, count: int) -> list[XPLMTextureID]: ...

    def deleteTexture(self, textureID: XPLMTextureID) -> None: ...

    def drawTranslucentDarkBox(self, left: int, top: int, right: int, bottom: int) -> None: ...

    # ------------------------------------------------------------------
    # Screen / mouse
    # ------------------------------------------------------------------
    def getScreenSize(self) -> tuple[int, int]: ...

    def getMouseLocation(self) -> tuple[int, int]: ...

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str: ...

    def getPrefsPath(self) -> str: ...

    def getDirectorySeparator(self) -> str: ...
