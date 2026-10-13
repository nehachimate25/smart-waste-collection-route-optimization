"""
data_structures/stack.py

Stack - a Last-In-First-Out (LIFO) data structure.

WHAT IT'S USED FOR IN THIS PROJECT:
    As route_service.py builds a collection route and a vehicle visits
    each stop (depot -> Bin B -> Bin C -> ... -> depot), every visited
    stop is PUSHED onto this Stack. This gives us:

        1. "Recently visited locations" - peek()/to_list() show the
           most recent stops first, useful for a live "route history"
           display while a route is being built.
        2. "Undo the most recent route operation" - if the last stop
           was added by mistake (e.g. wrong bin selected), pop() removes
           exactly that last operation and nothing else, which is the
           natural behaviour a Stack gives for free and a Queue could
           NOT give cleanly (a Queue would remove the OLDEST stop, not
           the most recent one - which is why this project uses a
           Stack here and a Queue for pending requests instead).

    We do NOT use this Stack for anything without a genuine purpose
    (per the project spec's "Do not create a Stack feature that has no
    purpose" instruction) - it exists specifically for this history/undo
    behaviour, nothing else.

IMPLEMENTATION NOTE:
    Backed by a plain Python list, using append()/pop() from the END
    of the list - both O(1) operations, since no shifting of other
    elements is required (unlike removing from the FRONT of a list,
    which would be O(n)).
"""


class Stack:
    def __init__(self):
        self._items = []

    def is_empty(self):
        return len(self._items) == 0

    def size(self):
        return len(self._items)

    def push(self, item):
        """
        Add an item to the TOP of the stack.
        Time: O(1) - appending to the end of a Python list is amortized O(1).
        """
        self._items.append(item)

    def pop(self):
        """
        Remove and return the item at the TOP of the stack (the most
        recently pushed item) - this is what powers "undo the most
        recent route operation".
        Time: O(1).
        Returns None if the stack is empty.
        """
        if self.is_empty():
            return None
        return self._items.pop()

    def peek(self):
        """
        Look at the top item WITHOUT removing it.
        Time: O(1).
        """
        if self.is_empty():
            return None
        return self._items[-1]

    def to_list(self, most_recent_first=True):
        """
        Non-destructive view of the stack's contents, used for
        displaying "route history" on screen.
        Time: O(n).

        Args:
            most_recent_first: if True (default), the most recently
                pushed item appears first in the returned list - this
                matches how a "history" list is normally read by a user
                (newest at the top).
        """
        if most_recent_first:
            return list(reversed(self._items))
        return list(self._items)

    def __repr__(self):
        return f"<Stack top->bottom = {list(reversed(self._items))}>"
