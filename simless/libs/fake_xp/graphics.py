# simless/libs/fake_xp/graphics.py
# ===========================================================================
# Graphics subsystem — wraps FakeXPGraphics and exposes xp.* graphics API.
# ===========================================================================

from __future__ import annotations

from typing import Any, List, Sequence

from simless.libs.fake_xp_graphics import FakeXPGraphics as _CoreGraphics  # existing implementation


class FakeXPGraphics(_CoreGraphics):
    """
    Thin subclass wrapper so we can expose a list of public API names
    for binding into xp.* and FakeXP.
    """

    public_api_names: List[str] = [
        "registerDrawCallback",
        "unregisterDrawCallback",
        "drawString",
        "drawNumber",
        "setGraphicsState",
        "bindTexture2d",
        "generateTextureNumbers",
        "deleteTexture",
    ]

    def __init__(self, fakexp: Any) -> None:
        super().__init__(fakexp)
