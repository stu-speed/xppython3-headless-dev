# ===========================================================================
# FakeXP Constants — X‑Plane / XPPython3 constant names for simless execution
#
# ROLE
#   Provide a flat namespace of SDK-shaped constant names expected by plugins.
#   These constants mirror the identifiers defined by X‑Plane and
#   XPPython3, but the numeric values here are PLAUSIBLE PLACEHOLDERS
#   suitable only for simless execution.
#
# DESIGN PRINCIPLES
#   - Names must match the real SDK exactly (pyi).
#   - Values are not authoritative; they exist only to satisfy plugin
#     imports, comparisons, and switch logic during simless runs.
#   - No classes, enums, or grouping structures — a flat module keeps
#     imports simple and mirrors the real * surface.
#
# USAGE
#   - FakeXP bulk‑binds these names into the * namespace at startup.
#   - Plugins see CONSTANT_NAME exactly as they would in X‑Plane.
#   - Contributors may add new constants by defining additional module‑
#     level names; no registration or binding code is required.
#
# NOTE
#   This file is generated/maintained for compatibility only. The values
#   do not correspond to real X‑Plane SDK numeric assignments and must
#   never be used for real‑sim behavior or validation.
# ===========================================================================

from __future__ import annotations


def bind_xp_constants(xp) -> None:
    """
    Bind all module-level constants into the xp namespace.
    """
    for name, val in globals().items():
        setattr(xp, name, val)

def lookup_constant_name(value: int, prefix: str) -> str:
    """
    Generic reverse lookup for any constant defined in this module.
    Example:
        lookup_constant_name(3005, "WidgetClass_") -> "Caption"
        lookup_constant_name(9010, "VK_") -> "A"
    """
    for name, val in globals().items():
        if name.startswith(prefix) and val == value:
            return name.replace(prefix, "")
    return f"Unknown({value})"


# Data type bitmask
Type_Int = 1 << 0  # 1
Type_Float = 1 << 1  # 2
Type_Double = 1 << 2  # 4
Type_FloatArray = 1 << 3  # 8
Type_IntArray = 1 << 4  # 16
Type_Data = 1 << 5  # 32
Type_Unknown = 0

# ----------------------------------------------------------------------
# AUDIO (1000–1999)
# ----------------------------------------------------------------------
AudioExteriorAircraft = 1000
AudioExteriorEnvironment = 1001
AudioExteriorUnprocessed = 1002
AudioGround = 1003
AudioInterior = 1004
AudioRadioCom1 = 1005
AudioRadioCom2 = 1006
AudioRadioCopilot = 1007
AudioRadioPilot = 1008
AudioUI = 1009
Master = 1010
MasterBank = 1011
RadioBank = 1012
FMOD_OK = 1013
FMOD_SOUND_FORMAT_PCM16 = 1014

# ----------------------------------------------------------------------
# COMMAND PHASES (2000–2099)
# ----------------------------------------------------------------------
CommandBegin = 2000
CommandContinue = 2001
CommandEnd = 2002

# ----------------------------------------------------------------------
# CAMERA CONTROL (2100–2199)
# ----------------------------------------------------------------------
ControlCameraForever = 2100
ControlCameraUntilViewChanges = 2101

# ----------------------------------------------------------------------
# KEY FLAGS (2200–2299)
# ----------------------------------------------------------------------
ControlFlag = 2200
DownFlag = 2201
UpFlag = 2202
NoFlag = 2203
OptionAltFlag = 2204
ShiftFlag = 2205

# ----------------------------------------------------------------------
# CURSOR STATUS (2300–2399)
# ----------------------------------------------------------------------
CursorArrow = 2300
CursorButton = 2301
CursorCustom = 2302
CursorDefault = 2303
CursorDown = 2304
CursorFourArrows = 2305
CursorHandle = 2306
CursorHidden = 2307
CursorLeft = 2308
CursorLeftRight = 2309
CursorRight = 2310
CursorRotateLarge = 2311
CursorRotateLargeLeft = 2312
CursorRotateLargeRight = 2313
CursorRotateMedium = 2314
CursorRotateMediumLeft = 2315
CursorRotateMediumRight = 2316
CursorRotateSmall = 2317
CursorRotateSmallLeft = 2318
CursorRotateSmallRight = 2319
CursorSplitterH = 2320
CursorSplitterV = 2321
CursorText = 2322
CursorUp = 2323
CursorUpDown = 2324

# ----------------------------------------------------------------------
# ELEMENTS / WORLD OBJECTS (2400–2599)
#   Includes Element_* styles and related world object constants.
# ----------------------------------------------------------------------
AircraftCarrier = 2400
Building = 2401
CoolingTower = 2402
CustomObject = 2403
Fire = 2404
ILSGlideScope = 2405
LittleDownArrow = 2406
LittleUpArrow = 2407
NDB = 2408
OilPlatform = 2409
OilPlatformSmall = 2410
PowerLine = 2411
RadioTower = 2412
Ship = 2413
SmokeStack = 2414
VOR = 2415
VORWithCompassRose = 2416
WayPoint = 2417
_Airport = 2418

Element_AircraftCarrier = 2450
Element_Airport = 2451
Element_Building = 2452
Element_CheckBox = 2453
Element_CheckBoxLit = 2454
Element_CoolingTower = 2455
Element_CopyButtons = 2456
Element_CopyButtonsWithEditingGrid = 2457
Element_CustomObject = 2458
Element_EditingGrid = 2459
Element_Fire = 2460
Element_ILSGlideScope = 2461
Element_LittleDownArrow = 2462
Element_LittleUpArrow = 2463
Element_MarkerLeft = 2464
Element_MarkerRight = 2465
Element_NDB = 2466
Element_OilPlatform = 2467
Element_OilPlatformSmall = 2468
Element_PowerLine = 2469
Element_PushButton = 2470
Element_PushButtonLit = 2471
Element_RadioTower = 2472
Element_ScrollBar = 2473
Element_Ship = 2474
Element_SmokeStack = 2475
Element_TextField = 2476
Element_TextFieldMiddle = 2477
Element_VOR = 2478
Element_VORWithCompassRose = 2479
Element_Waypoint = 2480
Element_WindowCloseBox = 2481
Element_WindowCloseBoxPressed = 2482
Element_WindowDragBar = 2483
Element_WindowDragBarSmooth = 2484
Element_Zoomer = 2485

# ----------------------------------------------------------------------
# WIDGET CLASSES (3000–3099)
# ----------------------------------------------------------------------
WidgetClass_None = 3000
WidgetClass_MainWindow = 3001
WidgetClass_SubWindow = 3002
WidgetClass_Button = 3003
WidgetClass_TextField = 3004
WidgetClass_Caption = 3005
WidgetClass_ScrollBar = 3006
WidgetClass_GeneralGraphics = 3007
WidgetClass_Progress = 3008

# ----------------------------------------------------------------------
# WIDGET PROPERTIES (4000–4199)
# ----------------------------------------------------------------------
Property_ButtonType = 4000
Property_ButtonBehavior = 4001
Property_ButtonState = 4002
Property_MainWindowHasCloseBoxes = 4003
Property_MainWindowType = 4004
Property_SubWindowType = 4005
Property_TextFieldType = 4006
Property_ActiveEditSide = 4007
Property_EditFieldSelDragStart = 4008
Property_EditFieldSelStart = 4009
Property_EditFieldSelEnd = 4010
Property_MaxCharacters = 4011
Property_PasswordMode = 4012
Property_Font = 4013
Property_GeneralGraphicsType = 4014
Property_ProgressMin = 4015
Property_ProgressMax = 4016
Property_ProgressPosition = 4017
Property_ScrollBarMin = 4018
Property_ScrollBarMax = 4019
Property_ScrollBarSliderPosition = 4020
Property_ScrollBarPageAmount = 4021
Property_ScrollBarSlop = 4022
Property_ScrollBarType = 4023
Property_ScrollPosition = 4024
Property_Clip = 4025
Property_DragXOff = 4026
Property_DragYOff = 4027
Property_Dragging = 4028
Property_Enabled = 4029
Property_Hilited = 4030
Property_Object = 4031
Property_Refcon = 4032
Property_UserStart = 4033
Property_CaptionLit = 4034
Property_CaptionFont = 4035

# ----------------------------------------------------------------------
# WIDGET / WINDOW STYLES & TRACKS (5000–5199)
# ----------------------------------------------------------------------
MainWindowStyle_MainWindow = 5000
MainWindowStyle_Translucent = 5001

SubWindowStyle_ListView = 5010
SubWindowStyle_Screen = 5011
SubWindowStyle_SubWindow = 5012

Window_Help = 5020
Window_ListView = 5021
Window_MainWindow = 5022
Window_Screen = 5023
Window_SubWindow = 5024

Track_Progress = 5040
Track_ScrollBar = 5041
Track_Slider = 5042

TextEntryField = 5050
TextTranslucent = 5051
TextTransparent = 5052

# ----------------------------------------------------------------------
# FONTS, TEXTURES, LANGUAGE, MOUSE (6000–6299)
# ----------------------------------------------------------------------
Font_Basic = 6000
Font_Proportional = 6001

Tex_GeneralInterface = 6010
Tex_Radar_Copilot = 6011
Tex_Radar_Pilot = 6012

Language_Chinese = 6020
Language_English = 6021
Language_French = 6022
Language_German = 6023
Language_Greek = 6024
Language_Italian = 6025
Language_Japanese = 6026
Language_Korean = 6027
Language_Russian = 6028
Language_Spanish = 6029
Language_Ukrainian = 6030
Language_Unknown = 6031

# ----------------------------------------------------------------------
# MAP / WEATHER / PROBE / FILE TYPES (7000–7499)
# ----------------------------------------------------------------------
MapLayer_Fill = 7000
MapLayer_Markings = 7001
MapOrientation_Map = 7002
MapOrientation_UI = 7003
MapStyle_IFR_HighEnroute = 7004
MapStyle_IFR_LowEnroute = 7005
MapStyle_VFR_Sectional = 7006

DefaultWxrRadiusMslFt = 7010
DefaultWxrRadiusNm = 7011

ProbeError = 7020
ProbeHitTerrain = 7021
ProbeMissed = 7022
ProbeY = 7023

DataFile_ReplayMovie = 7030
DataFile_Situation = 7031

# ----------------------------------------------------------------------
# NAVIGATION TYPES & FLIGHTPLAN (7500–7699)
# ----------------------------------------------------------------------
Nav_Airport = 7500
Nav_Any = 7501
Nav_DME = 7502
Nav_Fix = 7503
Nav_GlideSlope = 7504
Nav_ILS = 7505
Nav_InnerMarker = 7506
Nav_LatLon = 7507
Nav_Localizer = 7508
Nav_MiddleMarker = 7509
Nav_NDB = 7510
Nav_OuterMarker = 7511
Nav_TACAN = 7512
Nav_Unknown = 7513
Nav_VOR = 7514
NAV_NOT_FOUND = 7515

Fpl_CoPilot_Approach = 7550
Fpl_CoPilot_Primary = 7551
Fpl_CoPilot_Temporary = 7552
Fpl_Pilot_Approach = 7553
Fpl_Pilot_Primary = 7554
Fpl_Pilot_Temporary = 7555

# ----------------------------------------------------------------------
# HOST / DEVICE / INTERNAL PATHS (7700–7899)
# ----------------------------------------------------------------------
Host_Unknown = 7700
Host_XPlane = 7701

Device_CDU739_1 = 7710
Device_CDU739_2 = 7711
Device_CDU815_1 = 7712
Device_CDU815_2 = 7713
Device_G1000_MFD = 7714
Device_G1000_PFD_1 = 7715
Device_G1000_PFD_2 = 7716
Device_GNS430_1 = 7717
Device_GNS430_2 = 7718
Device_GNS530_1 = 7719
Device_GNS530_2 = 7720
Device_MCDU_1 = 7721
Device_MCDU_2 = 7722
Device_Primus_MFD_1 = 7723
Device_Primus_MFD_2 = 7724
Device_Primus_MFD_3 = 7725
Device_Primus_PFD_1 = 7726
Device_Primus_PFD_2 = 7727
Device_Primus_RMU_1 = 7728
Device_Primus_RMU_2 = 7729

INTERNALPLUGINSPATH = ""
PLUGINSPATH = ""
PLUGIN_XPLANE = 7800

MAP_IOS = ""
MAP_USER_INTERFACE = ""

# ----------------------------------------------------------------------
# MESSAGES (7900–8299)
# ----------------------------------------------------------------------
MSG_AIRPLANE_COUNT_CHANGED = 7900
MSG_AIRPORT_LOADED = 7901
MSG_DATAREFS_ADDED = 7902
MSG_ENTERED_VR = 7903
MSG_EXITING_VR = 7904
MSG_FMOD_BANK_LOADED = 7905
MSG_FMOD_BANK_UNLOADING = 7906
MSG_LIVERY_LOADED = 7907
MSG_PLANE_CRASHED = 7908
MSG_PLANE_LOADED = 7909
MSG_PLANE_UNLOADED = 7910
MSG_RELEASE_PLANES = 7911
MSG_SCENERY_LOADED = 7912
MSG_WILL_WRITE_PREFS = 7913

MsgAirplaneCountChanged = 7920
MsgAirportLoaded = 7921
MsgDatarefsAdded = 7922
MsgDatarefs_Added = 7923
MsgEnteredVr = 7924
MsgExitingVr = 7925
MsgFmodBankLoaded = 7926
MsgFmodBankUnloading = 7927
MsgLivery_Loaded = 7928
MsgPlaneCrashed = 7929
MsgPlaneLoaded = 7930
MsgPlaneUnloaded = 7931
MsgReleasePlanes = 7932
MsgSceneryLoaded = 7933
MsgWillWritePrefs = 7934

Message_CloseButtonPushed = 7940

# ----------------------------------------------------------------------
# WIDGET MESSAGES (8000–8999)
# ----------------------------------------------------------------------
Msg_None = 8000
Msg_Create = 8001
Msg_Destroy = 8002
Msg_Paint = 8003
Msg_Draw = 8004
Msg_MouseDown = 8005
Msg_MouseDrag = 8006
Msg_MouseUp = 8007
Msg_MouseWheel = 8008
Msg_KeyPress = 8009
Msg_KeyTakeFocus = 8010
Msg_KeyLoseFocus = 8011
Msg_DescriptorChanged = 8012
Msg_PropertyChanged = 8013
Msg_ExposedChanged = 8014
Msg_Hidden = 8015
Msg_Shown = 8016
Msg_Reshape = 8017
Msg_AcceptParent = 8018
Msg_AcceptChild = 8019
Msg_LoseChild = 8020
Msg_TextFieldChanged = 8021
Msg_PushButtonPressed = 8022
Msg_ScrollBarSliderPositionChanged = 8023
Msg_UserStart = 8024

# ----------------------------------------------------------------------
# KEYBOARD / VK_* (9000–10999)
# ----------------------------------------------------------------------

VK_0 = 9000
VK_1 = 9001
VK_2 = 9002
VK_3 = 9003
VK_4 = 9004
VK_5 = 9005
VK_6 = 9006
VK_7 = 9007
VK_8 = 9008
VK_9 = 9009
VK_A = 9010
VK_ADD = 9011
VK_B = 9012
VK_BACK = 9013
VK_BACKQUOTE = 9014
VK_BACKSLASH = 9015
VK_C = 9016
VK_CLEAR = 9017
VK_COMMA = 9018
VK_D = 9019
VK_DECIMAL = 9020
VK_DELETE = 9021
VK_DIVIDE = 9022
VK_DOWN = 9023
VK_E = 9024
VK_END = 9025
VK_ENTER = 9026
VK_EQUAL = 9027
VK_ESCAPE = 9028
VK_EXECUTE = 9029
VK_F10 = 9030
VK_F11 = 9031
VK_F12 = 9032
VK_F13 = 9033
VK_F14 = 9034
VK_F15 = 9035
VK_F16 = 9036
VK_F17 = 9037
VK_F18 = 9038
VK_F19 = 9039
VK_F1 = 9040
VK_F20 = 9041
VK_F21 = 9042
VK_F22 = 9043
VK_F23 = 9044
VK_F24 = 9045
VK_F2 = 9046
VK_F3 = 9047
VK_F4 = 9048
VK_F5 = 9049
VK_F6 = 9050
VK_F7 = 9051
VK_F8 = 9052
VK_F9 = 9053
VK_F = 9054
VK_G = 9055
VK_H = 9056
VK_HELP = 9057
VK_HOME = 9058
VK_I = 9059
VK_INSERT = 9060
VK_J = 9061
VK_K = 9062
VK_L = 9063
VK_LBRACE = 9064
VK_LEFT = 9065
VK_M = 9066
VK_MINUS = 9067
VK_MULTIPLY = 9068
VK_N = 9069
VK_NEXT = 9070
VK_NUMPAD0 = 9071
VK_NUMPAD1 = 9072
VK_NUMPAD2 = 9073
VK_NUMPAD3 = 9074
VK_NUMPAD4 = 9075
VK_NUMPAD5 = 9076
VK_NUMPAD6 = 9077
VK_NUMPAD7 = 9078
VK_NUMPAD8 = 9079
VK_NUMPAD9 = 9080
VK_NUMPAD_ENT = 9081
VK_NUMPAD_EQ = 9082
VK_O = 9083
VK_P = 9084
VK_PERIOD = 9085
VK_PRINT = 9086
VK_PRIOR = 9087
VK_Q = 9088
VK_QUOTE = 9089
VK_R = 9090
VK_RBRACE = 9091
VK_RETURN = 9092
VK_RIGHT = 9093
VK_S = 9094
VK_SELECT = 9095
VK_SEMICOLON = 9096
VK_SEPARATOR = 9097
VK_SLASH = 9098
VK_SNAPSHOT = 9099
VK_SPACE = 9100
VK_SUBTRACT = 9101
VK_T = 9102
VK_TAB = 9103
VK_U = 9104
VK_UP = 9105
VK_V = 9106
VK_W = 9107
VK_X = 9108
VK_Y = 9109
VK_Z = 9110

# ----------------------------------------------------------------------
# WINDOW / POSITIONING / DECORATION / LAYERS (11000–11999)
# ----------------------------------------------------------------------
WindowCenterOnMonitor = 11000
WindowFullScreenOnAllMonitors = 11001
WindowFullScreenOnMonitor = 11002
WindowPopOut = 11003
WindowPositionFree = 11004
WindowVR = 11005

WindowDecorationNone = 11100
WindowDecorationRoundRectangle = 11101
WindowDecorationSelfDecorated = 11102
WindowDecorationSelfDecoratedResizable = 11103

WindowLayerFlightOverlay = 11200
WindowLayerFloatingWindows = 11201
WindowLayerGrowlNotifications = 11202
WindowLayerModal = 11203

WindowCloseBox = 11300

# ----------------------------------------------------------------------
# WEATHER / ATMOSPHERE LAYERS (12100–12199)
# ----------------------------------------------------------------------
NumCloudLayers = 12100
NumTemperatureLayers = 12101
NumWindLayers = 12102
WindUndefinedLayer = 12103

# ----------------------------------------------------------------------
# SCROLLBAR (12200–12299)
# ----------------------------------------------------------------------
ScrollBarTypeScrollBar = 12210
ScrollBarTypeSlider = 12211

# ----------------------------------------------------------------------
# BUTTON BEHAVIOR (12300–12399)
# ----------------------------------------------------------------------
ButtonBehaviorCheckBox = 12300
ButtonBehaviorPushButton = 12301
ButtonBehaviorRadioButton = 12302

PushButton = 12310
RadioButton = 12311
CheckBox = 12312

# ----------------------------------------------------------------------
# MISC XP CONSTANTS (12400–12699)
# ----------------------------------------------------------------------
USER_AIRCRAFT = 12400
NO_PARENT = 12401
NO_PLUGIN_ID = 12402

PARAM_PARENT = 12410

# ----------------------------------------------------------------------
# INTERNAL / PYTHON / SYSTEM (12700–12999)
# ----------------------------------------------------------------------
ModuleMTimes = object()  # 12700
pythonDebugLevel = 12701
pythonExecutable = "python.exe"

# ----------------------------------------------------------------------
# DRAWING PHASES (13000–13099)
# ----------------------------------------------------------------------
Phase_FirstCockpit = 13000
Phase_Gauges = 13001
Phase_LastCockpit = 13002
Phase_LocalMap2D = 13003
Phase_LocalMap3D = 13004
Phase_LocalMapProfile = 13005
Phase_Modern3D = 13006
Phase_Panel = 13007
Phase_Window = 13008

# ----------------------------------------------------------------------
# MOUSE STATUS (13100–13199)
# ----------------------------------------------------------------------
MouseDown = 13100
MouseDrag = 13101
MouseUp = 13102

# ----------------------------------------------------------------------
# REMAINING WORLD OBJECTS / ICONS (14200–14299)
# ----------------------------------------------------------------------
MarkerLeft = 14200
MarkerRight = 14201

# ----------------------------------------------------------------------
# VERSION / IDENTIFIERS (15100–15199)
# ----------------------------------------------------------------------

VERSION = Version = "12.4"
kVersion = 15100
kXPLM_Version = 15101

# ----------------------------------------------------------------------
# MENUS (XPLMMenus API)
# ----------------------------------------------------------------------
Menu_NoCheck = 16000  # Item cannot be checked
Menu_Unchecked = 16001  # Item is checkable and currently unchecked
Menu_Checked = 16002  # Item is checkable and currently checked
