"""Virtual Desktop State module"""

import time
import logging
from typing import Dict, Optional, Tuple, Callable, List

from jigsawwm.jmk import sysinout, Vk
from jigsawwm.w32.winevent import WinEvent
from jigsawwm.w32.monitor_detector import MonitorDetector, Monitor
from jigsawwm.w32.window_detector import WindowDetector, Window, HWND

from .monitor_state import MonitorState
from .workspace_state import WorkspaceState
from .const import (
    PREFERRED_MONITOR_INDEX,
    PREFERRED_WORKSPACE_INDEX,
    STATIC_WINDOW_INDEX,
    MONITOR_STATE,
    WORKSPACE_STATE,
)
from .config import WmConfig

logger = logging.getLogger(__name__)


class VirtDeskState:
    """VirtDeskState holds variables needed by a Virtual Desktop

    :param WindowManager manager: associated WindowManager
    :param bytearray desktop_id: virtual desktop id
    """

    desktop_id: bytearray
    config: WmConfig
    monitor_states: Dict[Monitor, MonitorState] = {}
    active_monitor_index: int = 0
    window_detector: WindowDetector
    monitor_detector: MonitorDetector
    _wait_mouse_released: bool = False
    _previous_switch_workspace_for_window_activation = 0.0

    def __init__(self, desktop_id: bytearray, config: WmConfig):
        self.desktop_id = desktop_id
        self.window_detector = WindowDetector()
        self.monitor_detector = MonitorDetector()
        self.config = config

    def sync_monitors(self):
        """Syncs the monitor states with the virtual desktop"""
        result = self.monitor_detector.detect_monitor_changes()
        if not result.changed:
            logger.info("no monitor changes detected")
            return
        windows_tobe_rearranged = set()
        # process new monitors
        if result.new_monitors:
            windows_tobe_rearranged = self.window_detector.windows
            for m in result.new_monitors:
                monitor_index = self.monitor_detector.monitors.index(m)
                logger.info("new monitor connected: %s index: %d", m, monitor_index)
                self.monitor_states[m] = MonitorState(
                    monitor_index,
                    m.name,
                    self.config.workspace_names,
                    m.get_work_rect(),
                    self.config.get_theme_for_monitor(m),
                )
        # remove monitor states
        if result.removed_monitors:
            for m in result.removed_monitors:
                ms = self.monitor_states.pop(m)
                logger.info("monitor disconnected: %s", ms.monitor)
                for ws in ms.workspaces:
                    windows_tobe_rearranged |= ws.windows
        # rearrange windows
        if windows_tobe_rearranged:
            for w in windows_tobe_rearranged:
                m = self.monitor_detector.monitors[
                    w.attrs.get(PREFERRED_MONITOR_INDEX, 0)
                    % len(self.monitor_detector.monitors)
                ]
                monitor_state = self.monitor_states[m]
                monitor_state.add_windows(w)
            for ms in self.monitor_states.values():
                ms.workspace.sync_windows()

    def sync_windows(self):
        """Syncs the window states with the virtual desktop"""
        if not self.monitor_states:
            logger.warning("no monitors found")
            return
        result = self.window_detector.detect_window_changes()
        if not result.changed:
            logger.info("no window changes detected")
            return
        # handle new windows
        if result.new_windows:
            for w in result.new_windows:
                logger.info("new window appeared: %s", w)
                self.apply_rule_to_window(w)
                if PREFERRED_MONITOR_INDEX not in w.attrs:
                    logger.debug(
                        "window %s has no preferred monitor index, set it to ",
                        self.active_monitor_index,
                    )
                    w.attrs[PREFERRED_MONITOR_INDEX] = self.active_monitor_index
                monitor_state = self.monitor_state_from_index(
                    w.attrs[PREFERRED_MONITOR_INDEX]
                )
                monitor_state.add_windows(w)
        # handle removed windows
        if result.removed_windows:
            logger.info("window disappeared: %s", result.removed_windows)
            for w in result.removed_windows:
                monitor_state: MonitorState = w.attrs[MONITOR_STATE]
                monitor_state.remove_windows(w)
        for ms in self.monitor_states.values():
            ms.workspace.sync_windows()

    def apply_rule_to_window(self, window: Window) -> bool:
        """Check if window is to be tilable"""
        rule = self.config.find_rule_for_window(window)
        if rule:
            logger.info("applying rule %s on %s", rule, window)
            if rule.manageable is not None:
                window.manageable = rule.manageable
            if rule.tilable is not None:
                window.tilable = rule.tilable
            if rule.preferred_monitor_index is not None:
                window.attrs[PREFERRED_MONITOR_INDEX] = (
                    rule.preferred_monitor_index % len(self.monitor_detector.monitors)
                )
            if rule.preferred_workspace_index is not None:
                window.attrs[PREFERRED_WORKSPACE_INDEX] = rule.preferred_workspace_index
            if rule.static_window_index is not None:
                window.attrs[STATIC_WINDOW_INDEX] = rule.static_window_index

    def on_window_event(self, event: WinEvent, hwnd: Optional[HWND] = None):
        """Check if we need to sync windows for given window event"""
        # ignore if left mouse button is pressed in case of dragging
        if (
            not self._wait_mouse_released
            and event == WinEvent.EVENT_OBJECT_PARENTCHANGE
            and sysinout.state.get(Vk.LBUTTON)  # assuming JMK is enabled...
        ):
            # delay the sync until button released to avoid flickering
            self._wait_mouse_released = True
            return False
        elif self._wait_mouse_released:
            if not sysinout.state.get(Vk.LBUTTON):
                self._wait_mouse_released = False
            else:
                return False
        if not hwnd:
            return False
        window = self.window_detector.get_window(hwnd)
        if not window.manageable:
            return False
        workspace_state: WorkspaceState = window.attrs.get(WORKSPACE_STATE)
        # # filter by event
        if event == WinEvent.EVENT_SYSTEM_FOREGROUND:
            self.try_switch_workspace_for_window_activation(window)
            return False
        if (
            event == WinEvent.EVENT_OBJECT_HIDE
            or event == WinEvent.EVENT_OBJECT_SHOW
            or event == WinEvent.EVENT_OBJECT_UNCLOAKED
        ):
            pass
        elif event == WinEvent.EVENT_SYSTEM_MOVESIZEEND:
            if self.try_swapping_window(window):
                return False
            workspace_state.restrict()
            return False
        elif (
            event == WinEvent.EVENT_SYSTEM_MINIMIZESTART
            or event == WinEvent.EVENT_SYSTEM_MINIMIZEEND
        ):
            ws: WorkspaceState = window.attrs[WORKSPACE_STATE]
            ws.sync_windows()
            return False
        else:
            if event not in (
                WinEvent.EVENT_OBJECT_LOCATIONCHANGE,
                WinEvent.EVENT_OBJECT_NAMECHANGE,
                # WinEvent.EVENT_OBJECT_CREATE,
                WinEvent.EVENT_SYSTEM_MENUSTART,
                WinEvent.EVENT_SYSTEM_MENUEND,
                WinEvent.EVENT_OBJECT_REORDER,
                WinEvent.EVENT_SYSTEM_CAPTURESTART,
                WinEvent.EVENT_SYSTEM_CAPTUREEND,
            ):
                # do NOT inspect Window instance here, would crash the app
                # logger.debug("ignore winevent %s for window %s", event.name, hwnd)
                pass
            return False

        logger.info("!!! REACT on event %s for window %s", event.name, hwnd)
        self.sync_windows()

    def try_switch_workspace_for_window_activation(self, window: Window):
        """Try to switch workspace for window activation"""
        # a window belongs to hidden workspace just got activated
        # put your default browser into workspace and then ctrl-click a link, e.g. http://google.com
        now = time.time()
        elapsed = now - self._previous_switch_workspace_for_window_activation
        if elapsed < 1:
            # child windows got spread across multiple workspaces
            logger.warning("workspace switching happened too frequently, possible loop")
            return
        if MONITOR_STATE not in window.attrs or window.manageable is False:
            return
        monitor_state: MonitorState = window.attrs[MONITOR_STATE]
        workspace_state: WorkspaceState = window.attrs[WORKSPACE_STATE]
        if not workspace_state.showing:
            self._previous_switch_workspace_for_window_activation = now
            monitor_state.switch_workspace(workspace_state.index)
            logger.info(
                "switch to workspace %s due window %s got activated",
                workspace_state,
                window,
            )

    def try_swapping_window(
        self, window: Window
    ) -> Optional[Tuple[Window, MonitorState]]:
        """Check if the window is being reordered"""
        logger.info("try swapping windows")
        if not window.manageable:
            return
        # when dragging chrome tab into a new window, the window will not have MONITOR_STATE
        monitor_state: MonitorState = window.attrs[MONITOR_STATE]
        target_monitor_state = self.monitor_state_from_cursor()
        # window being dragged to another monitor
        if target_monitor_state != monitor_state:
            logger.debug("move window %s to another monitor", window)
            monitor_state.remove_windows(window)
            target_monitor_state.add_windows(window)
            window.attrs[PREFERRED_MONITOR_INDEX] = target_monitor_state.index
            monitor_state.workspace.sync_windows()
            target_monitor_state.workspace.sync_windows()
            return True
        if not window.tilable:
            return False
        target_window = self.window_detector.window_restricted_at_cursor()
        if not target_window or target_window == window:
            return False
        window_index = monitor_state.workspace.tiling_windows.index(window)
        target_window_index = target_monitor_state.workspace.tiling_windows.index(
            target_window
        )
        # swap
        a = monitor_state.workspace
        b = target_monitor_state.workspace
        a.tiling_windows[window_index], b.tiling_windows[target_window_index] = (
            target_window,
            window,
        )
        a.windows.remove(window)
        a.windows.add(target_window)
        b.windows.add(window)
        b.windows.remove(target_window)
        a = window.restricted_rect
        if a is None:
            raise ValueError(f"window has no restricted rect: {window}")
        b = target_window.restricted_rect
        if b is None:
            raise ValueError(f"target window has no restricted rect: {target_window}")
        window.set_restrict_rect(b)
        target_window.set_restrict_rect(a)
        window.attrs[PREFERRED_MONITOR_INDEX] = target_monitor_state.index
        target_window.attrs[PREFERRED_MONITOR_INDEX] = monitor_state.index
        return True

    def monitor_state_from_cursor(self) -> MonitorState:
        """Retrieve monitor_state from current cursor"""
        return self.monitor_states[self.monitor_detector.monitor_from_cursor()]

    def monitor_state_from_window(self, window: Window) -> MonitorState:
        """Retrieve monitor_state from window"""
        return self.monitor_states[
            self.monitor_detector.monitor_from_window(window.handle)
        ]

    def monitor_state_from_index(self, index: int) -> MonitorState:
        """Retrieve monitor_state from index"""
        if index >= len(self.monitor_detector.monitors):
            raise IndexError("monitor index out of range")
        return self.monitor_states[self.monitor_detector.monitors[index]]

    def reorder(self, reorderer: Callable[[List[Window], int], None]):
        """Reorder windows"""
        window = self.window_detector.foreground_window()
        if not window.manageable or not window.tilable:
            return
        workspace_state: WorkspaceState = window.attrs[WORKSPACE_STATE]
        if len(workspace_state.tiling_windows) < 2:
            return
        next_active_window = reorderer(
            workspace_state.tiling_windows, workspace_state.tiling_windows.index(window)
        )
        workspace_state.arrange()
        (next_active_window or window).activate()

    def move_to_monitor(self, delta: int):
        """Move window to another monitor"""
        if len(self.monitor_detector.monitors) < 2:
            return
        window = self.window_detector.foreground_window()
        if not window.manageable or not window.tilable:
            return
        monitor_state: MonitorState = window.attrs[MONITOR_STATE]
        preferred_monitor_index = (monitor_state.monitor.index + delta) % len(
            self.monitor_detector.monitors
        )
        window.attrs[PREFERRED_MONITOR_INDEX] = preferred_monitor_index
        target_monitor_state = self.monitor_state_from_index(preferred_monitor_index)
        monitor_state.remove_windows(window)
        target_monitor_state.add_windows(window)
        monitor_state.workspace.sync_windows()
        target_monitor_state.sync_windows()

    def toggle_tilable(self):
        """Toggle window tilable"""
        window = self.window_detector.foreground_window()
        window.tilable = not window.tilable
        workspace_state: WorkspaceState = window.attrs[WORKSPACE_STATE]
        workspace_state.sync_windows()
