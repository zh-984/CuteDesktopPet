"""Route sprite anchors through real display edges, even on mixed-DPI desktops."""

from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRect


@dataclass(frozen=True)
class Display:
    name: str
    logical: QRect
    physical: QRect

    def to_physical(self, point):
        return QPointF(self.physical.x() + (point.x() - self.logical.x()) * self.physical.width() / self.logical.width(),
                       self.physical.y() + (point.y() - self.logical.y()) * self.physical.height() / self.logical.height())

    def to_logical(self, point):
        return QPointF(self.logical.x() + (point.x() - self.physical.x()) * self.logical.width() / self.physical.width(),
                       self.logical.y() + (point.y() - self.physical.y()) * self.logical.height() / self.physical.height())


def match_windows_display(logical, scale, physical_rects):
    # Qt reports a monitor's model name, which can differ from the Win32 device ID
    # and be identical for two displays. On Windows Qt preserves the native origin.
    candidates = [name for name, (x, y, width, height) in physical_rects.items()
                  if (x, y) == (logical.x(), logical.y())
                  and abs(width - logical.width() * scale) <= max(2, scale)
                  and abs(height - logical.height() * scale) <= max(2, scale)]
    return candidates[0] if len(candidates) == 1 else None


def display_at(displays, point, *, physical):
    """Prefer the screen containing the point, otherwise its nearest edge."""
    def distance(display):
        rect = display.physical if physical else display.logical
        dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
        dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
        return dx * dx + dy * dy

    return min(displays, key=distance)


def _shared_edge(source, target):
    """Return the shared span and the first coordinate inside the neighbor."""
    low, high = max(source.top(), target.top()), min(source.bottom(), target.bottom())
    if low <= high:
        if source.right() + 1 == target.left():
            return True, target.left(), low, high
        if target.right() + 1 == source.left():
            return True, target.right(), low, high
    low, high = max(source.left(), target.left()), min(source.right(), target.right())
    if low <= high:
        if source.bottom() + 1 == target.top():
            return False, target.top(), low, high
        if target.bottom() + 1 == source.top():
            return False, target.bottom(), low, high
    return None


class DesktopLayout:
    def __init__(self, displays):
        self.displays = {display.name: display for display in displays}
        self.edges = {
            source.name: {target.name: edge for target in displays if target is not source
                          if (edge := _shared_edge(source.physical, target.physical)) is not None}
            for source in displays
        }

    def next_waypoint(self, start, goal):
        source = display_at(self.displays.values(), start, physical=True).name
        target = display_at(self.displays.values(), goal, physical=True).name
        if source == target:
            return goal
        queue = deque([(source, None)])
        seen = {source}
        while queue:
            current, first_edge = queue.popleft()
            for neighbor, edge in self.edges[current].items():
                if neighbor in seen:
                    continue
                entrance = first_edge or edge
                if neighbor == target:
                    horizontal, crossing, low, high = entrance
                    toward = goal.y() if horizontal else goal.x()
                    shared = max(low, min(toward, high))
                    return QPointF(crossing, shared) if horizontal else QPointF(shared, crossing)
                seen.add(neighbor)
                queue.append((neighbor, entrance))
        # Disconnected layouts have no continuous visible route.
        return goal
