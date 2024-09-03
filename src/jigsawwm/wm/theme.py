from dataclasses import dataclass
from typing import Optional

from jigsawwm.tiler.tilers import *
from jigsawwm.w32.monitor import Monitor


@dataclass
class Theme:
    """Theme is a set of preference packed together for users to switch easily,
    typically, it consists of a LayoutTiler, Gap between windows and
    other options.
    """

    # name of the theme
    name: str
    # layout tiler
    layout_tiler: LayoutTiler
    static_layout: bool = False
    max_tiling_areas: int = 0
    # unused
    icon_name: Optional[str] = None
    # unused
    icon_path: Optional[str] = None
    # new appeared window would be prepended to the list if the option was set to True
    new_window_as_master: Optional[bool] = None
    # gap between windows / monitor edges
    gap: Optional[int] = 0
    # forbid
    strict: Optional[bool] = None
    affinity_index: Optional[Callable[[Monitor], int]] = None
    stacking_margin_x: float = 0.1
    stacking_margin_y: float = 0.1
    stacking_window_width: float = 0.8
    stacking_window_height: float = 0.8
    stacking_max_step: int = 30
