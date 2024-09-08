"""MonitorState maintains state of a specific Monitor under a Virtual Desktop"""

import logging
from typing import List, Optional

from jigsawwm.w32.window import Window, Rect

from .theme import Theme
from .workspace_state import WorkspaceState
from .const import (
    MONITOR_STATE,
    WORKSPACE_STATE,
    PREFERRED_MONITOR_INDEX,
    PREFERRED_WORKSPACE_INDEX,
    PREFERRED_WINDOW_INDEX,
)

logger = logging.getLogger(__name__)


class MonitorState:
    """MonitorState holds variables needed by a Monitor


    :param VirtDeskState virtdesk_state: associated virtual desktop
    :param Monitor monitor: associated system monitor
    :param str theme: the active theme for the monitor in the virtual desktop
    """

    index: int
    name: str
    rect: Rect
    full_rect: Rect
    theme: Theme
    workspaces: List[WorkspaceState]
    active_workspace_index: int

    def __init__(
        self,
        index: int,
        name: str,
        workspace_names: List[str],
        rect: Rect,
        full_rect: Rect,
        theme: Theme,
    ):
        self.index = index
        self.name = name
        self.rect = rect
        self.full_rect = full_rect
        self.theme = theme
        self.active_workspace_index = 0
        self.workspaces = []
        self.set_workspaces(workspace_names)

    def __repr__(self) -> str:
        return f"<MonitorState #{self.index} {self.rect}>"

    def set_workspaces(self, workspace_names: List[str]):
        """Update the workspaces"""
        if len(self.workspaces) > len(workspace_names):
            self.active_workspace_index = self.active_workspace_index % len(
                workspace_names
            )
            active_workspace = self.workspaces[self.active_workspace_index]
            while len(self.workspaces) > len(workspace_names):
                ws = self.workspaces.pop()
                active_workspace.windows |= ws.windows
        if len(self.workspaces) < len(workspace_names):
            while len(self.workspaces) < len(workspace_names):
                i = len(self.workspaces)
                self.workspaces.append(
                    WorkspaceState(
                        monitor_index=self.index,
                        index=len(self.workspaces),
                        name=workspace_names[i],
                        rect=self.rect,
                        alter_rect=self.compute_alter_rect(i),
                        theme=self.theme,
                    )
                )
        for i, workspace_name in enumerate(workspace_names):
            self.workspaces[i].name = workspace_name
        self.workspace.toggle(True)

    def set_rect(self, rect: Rect):
        """Update the monitor rect"""
        self.rect = rect
        for workspace in self.workspaces:
            workspace.set_rect(rect)

    @property
    def workspace(self) -> WorkspaceState:
        """Get the active workspace of the monitor"""
        return self.workspaces[self.active_workspace_index]

    def assign_window(
        self,
        w: Window,
        workspace: Optional[WorkspaceState] = None,
        window_index: Optional[int] = None,
    ):
        """Assign a window to the monitor"""
        workspace = workspace or self.workspace
        w.attrs[PREFERRED_MONITOR_INDEX] = self.index
        w.attrs[PREFERRED_WORKSPACE_INDEX] = workspace.index
        if window_index:
            w.attrs[PREFERRED_WINDOW_INDEX] = window_index
        elif PREFERRED_WINDOW_INDEX in w.attrs:
            del w.attrs[PREFERRED_WINDOW_INDEX]
        logger.info("assigned %s to %s with index %s", w, workspace, window_index)
        self.add_window(w, workspace_index=workspace.index)

    def add_window(self, w: Window, workspace_index: Optional[int] = None):
        """Add new windows to the active workspace of the monitor"""
        if workspace_index is None:
            workspace_index = self.active_workspace_index
        ws = self.workspaces[workspace_index]
        ws.windows.add(w)
        ws.toggle_window(w, ws.showing)
        w.attrs[MONITOR_STATE] = self
        w.attrs[WORKSPACE_STATE] = ws
        if not w.tilable:
            self.move_floating_window_in(w)
        logger.info("added window %s to %s", w, ws)
        for c in w.manageable_children:
            self.add_window(c, workspace_index=workspace_index)

    def remove_window(self, w: Window):
        """Remove windows from the active workspace of the monitor"""
        ws: WorkspaceState = w.attrs[WORKSPACE_STATE]
        ws.windows.remove(w)
        logger.info("removed window %s from %s", w, ws)
        for c in w.manageable_children:
            self.remove_window(c)
        # del w.attrs[MONITOR_STATE]
        # del w.attrs[WORKSPACE_STATE]

    def switch_workspace(self, workspace_index: int):
        """Switch to the workspace by index"""
        logger.debug("%s switch workspace by index to #%d", self, workspace_index)
        workspace_index = workspace_index % len(self.workspaces)
        if workspace_index == self.active_workspace_index:
            logger.warning("already in workspace index %s", workspace_index)
            return
        self.workspaces[self.active_workspace_index].toggle(False)
        self.workspaces[workspace_index].toggle(True)
        self.active_workspace_index = workspace_index

    def move_to_workspace(self, window: Window, workspace_index: int):
        """Move the window to the workspace by index"""
        logger.debug("%s move window %s to #%d", self, window, workspace_index)
        if workspace_index >= len(self.workspaces):
            logger.warning("workspace index %s does not exist", workspace_index)
            return
        if workspace_index == self.active_workspace_index:
            logger.warning(
                "window %s already in workspace index %s", window, workspace_index
            )
            return
        # should move all windows
        while window.parent:
            window = window.parent
        self.remove_window(window)
        self.add_window(window, workspace_index=workspace_index)
        self.workspace.arrange()

    def move_floating_window_in(self, window: Window):
        """Move the floating window into the monitor"""
        logger.debug("%s move floating window %s in", self, window)
        wr = window.get_rect()
        mr = self.rect
        if mr.contains(wr.left, wr.top):
            return
        window.set_rect(
            Rect(
                mr.x + mr.width // 4,
                mr.y + mr.height // 4,
                mr.width // 2,
                mr.height // 2,
            )
        )

    def compute_alter_rect(self, workspace_index: int):
        """Compute the alter rect(window would be moved into when workspace is toggled off) for the workspace,
        all alter_rect would be spread over the y axis of the current full_rect()"""
        left = self.rect.left
        top = self.full_rect.bottom + self.rect.height * workspace_index
        right = self.rect.right
        bottom = top + self.rect.height
        return Rect(left, top, right, bottom)
