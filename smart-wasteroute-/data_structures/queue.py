"""
data_structures/queue.py

Queue - a First-In-First-Out (FIFO) data structure.

WHAT IT'S USED FOR IN THIS PROJECT:
    When a bin needs collection (either reported manually, or detected
    automatically because its waste_level crossed a threshold), it is
    first ENQUEUED here as a "pending collection request" - in the
    order the requests arrive.

    This Queue is deliberately kept SEPARATE from the Priority Queue:
        Queue          = "these requests arrived, in this order"
        Priority Queue = "of the pending requests, which is most urgent"

    route_service.py (built in a later step) drains this Queue and
    pushes each request into the Priority Queue for urgency evaluation.
    This two-stage design (Queue -> Priority Queue) is exactly what
    Section 30 of the spec asks for and gives a clean, honest reason
    for BOTH structures to exist in the same project.

IMPLEMENTATION NOTE:
    Internally backed by collections.deque, which gives true O(1)
    enqueue/dequeue at both ends (a plain Python list would be O(n)
    for dequeue from the front, since every remaining element would
    have to shift left). We wrap it in our own class rather than
    exposing deque directly so the operations are named the way this
    project's spec describes them (enqueue/dequeue/front) and so the
    Data Structures demo page has a clean, dedicated class to point at.
"""

from collections import deque


class Queue:
    def __init__(self):
        self._items = deque()

    def is_empty(self):
        return len(self._items) == 0

    def size(self):
        return len(self._items)

    def enqueue(self, item):
        """
        Add an item to the REAR of the queue.
        Time: O(1).
        """
        self._items.append(item)

    def dequeue(self):
        """
        Remove and return the item at the FRONT of the queue.
        Time: O(1).
        Returns None if the queue is empty (caller should check
        is_empty() first if that distinction matters).
        """
        if self.is_empty():
            return None
        return self._items.popleft()

    def front(self):
        """
        Look at the item at the front WITHOUT removing it.
        Time: O(1).
        """
        if self.is_empty():
            return None
        return self._items[0]

    def to_list(self):
        """
        Non-destructive view of the queue, front to rear.
        Used for display purposes (e.g. the Collection Requests page
        showing "Pending Requests" in arrival order) without disturbing
        the actual queue contents.
        Time: O(n).
        """
        return list(self._items)

    def __repr__(self):
        return f"<Queue front->rear = {list(self._items)}>"
