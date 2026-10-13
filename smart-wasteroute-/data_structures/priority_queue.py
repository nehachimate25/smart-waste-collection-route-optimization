"""
data_structures/priority_queue.py

PriorityQueue - a genuine priority queue, backed internally by our own
MinHeap (data_structures/min_heap.py). This is NOT a sorted list that
we re-sort on every push - that would be O(n log n) per insertion.
Using a heap underneath gives O(log n) insert and O(log n) removal,
which is the whole reason heaps exist.

WHAT IT'S USED FOR IN THIS PROJECT:
    Bins waiting for collection are pushed in with a priority WEIGHT
    (see utils/priority_config.get_priority_weight - CRITICAL=1 is the
    most urgent, LOW=4 is the least). pop() always returns the most
    urgent bin first, e.g.:

        Bin B -> 95% -> CRITICAL  (popped first)
        Bin C -> 88% -> HIGH
        Bin A -> 72% -> MEDIUM
        Bin D -> 30% -> LOW       (popped last)
"""

from data_structures.min_heap import MinHeap


class PriorityQueue:
    def __init__(self):
        self._heap = MinHeap()

    def is_empty(self):
        return self._heap.is_empty()

    def size(self):
        return self._heap.size()

    def push(self, item, priority):
        """
        Add an item with a given priority (lower number = collected sooner).
        Time: O(log n).
        """
        self._heap.insert(item, priority)

    def pop(self):
        """
        Remove and return the (item, priority) with the highest urgency
        (i.e. the smallest priority number).
        Time: O(log n).
        Returns None if the queue is empty.
        """
        return self._heap.extract_min()

    def peek(self):
        """
        Look at the most urgent (item, priority) without removing it.
        Time: O(1).
        """
        return self._heap.peek()

    def build_from_list(self, items_with_priorities):
        """
        Bulk-load the priority queue from a list of (item, priority)
        pairs in one O(n) operation - used when we already have a full
        batch of pending bins ready to be prioritized at once (e.g.
        when route_service starts building a new route).
        """
        self._heap.heapify(items_with_priorities)

    def view_priority_order(self):
        """
        Non-destructive view of all (item, priority) pairs in priority
        order, without emptying the queue. Used by the Data Structures
        demo page and the Collection Requests page to display the
        current priority order to the user.
        """
        return self._heap.to_sorted_list()

    def __repr__(self):
        return f"<PriorityQueue size={self.size()}>"
