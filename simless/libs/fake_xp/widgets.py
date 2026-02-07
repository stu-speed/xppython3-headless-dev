# simless/libs/fake_xp/widgets.py
# ===========================================================================
# Widget subsystem — wraps FakeXPWidgets and exposes xp.* widget API.
# ===========================================================================

from __future__ import annotations

from typing import Any, List

from simless.libs.fake_xp_widget import FakeXPWidgets as _CoreWidgets  # existing implementation


class FakeXPWidgets(_CoreWidgets):
    """
    Thin subclass wrapper so we can expose a list of public API names
    for binding into xp.* and FakeXP.
    """

    public_api_names: List[str] = [
        "createWidget",
        "killWidget",
        "setWidgetGeometry",
        "getWidgetGeometry",
        "getWidgetExposedGeometry",
        "showWidget",
        "hideWidget",
        "isWidgetVisible",
        "isWidgetInFront",
        "bringWidgetToFront",
        "pushWidgetBehind",
        "getParentWidget",
        "getWidgetClass",
        "getWidgetUnderlyingWindow",
        "setWidgetDescriptor",
        "getWidgetDescriptor",
        "getWidgetForLocation",
        "setKeyboardFocus",
        "loseKeyboardFocus",
        "setWidgetProperty",
        "getWidgetProperty",
        "addWidgetCallback",
        "sendWidgetMessage",
    ]

    def __init__(self, fakexp: Any) -> None:
        super().__init__(fakexp)
