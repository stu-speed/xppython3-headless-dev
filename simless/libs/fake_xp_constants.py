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
#   - Names must match the real SDK exactly (xp.pyi).
#   - Values are not authoritative; they exist only to satisfy plugin
#     imports, comparisons, and switch logic during simless runs.
#   - No classes, enums, or grouping structures — a flat module keeps
#     imports simple and mirrors the real xp.* surface.
#
# USAGE
#   - FakeXP bulk‑binds these names into the xp.* namespace at startup.
#   - Plugins see xp.CONSTANT_NAME exactly as they would in X‑Plane.
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
    # Data type bitmask
    xp.Type_Int = 1 << 0  # 1
    xp.Type_Float = 1 << 1  # 2
    xp.Type_Double = 1 << 2  # 4
    xp.Type_FloatArray = 1 << 3  # 8
    xp.Type_IntArray = 1 << 4  # 16
    xp.Type_Data = 1 << 5  # 32
    xp.Type_Unknown = 0

    # ----------------------------------------------------------------------
    # AUDIO (1000–1999)
    # ----------------------------------------------------------------------
    xp.AudioExteriorAircraft = 1000
    xp.AudioExteriorEnvironment = 1001
    xp.AudioExteriorUnprocessed = 1002
    xp.AudioGround = 1003
    xp.AudioInterior = 1004
    xp.AudioRadioCom1 = 1005
    xp.AudioRadioCom2 = 1006
    xp.AudioRadioCopilot = 1007
    xp.AudioRadioPilot = 1008
    xp.AudioUI = 1009
    xp.Master = 1010
    xp.MasterBank = 1011
    xp.RadioBank = 1012
    xp.FMOD_OK = 1013
    xp.FMOD_SOUND_FORMAT_PCM16 = 1014

    # ----------------------------------------------------------------------
    # COMMAND PHASES (2000–2099)
    # ----------------------------------------------------------------------
    xp.CommandBegin = 2000
    xp.CommandContinue = 2001
    xp.CommandEnd = 2002

    # ----------------------------------------------------------------------
    # CAMERA CONTROL (2100–2199)
    # ----------------------------------------------------------------------
    xp.ControlCameraForever = 2100
    xp.ControlCameraUntilViewChanges = 2101

    # ----------------------------------------------------------------------
    # KEY FLAGS (2200–2299)
    # ----------------------------------------------------------------------
    xp.ControlFlag = 2200
    xp.DownFlag = 2201
    xp.UpFlag = 2202
    xp.NoFlag = 2203
    xp.OptionAltFlag = 2204
    xp.ShiftFlag = 2205

    # ----------------------------------------------------------------------
    # CURSOR STATUS (2300–2399)
    # ----------------------------------------------------------------------
    xp.CursorArrow = 2300
    xp.CursorButton = 2301
    xp.CursorCustom = 2302
    xp.CursorDefault = 2303
    xp.CursorDown = 2304
    xp.CursorFourArrows = 2305
    xp.CursorHandle = 2306
    xp.CursorHidden = 2307
    xp.CursorLeft = 2308
    xp.CursorLeftRight = 2309
    xp.CursorRight = 2310
    xp.CursorRotateLarge = 2311
    xp.CursorRotateLargeLeft = 2312
    xp.CursorRotateLargeRight = 2313
    xp.CursorRotateMedium = 2314
    xp.CursorRotateMediumLeft = 2315
    xp.CursorRotateMediumRight = 2316
    xp.CursorRotateSmall = 2317
    xp.CursorRotateSmallLeft = 2318
    xp.CursorRotateSmallRight = 2319
    xp.CursorSplitterH = 2320
    xp.CursorSplitterV = 2321
    xp.CursorText = 2322
    xp.CursorUp = 2323
    xp.CursorUpDown = 2324

    # ----------------------------------------------------------------------
    # ELEMENTS / WORLD OBJECTS (2400–2599)
    #   Includes Element_* styles and related world object constants.
    # ----------------------------------------------------------------------
    xp.AircraftCarrier = 2400
    xp.Building = 2401
    xp.CoolingTower = 2402
    xp.CustomObject = 2403
    xp.Fire = 2404
    xp.ILSGlideScope = 2405
    xp.LittleDownArrow = 2406
    xp.LittleUpArrow = 2407
    xp.NDB = 2408
    xp.OilPlatform = 2409
    xp.OilPlatformSmall = 2410
    xp.PowerLine = 2411
    xp.RadioTower = 2412
    xp.Ship = 2413
    xp.SmokeStack = 2414
    xp.VOR = 2415
    xp.VORWithCompassRose = 2416
    xp.WayPoint = 2417
    xp._Airport = 2418

    xp.Element_AircraftCarrier = 2450
    xp.Element_Airport = 2451
    xp.Element_Building = 2452
    xp.Element_CheckBox = 2453
    xp.Element_CheckBoxLit = 2454
    xp.Element_CoolingTower = 2455
    xp.Element_CopyButtons = 2456
    xp.Element_CopyButtonsWithEditingGrid = 2457
    xp.Element_CustomObject = 2458
    xp.Element_EditingGrid = 2459
    xp.Element_Fire = 2460
    xp.Element_ILSGlideScope = 2461
    xp.Element_LittleDownArrow = 2462
    xp.Element_LittleUpArrow = 2463
    xp.Element_MarkerLeft = 2464
    xp.Element_MarkerRight = 2465
    xp.Element_NDB = 2466
    xp.Element_OilPlatform = 2467
    xp.Element_OilPlatformSmall = 2468
    xp.Element_PowerLine = 2469
    xp.Element_PushButton = 2470
    xp.Element_PushButtonLit = 2471
    xp.Element_RadioTower = 2472
    xp.Element_ScrollBar = 2473
    xp.Element_Ship = 2474
    xp.Element_SmokeStack = 2475
    xp.Element_TextField = 2476
    xp.Element_TextFieldMiddle = 2477
    xp.Element_VOR = 2478
    xp.Element_VORWithCompassRose = 2479
    xp.Element_Waypoint = 2480
    xp.Element_WindowCloseBox = 2481
    xp.Element_WindowCloseBoxPressed = 2482
    xp.Element_WindowDragBar = 2483
    xp.Element_WindowDragBarSmooth = 2484
    xp.Element_Zoomer = 2485

    # ----------------------------------------------------------------------
    # WIDGET CLASSES (3000–3099)
    # ----------------------------------------------------------------------
    xp.WidgetClass_None = 3000
    xp.WidgetClass_MainWindow = 3001
    xp.WidgetClass_SubWindow = 3002
    xp.WidgetClass_Button = 3003
    xp.WidgetClass_TextField = 3004
    xp.WidgetClass_Caption = 3005
    xp.WidgetClass_ScrollBar = 3006
    xp.WidgetClass_GeneralGraphics = 3007
    xp.WidgetClass_Progress = 3008

    # ----------------------------------------------------------------------
    # WIDGET PROPERTIES (4000–4199)
    # ----------------------------------------------------------------------
    xp.Property_ButtonType = 4000
    xp.Property_ButtonBehavior = 4001
    xp.Property_ButtonState = 4002
    xp.Property_MainWindowHasCloseBoxes = 4003
    xp.Property_MainWindowType = 4004
    xp.Property_SubWindowType = 4005
    xp.Property_TextFieldType = 4006
    xp.Property_ActiveEditSide = 4007
    xp.Property_EditFieldSelDragStart = 4008
    xp.Property_EditFieldSelStart = 4009
    xp.Property_EditFieldSelEnd = 4010
    xp.Property_MaxCharacters = 4011
    xp.Property_PasswordMode = 4012
    xp.Property_Font = 4013
    xp.Property_GeneralGraphicsType = 4014
    xp.Property_ProgressMin = 4015
    xp.Property_ProgressMax = 4016
    xp.Property_ProgressPosition = 4017
    xp.Property_ScrollBarMin = 4018
    xp.Property_ScrollBarMax = 4019
    xp.Property_ScrollBarSliderPosition = 4020
    xp.Property_ScrollBarPageAmount = 4021
    xp.Property_ScrollBarSlop = 4022
    xp.Property_ScrollBarType = 4023
    xp.Property_ScrollPosition = 4024
    xp.Property_Clip = 4025
    xp.Property_DragXOff = 4026
    xp.Property_DragYOff = 4027
    xp.Property_Dragging = 4028
    xp.Property_Enabled = 4029
    xp.Property_Hilited = 4030
    xp.Property_Object = 4031
    xp.Property_Refcon = 4032
    xp.Property_UserStart = 4033
    xp.Property_CaptionLit = 4034
    xp.Property_CaptionFont = 4035

    # ----------------------------------------------------------------------
    # WIDGET / WINDOW STYLES & TRACKS (5000–5199)
    # ----------------------------------------------------------------------
    xp.MainWindowStyle_MainWindow = 5000
    xp.MainWindowStyle_Translucent = 5001

    xp.SubWindowStyle_ListView = 5010
    xp.SubWindowStyle_Screen = 5011
    xp.SubWindowStyle_SubWindow = 5012

    xp.Window_Help = 5020
    xp.Window_ListView = 5021
    xp.Window_MainWindow = 5022
    xp.Window_Screen = 5023
    xp.Window_SubWindow = 5024

    xp.WindowCloseBox = 5030

    xp.Track_Progress = 5040
    xp.Track_ScrollBar = 5041
    xp.Track_Slider = 5042

    xp.TextEntryField = 5050
    xp.TextTranslucent = 5051
    xp.TextTransparent = 5052

    # ----------------------------------------------------------------------
    # FONTS, TEXTURES, LANGUAGE, MOUSE (6000–6299)
    # ----------------------------------------------------------------------
    xp.Font_Basic = 6000
    xp.Font_Proportional = 6001

    xp.Tex_GeneralInterface = 6010
    xp.Tex_Radar_Copilot = 6011
    xp.Tex_Radar_Pilot = 6012

    xp.Language_Chinese = 6020
    xp.Language_English = 6021
    xp.Language_French = 6022
    xp.Language_German = 6023
    xp.Language_Greek = 6024
    xp.Language_Italian = 6025
    xp.Language_Japanese = 6026
    xp.Language_Korean = 6027
    xp.Language_Russian = 6028
    xp.Language_Spanish = 6029
    xp.Language_Ukrainian = 6030
    xp.Language_Unknown = 6031

    xp.MouseDown = 6040
    xp.MouseDrag = 6041
    xp.MouseUp = 6042

    # ----------------------------------------------------------------------
    # MAP / WEATHER / PROBE / FILE TYPES (7000–7499)
    # ----------------------------------------------------------------------
    xp.MapLayer_Fill = 7000
    xp.MapLayer_Markings = 7001
    xp.MapOrientation_Map = 7002
    xp.MapOrientation_UI = 7003
    xp.MapStyle_IFR_HighEnroute = 7004
    xp.MapStyle_IFR_LowEnroute = 7005
    xp.MapStyle_VFR_Sectional = 7006

    xp.DefaultWxrRadiusMslFt = 7010
    xp.DefaultWxrRadiusNm = 7011

    xp.ProbeError = 7020
    xp.ProbeHitTerrain = 7021
    xp.ProbeMissed = 7022
    xp.ProbeY = 7023

    xp.DataFile_ReplayMovie = 7030
    xp.DataFile_Situation = 7031

    # ----------------------------------------------------------------------
    # NAVIGATION TYPES & FLIGHTPLAN (7500–7699)
    # ----------------------------------------------------------------------
    xp.Nav_Airport = 7500
    xp.Nav_Any = 7501
    xp.Nav_DME = 7502
    xp.Nav_Fix = 7503
    xp.Nav_GlideSlope = 7504
    xp.Nav_ILS = 7505
    xp.Nav_InnerMarker = 7506
    xp.Nav_LatLon = 7507
    xp.Nav_Localizer = 7508
    xp.Nav_MiddleMarker = 7509
    xp.Nav_NDB = 7510
    xp.Nav_OuterMarker = 7511
    xp.Nav_TACAN = 7512
    xp.Nav_Unknown = 7513
    xp.Nav_VOR = 7514
    xp.NAV_NOT_FOUND = 7515

    xp.Fpl_CoPilot_Approach = 7550
    xp.Fpl_CoPilot_Primary = 7551
    xp.Fpl_CoPilot_Temporary = 7552
    xp.Fpl_Pilot_Approach = 7553
    xp.Fpl_Pilot_Primary = 7554
    xp.Fpl_Pilot_Temporary = 7555

    # ----------------------------------------------------------------------
    # HOST / DEVICE / INTERNAL PATHS (7700–7899)
    # ----------------------------------------------------------------------
    xp.Host_Unknown = 7700
    xp.Host_XPlane = 7701

    xp.Device_CDU739_1 = 7710
    xp.Device_CDU739_2 = 7711
    xp.Device_CDU815_1 = 7712
    xp.Device_CDU815_2 = 7713
    xp.Device_G1000_MFD = 7714
    xp.Device_G1000_PFD_1 = 7715
    xp.Device_G1000_PFD_2 = 7716
    xp.Device_GNS430_1 = 7717
    xp.Device_GNS430_2 = 7718
    xp.Device_GNS530_1 = 7719
    xp.Device_GNS530_2 = 7720
    xp.Device_MCDU_1 = 7721
    xp.Device_MCDU_2 = 7722
    xp.Device_Primus_MFD_1 = 7723
    xp.Device_Primus_MFD_2 = 7724
    xp.Device_Primus_MFD_3 = 7725
    xp.Device_Primus_PFD_1 = 7726
    xp.Device_Primus_PFD_2 = 7727
    xp.Device_Primus_RMU_1 = 7728
    xp.Device_Primus_RMU_2 = 7729

    xp.INTERNALPLUGINSPATH = ""
    xp.PLUGINSPATH = ""
    xp.PLUGIN_XPLANE = 7800

    xp.MAP_IOS = ""
    xp.MAP_USER_INTERFACE = ""

    # ----------------------------------------------------------------------
    # MESSAGES (7900–8299)
    # ----------------------------------------------------------------------
    xp.MSG_AIRPLANE_COUNT_CHANGED = 7900
    xp.MSG_AIRPORT_LOADED = 7901
    xp.MSG_DATAREFS_ADDED = 7902
    xp.MSG_ENTERED_VR = 7903
    xp.MSG_EXITING_VR = 7904
    xp.MSG_FMOD_BANK_LOADED = 7905
    xp.MSG_FMOD_BANK_UNLOADING = 7906
    xp.MSG_LIVERY_LOADED = 7907
    xp.MSG_PLANE_CRASHED = 7908
    xp.MSG_PLANE_LOADED = 7909
    xp.MSG_PLANE_UNLOADED = 7910
    xp.MSG_RELEASE_PLANES = 7911
    xp.MSG_SCENERY_LOADED = 7912
    xp.MSG_WILL_WRITE_PREFS = 7913

    xp.MsgAirplaneCountChanged = 7920
    xp.MsgAirportLoaded = 7921
    xp.MsgDatarefsAdded = 7922
    xp.MsgDatarefs_Added = 7923
    xp.MsgEnteredVr = 7924
    xp.MsgExitingVr = 7925
    xp.MsgFmodBankLoaded = 7926
    xp.MsgFmodBankUnloading = 7927
    xp.MsgLivery_Loaded = 7928
    xp.MsgPlaneCrashed = 7929
    xp.MsgPlaneLoaded = 7930
    xp.MsgPlaneUnloaded = 7931
    xp.MsgReleasePlanes = 7932
    xp.MsgSceneryLoaded = 7933
    xp.MsgWillWritePrefs = 7934

    xp.Message_CloseButtonPushed = 7940

    # ----------------------------------------------------------------------
    # WIDGET MESSAGES (8000–8999)
    # ----------------------------------------------------------------------
    xp.Msg_None = 8000
    xp.Msg_Create = 8001
    xp.Msg_Destroy = 8002
    xp.Msg_Paint = 8003
    xp.Msg_Draw = 8004
    xp.Msg_MouseDown = 8005
    xp.Msg_MouseDrag = 8006
    xp.Msg_MouseUp = 8007
    xp.Msg_MouseWheel = 8008
    xp.Msg_KeyPress = 8009
    xp.Msg_KeyTakeFocus = 8010
    xp.Msg_KeyLoseFocus = 8011
    xp.Msg_DescriptorChanged = 8012
    xp.Msg_PropertyChanged = 8013
    xp.Msg_ExposedChanged = 8014
    xp.Msg_Hidden = 8015
    xp.Msg_Shown = 8016
    xp.Msg_Reshape = 8017
    xp.Msg_AcceptParent = 8018
    xp.Msg_AcceptChild = 8019
    xp.Msg_LoseChild = 8020
    xp.Msg_TextFieldChanged = 8021
    xp.Msg_PushButtonPressed = 8022
    xp.Msg_ScrollBarSliderPositionChanged = 8023
    xp.Msg_UserStart = 8024

    xp.Message_CloseButtonPushed = 8100

    # ----------------------------------------------------------------------
    # KEYBOARD / VK_* (9000–10999)
    # ----------------------------------------------------------------------
    base = 9000
    names = [
        "VK_0", "VK_1", "VK_2", "VK_3", "VK_4", "VK_5", "VK_6", "VK_7", "VK_8", "VK_9",
        "VK_A", "VK_ADD", "VK_B", "VK_BACK", "VK_BACKQUOTE", "VK_BACKSLASH", "VK_C",
        "VK_CLEAR", "VK_COMMA", "VK_D", "VK_DECIMAL", "VK_DELETE", "VK_DIVIDE",
        "VK_DOWN", "VK_E", "VK_END", "VK_ENTER", "VK_EQUAL", "VK_ESCAPE", "VK_EXECUTE",
        "VK_F10", "VK_F11", "VK_F12", "VK_F13", "VK_F14", "VK_F15", "VK_F16", "VK_F17",
        "VK_F18", "VK_F19", "VK_F1", "VK_F20", "VK_F21", "VK_F22", "VK_F23", "VK_F24",
        "VK_F2", "VK_F3", "VK_F4", "VK_F5", "VK_F6", "VK_F7", "VK_F8", "VK_F9", "VK_F",
        "VK_G", "VK_H", "VK_HELP", "VK_HOME", "VK_I", "VK_INSERT", "VK_J", "VK_K",
        "VK_L", "VK_LBRACE", "VK_LEFT", "VK_M", "VK_MINUS", "VK_MULTIPLY", "VK_N",
        "VK_NEXT", "VK_NUMPAD0", "VK_NUMPAD1", "VK_NUMPAD2", "VK_NUMPAD3",
        "VK_NUMPAD4", "VK_NUMPAD5", "VK_NUMPAD6", "VK_NUMPAD7", "VK_NUMPAD8",
        "VK_NUMPAD9", "VK_NUMPAD_ENT", "VK_NUMPAD_EQ", "VK_O", "VK_P", "VK_PERIOD",
        "VK_PRINT", "VK_PRIOR", "VK_Q", "VK_QUOTE", "VK_R", "VK_RBRACE", "VK_RETURN",
        "VK_RIGHT", "VK_S", "VK_SELECT", "VK_SEMICOLON", "VK_SEPARATOR", "VK_SLASH",
        "VK_SNAPSHOT", "VK_SPACE", "VK_SUBTRACT", "VK_T", "VK_TAB", "VK_U", "VK_UP",
        "VK_V", "VK_W", "VK_X", "VK_Y", "VK_Z"
    ]

    for i, name in enumerate(names):
        setattr(xp, name, base + i)

    # ----------------------------------------------------------------------
    # WINDOW / POSITIONING / DECORATION / LAYERS (11000–11999)
    # ----------------------------------------------------------------------
    xp.WindowCenterOnMonitor = 11000
    xp.WindowFullScreenOnAllMonitors = 11001
    xp.WindowFullScreenOnMonitor = 11002
    xp.WindowPopOut = 11003
    xp.WindowPositionFree = 11004
    xp.WindowVR = 11005

    xp.WindowDecorationNone = 11100
    xp.WindowDecorationRoundRectangle = 11101
    xp.WindowDecorationSelfDecorated = 11102
    xp.WindowDecorationSelfDecoratedResizable = 11103

    xp.WindowLayerFlightOverlay = 11200
    xp.WindowLayerFloatingWindows = 11201
    xp.WindowLayerGrowlNotifications = 11202
    xp.WindowLayerModal = 11203

    xp.WindowCloseBox = 11300

    # ----------------------------------------------------------------------
    # WEATHER / ATMOSPHERE LAYERS (12100–12199)
    # ----------------------------------------------------------------------
    xp.NumCloudLayers = 12100
    xp.NumTemperatureLayers = 12101
    xp.NumWindLayers = 12102
    xp.WindUndefinedLayer = 12103

    # ----------------------------------------------------------------------
    # PROGRESS / TRACK / SCROLLBAR (12200–12299)
    # ----------------------------------------------------------------------
    xp.Track_Progress = 12200
    xp.Track_ScrollBar = 12201
    xp.Track_Slider = 12202

    xp.ScrollBarTypeScrollBar = 12210
    xp.ScrollBarTypeSlider = 12211

    # ----------------------------------------------------------------------
    # BUTTON BEHAVIOR (12300–12399)
    # ----------------------------------------------------------------------
    xp.ButtonBehaviorCheckBox = 12300
    xp.ButtonBehaviorPushButton = 12301
    xp.ButtonBehaviorRadioButton = 12302

    xp.PushButton = 12310
    xp.RadioButton = 12311
    xp.CheckBox = 12312

    # ----------------------------------------------------------------------
    # MISC XP CONSTANTS (12400–12699)
    # ----------------------------------------------------------------------
    xp.USER_AIRCRAFT = 12400
    xp.NO_PARENT = 12401
    xp.NO_PLUGIN_ID = 12402

    xp.PARAM_PARENT = 12410

    xp.NAV_NOT_FOUND = 12420

    # ----------------------------------------------------------------------
    # INTERNAL / PYTHON / SYSTEM (12700–12999)
    # ----------------------------------------------------------------------
    xp.ModuleMTimes = object()  # 12700
    xp.pythonDebugLevel = 12701
    xp.pythonExecutable = ""

    # ----------------------------------------------------------------------
    # DRAWING PHASES (13000–13099)
    # ----------------------------------------------------------------------
    xp.Phase_FirstCockpit = 13000
    xp.Phase_Gauges = 13001
    xp.Phase_LastCockpit = 13002
    xp.Phase_LocalMap2D = 13003
    xp.Phase_LocalMap3D = 13004
    xp.Phase_LocalMapProfile = 13005
    xp.Phase_Modern3D = 13006
    xp.Phase_Panel = 13007
    xp.Phase_Window = 13008

    # ----------------------------------------------------------------------
    # MOUSE STATUS (13100–13199)
    # ----------------------------------------------------------------------
    xp.MouseDown = 13100
    xp.MouseDrag = 13101
    xp.MouseUp = 13102

    # ----------------------------------------------------------------------
    # XP WINDOW STYLES (13200–13299)
    # ----------------------------------------------------------------------
    xp.Window_Help = 13200
    xp.Window_ListView = 13201
    xp.Window_MainWindow = 13202
    xp.Window_Screen = 13203
    xp.Window_SubWindow = 13204

    # ----------------------------------------------------------------------
    # WINDOW / UI CONTINUATION (14000–14199)
    # ----------------------------------------------------------------------
    xp.WindowLayerFlightOverlay = 14000
    xp.WindowLayerFloatingWindows = 14001
    xp.WindowLayerGrowlNotifications = 14002
    xp.WindowLayerModal = 14003

    # ----------------------------------------------------------------------
    # REMAINING WORLD OBJECTS / ICONS (14200–14299)
    # ----------------------------------------------------------------------
    xp.MarkerLeft = 14200
    xp.MarkerRight = 14201

    # ----------------------------------------------------------------------
    # REMAINING SCROLLBAR / BUTTON / TEXTFIELD (14300–14399)
    # ----------------------------------------------------------------------
    xp.ScrollBarTypeScrollBar = 14300
    xp.ScrollBarTypeSlider = 14301

    # ----------------------------------------------------------------------
    # REMAINING MAP / INTERNAL STRINGS (14500–14599)
    # ----------------------------------------------------------------------
    xp.MAP_IOS = ""
    xp.MAP_USER_INTERFACE = ""

    # ----------------------------------------------------------------------
    # REMAINING PYTHON / INTERNAL (15000–15099)
    # ----------------------------------------------------------------------
    xp.pythonDebugLevel = 15000
    xp.pythonExecutable = "python.exe"

    # ----------------------------------------------------------------------
    # VERSION / IDENTIFIERS (15100–15199)
    # ----------------------------------------------------------------------

    xp.VERSION = xp.Version = "12.4"
    xp.kVersion = 15100
    xp.kXPLM_Version = 15101

    # ----------------------------------------------------------------------
    # MENUS (XPLMMenus API)
    # ----------------------------------------------------------------------
    xp.Menu_NoCheck = 16000  # Item cannot be checked
    xp.Menu_Unchecked = 16001  # Item is checkable and currently unchecked
    xp.Menu_Checked = 16002  # Item is checkable and currently checked
