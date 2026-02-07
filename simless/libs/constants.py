# simless/libs/fake_xp/constants.py
# ===========================================================================
# xp.* constants — widget classes, properties, messages, etc.
# Centralized so FakeXP and plugins share a single source of truth.
# ===========================================================================

from __future__ import annotations


def bind_xp_constants(xp: object) -> None:
    # Widget classes
    xp.WidgetClass_MainWindow = 1
    xp.WidgetClass_SubWindow = 2
    xp.WidgetClass_Button = 3
    xp.WidgetClass_TextField = 4
    xp.WidgetClass_Caption = 5
    xp.WidgetClass_ScrollBar = 6
    xp.WidgetClass_GeneralGraphics = 7

    # Scrollbar properties
    xp.Property_ScrollBarMin = 100
    xp.Property_ScrollBarMax = 101
    xp.Property_ScrollBarSliderPosition = 102
    xp.Property_ScrollBarPageAmount = 103
    xp.Property_ScrollBarType = 104
    xp.ScrollBarTypeScrollBar = 0
    xp.ScrollBarTypeSlider = 1

    # Main window properties
    xp.Property_MainWindowHasCloseBoxes = 110

    # Button properties
    xp.Property_ButtonType = 200
    xp.PushButton = 0
    xp.RadioButton = 1
    xp.CheckBox = 2

    # Widget messages
    xp.Msg_MouseDown = 1
    xp.Msg_MouseDrag = 2
    xp.Msg_MouseUp = 3
    xp.Msg_KeyPress = 4
    xp.Msg_ScrollBarSliderPositionChanged = 5
    xp.Msg_PushButtonPressed = 6
    xp.Message_CloseButtonPushed = 7
