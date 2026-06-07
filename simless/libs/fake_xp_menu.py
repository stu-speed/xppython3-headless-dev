# ===========================================================================
# FakeXPMenu — DearPyGui-backed menu subsystem mixin for FakeXP
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TYPE_CHECKING, cast

from simless.libs.fake_xp_types import DPGOp, MenuRecord, MenuItemRecord
from simless.libs.graphics import GraphicsManager
from xp_typing import XPLMCommandPhase, XPLMCommandRef, XPLMMenuID, XPLMMenuCheck

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPMenu:
    @property
    def fake_xp(self) -> FakeXP:
        return cast(FakeXP, cast(object, self))

    @property
    def gm(self) -> GraphicsManager:
        return self.fake_xp.graphics_manager

    @property
    def mm(self) -> MenuManager:
        return self.fake_xp.menu_manager

    def createMenu(
            self,
            name: Optional[str] = None,
            parentMenuID: Optional[XPLMMenuID] = None,
            parentItem: int = 0,
            handler: Optional[Callable[[Any, Any], None]] = None,
            refCon: Optional[Any] = None,
    ) -> Optional[XPLMMenuID]:
        # ------------------------------------------------------------
        # 1. Normalize menu name
        # ------------------------------------------------------------
        if name is not None:
            menu_name = name
        else:
            plugin = self.fake_xp.simless_runner.active_plugin
            menu_name = plugin.name if plugin else "UnknownPlugin"

        # ------------------------------------------------------------
        # 2. Resolve parent menu
        # ------------------------------------------------------------
        if parentMenuID is None:
            parent_menu = self.mm.root_menu
        else:
            # parentMenuID / parentItem specifies a submenu item
            parent_item = self.mm.get_menu_item(parentMenuID, parentItem)
            if parent_item is None:
                return None
            if parent_item.submenu_id is None:
                return None
            parent_menu = self.mm.get_menu(parent_item.submenu_id)
            if parent_menu is None:
                return None

        # ------------------------------------------------------------
        # 3. Create submenu MenuRecord
        # ------------------------------------------------------------
        submenu = self.mm.create_menu_record(
            name=menu_name,
            parent_dpg_tag=parent_menu.dpg_tag,  # submenu attaches to parent menu
            refcon=refCon,
            handler=handler,
        )

        # ------------------------------------------------------------
        # 4. ALWAYS append a new item to the parent menu
        # ------------------------------------------------------------
        self.mm.append_menu_item_record(
            menu_rec=parent_menu,
            name=menu_name,
            refcon=refCon,
            checked=self.fake_xp.Menu_Unchecked,
            enabled=True,
            separator=False,
            command=None,
            submenu_id=submenu.menu_id,
        )

        # ------------------------------------------------------------
        # 5. Create DPG menu under the parent menu
        # ------------------------------------------------------------
        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU,
            args=(),
            kwargs={
                "tag": submenu.dpg_tag,
                "parent": submenu.parent_dpg_tag,
                "label": submenu.name,
            },
        )

        return submenu.menu_id

    def appendMenuItem(
            self,
            menuID: Optional[XPLMMenuID] = None,
            name: str = "Item",
            refCon: Any = None,
    ) -> int:
        # Resolve and validate menu
        menu_rec = self.mm.get_menu(menuID)
        if menu_rec is None:
            return -1

        # Create authoritative item record
        item_idx = self.mm.append_menu_item_record(
            menu_rec=menu_rec,
            name=name,
            refcon=refCon,
            checked=self.fake_xp.Menu_Unchecked,
            enabled=True,
            separator=False,
            command=None,  # OLD API: no commandRef
            submenu_id=None,
        )
        item_rec = menu_rec.items[item_idx]

        # Create DPG item
        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "label": name,
                "parent": menu_rec.dpg_tag,
                "tag": item_rec.dpg_tag,
                "callback": self._dispatch_menu_click,
                "user_data": menu_rec.menu_id,  # efficient: restricts search to this menu only
            },
        )

        return item_idx

    def appendMenuItemWithCommand(
            self,
            menuID: Optional[XPLMMenuID] = None,
            name: str = "Command",
            commandRef: XPLMCommandRef | None = None,
    ) -> int:
        # Resolve and validate menu
        menu_rec = self.mm.get_menu(menuID)
        if menu_rec is None:
            return -1

        # Create authoritative item record
        item_idx: int = self.mm.append_menu_item_record(
            menu_rec=menu_rec,
            name=name,
            refcon=None,  # XP: command-backed menu items do not use refCon
            checked=self.fake_xp.Menu_Unchecked,
            enabled=True,
            separator=False,
            command=commandRef,  # NEW API: attach commandRef
            submenu_id=None,
        )
        item_rec = menu_rec.items[item_idx]

        # Enqueue DPG creation
        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "label": name,
                "parent": menu_rec.dpg_tag,
                "tag": item_rec.dpg_tag,
                "callback": self._dispatch_menu_click,
                "user_data": menu_rec.menu_id,  # efficient: restricts search to this menu only
            },
        )

        return item_idx

    def appendMenuSeparator(self, menuID: Optional[XPLMMenuID] = None) -> Optional[int]:
        # Resolve and validate menu
        menu_rec = self.mm.get_menu(menuID)
        if menu_rec is None:
            return -1

        # Insert separator record
        item_idx = self.mm.append_menu_item_record(
            menu_rec=menu_rec,
            name="",
            refcon=None,
            checked=self.fake_xp.Menu_NoCheck,
            enabled=True,
            separator=True,
            command=None,  # OLD API: no commandRef
            submenu_id=None,
        )
        item_rec = menu_rec.items[item_idx]

        # Enqueue DPG separator
        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "tag": item_rec.dpg_tag,
                "parent": menu_rec.dpg_tag,
                "label": "",
                "separator": True,
                "enabled": True,
                "check": False,
            },
        )

        return item_idx

    def setMenuItemName(self, menuID: Optional[XPLMMenuID], index: int, name: str) -> None:
        # Resolve and validate item
        item_rec = self.mm.get_menu_item(menuID, index)
        if item_rec is None:
            return

        item_rec.name = name

        self.gm.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(item_rec.dpg_tag,),
            kwargs={"label": item_rec.name},
        )

    def checkMenuItem(
            self,
            menuID: Optional[XPLMMenuID],
            index: int,
            checked: Optional[XPLMMenuCheck] = None,
    ) -> None:
        if checked is None:
            checked = self.fake_xp.Menu_Checked

        # Resolve and validate item
        item_rec = self.mm.get_menu_item(menuID, index)
        if item_rec is None:
            return

        # Update logical state
        item_rec.checked = checked

        # Minimal DPG operator set
        self.gm.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(item_rec.dpg_tag,),
            kwargs={"check": (checked == self.fake_xp.Menu_Checked)},
        )

    def enableMenuItem(
            self,
            menuID: Optional[XPLMMenuID],
            index: int,
            enabled: int = 1,
    ) -> None:
        # Resolve and validate item
        item_rec = self.mm.get_menu_item(menuID, index)
        if item_rec is None:
            return

        self.gm.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(item_rec.dpg_tag,),
            kwargs={"enabled": bool(enabled)},
        )

    def removeMenuItem(self, menuID: Optional[XPLMMenuID], index: int) -> None:
        # Resolve parent menu
        menu_rec = self.mm.get_menu(menuID)
        if menu_rec is None:
            return

        # Resolve item
        item_rec = self.mm.get_menu_item(menuID, index)
        if item_rec is None:
            return

        # If this item has a submenu, delete the menu (dict entry)
        if item_rec.submenu is not None:
            del self.mm._menus[item_rec.submenu.menu_id]
            item_rec.submenu = None

        # Remove DPG item
        self.gm.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(item_rec.dpg_tag,),
            kwargs={},
        )

        # Remove from authoritative list
        del menu_rec.items[index]

    def destroyMenu(self, menuID: XPLMMenuID) -> None:
        # 1. Resolve menu record
        menu_rec = self.mm.get_menu(menuID)
        if menu_rec is None:
            return

        # 2. Find parent menu by matching parent_dpg_tag
        parent_menu = self.mm.get_menu_by_tag(menu_rec.parent_dpg_tag)
        if parent_menu is not None:
            # 3. Remove the item whose submenu_id == menuID
            for idx, item in enumerate(parent_menu.items):
                if item.submenu_id == menuID:
                    parent_menu.items.pop(idx)
                    break

        # 4. Delete DPG menu widget
        self.gm.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(menu_rec.dpg_tag,),
            kwargs={},
        )

        # 5. Delete authoritative menu record
        del self.mm._menus[menuID]

    def _dispatch_menu_click(self, sender, app_data, user_data):
        item_dpg_tag = sender
        menu_id = user_data
        menu_rec = self.mm.get_menu(menu_id)
        if menu_rec is None:
            raise KeyError(f"[FakeXP] Unknown menu_id: {menu_id}")

        for item in menu_rec.items:
            if item.dpg_tag == item_dpg_tag:
                # NEW API: item created with appendMenuItemWithCommand()
                if item.command is not None:
                    self.fake_xp.commandOnce(item.command)
                    return

                # OLD API: item created with appendMenuItem()
                if menu_rec.handler is not None:
                    menu_rec.handler(menu_rec.refcon, item.refcon)
                return

        raise KeyError(f"[FakeXP] Unknown menu item tag: {item_dpg_tag}")


class MenuManager:
    _menus: Dict[XPLMMenuID, MenuRecord]
    _next_menu_idx: int
    _menu_commands: Dict[XPLMCommandRef, Callable[[XPLMCommandRef, XPLMCommandPhase, Any], None]]
    _next_command_idx: int
    _root_plugins_menu: MenuRecord

    def __init__(self, fake_xp: FakeXP) -> None:
        # Menu bookkeeping (renderer owns DPG menus)
        self._menu_commands = {}
        self._next_command_idx = 1

        self._menus = {}
        self._next_menu_idx = 0
        self._root_plugins_menu = self.create_menu_record(
            name="Plugins",
            parent_dpg_tag="xp_menu_bar",
        )

        self.fake_xp = fake_xp

    @property
    def root_menu(self) -> MenuRecord:
        """Return the root Plugins menu ID."""
        return self._root_plugins_menu

    def get_menu(self, menu_id: Optional[XPLMMenuID]) -> Optional[MenuRecord]:
        if menu_id is None:
            return self.root_menu
        return self._menus.get(menu_id)

    def get_menu_by_tag(self, tag: str) -> Optional[MenuRecord]:
        for menu_rec in self._menus.values():
            if menu_rec.dpg_tag == tag:
                return menu_rec
        return None

    def get_submenu(self, menu_id: Optional[XPLMMenuID], item_idx) -> Optional[MenuRecord]:
        """
        XP semantics:
          - menu_id=None → return Plugins menu root
          - otherwise → return submenu attached to item_idx
        """
        if menu_id is None:
            return self.root_menu
        menu_item = self.get_menu_item(menu_id, item_idx)
        if menu_item is None:
            return None
        return self.get_menu(menu_item.submenu_id)

    def get_menu_item(self, menu_id: Optional[XPLMMenuID], index: int) -> Optional[MenuItemRecord]:
        menu_rec = self.get_menu(menu_id)
        if menu_rec is None:
            return None

        if index < 0 or index >= len(menu_rec.items):
            return None

        return menu_rec.items[index]

    def create_menu_record(
            self,
            name: str,
            parent_dpg_tag: str,
            refcon: Optional[Any] = None,
            handler: Optional[
                Callable[[Any, Any], None]
            ] = None,
    ) -> MenuRecord:
        menu_id = XPLMMenuID(self._next_menu_idx)
        self._next_menu_idx += 1

        dpg_tag = f"xp_menu_{menu_id}"

        menu_rec = MenuRecord(
            menu_id=menu_id,
            name=name,
            dpg_tag=dpg_tag,
            parent_dpg_tag=parent_dpg_tag,
            handler=handler,
            refcon=refcon,
        )
        self._menus[menu_id] = menu_rec

        return menu_rec

    def append_menu_item_record(
            self,
            menu_rec: MenuRecord,
            name: str,
            refcon: Any,
            checked: XPLMMenuCheck,
            enabled: bool,
            separator: bool,
            command: Optional[XPLMCommandRef],
            submenu_id: Optional[XPLMMenuID],
    ) -> int:
        """Append a menu item to a menu and return its index."""
        items = menu_rec.items
        idx = len(items)
        item_tag = f"{menu_rec.dpg_tag}_{idx}"
        item_rec = MenuItemRecord(
            name=name,
            refcon=refcon,
            checked=checked,
            enabled=enabled,
            separator=separator,
            command=command,
            dpg_tag=item_tag,
            submenu_id=submenu_id,
        )
        items.append(item_rec)

        return idx
