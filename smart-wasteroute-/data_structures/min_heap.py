"""
data_structures/min_heap.py

A binary MIN HEAP, implemented manually on top of a plain Python list
(array-backed, NOT using Python's built-in `heapq` module - the whole
point of this file is to show the actual heap mechanics for viva).

WHAT IS A MIN HEAP?
    A complete binary tree where every parent node's value is SMALLER
    THAN OR EQUAL TO both of its children's values. This guarantees the
    smallest element is always at the root (index 0), so "find the
    smallest" is O(1) and "remove the smallest" is O(log n).

WHY WE NEED IT HERE:
    Our PriorityQueue (data_structures/priority_queue.py) uses this
    Min Heap internally. Bins are pushed in with a numeric priority
    WEIGHT where a SMALLER number means MORE URGENT (see
    utils/priority_config.py -> CRITICAL = 1, LOW = 4). Because a Min
    Heap always keeps the smallest value at the root, the most urgent
    bin naturally ends up at the top, ready to be extracted first.

ARRAY REPRESENTATION OF THE TREE:
    For a node stored at index i:
        left child index  = 2*i + 1
        right child index = 2*i + 2
        parent index       = (i - 1) // 2
    This lets us store a full binary tree in a flat Python list with
    no pointers/nodes needed - the index arithmetic IS the tree shape.

WHAT EACH HEAP ENTRY LOOKS LIDE:
    We store tuples: (priority, insertion_order, item)
    - priority: the number that determines heap order (smaller = more urgent)
    - insertion_order: a tie-breaker counter. Without this, if two bins
      have the SAME priority, Python would try to compare the `item`
      objects directly (e.g. two Bin objects), which would crash since
      Bin doesn't define < or >. The counter guarantees every tuple is
      comparable and that ties are broken by insertion order (FIFO
      among equal priorities), which is intuitive behaviour.
"""

import itertools


class MinHeap:
    def __init__(self):
        self._heap = []  # list of (priority, order, item) tuples
        self._counter = itertools.count()  # tie-breaker generator

    def is_empty(self):
        return len(self._heap) == 0

    def size(self):
        return len(self._heap)

    def peek(self):
        """
        Look at the smallest-priority item WITHOUT removing it.
        Time: O(1) - it's always at index 0.
        """
        if self.is_empty():
            return None
        priority, _, item = self._heap[0]
        return item, priority

    def insert(self, item, priority):
        """
        Insert a new item with the given priority.
        Time: O(log n) - append then "bubble up" at most tree-height times.
        """
        entry = (priority, next(self._counter), item)
        self._heap.append(entry)
        self._heapify_up(len(self._heap) - 1)

    def extract_min(self):
        """
        Remove and return the item with the smallest priority.
        Time: O(log n).

        Technique: swap root with the LAST element, pop the last
        element off (which is now the old root - O(1) removal from the
        end), then "bubble down" the new root into its correct place.
        """
        if self.is_empty():
            return None

        self._swap(0, len(self._heap) - 1)
        priority, _, item = self._heap.pop()
        if not self.is_empty():
            self._heapify_down(0)
        return item, priority

    def heapify(self, items_with_priorities):
        """
        Build a heap from a list of (item, priority) pairs all at once,
        rather than inserting one at a time.
        Time: O(n) using the standard "heapify from the bottom up"
        technique (this is the classic result: building a heap from
        scratch is O(n), not O(n log n), because most nodes are near
        the bottom and need very few swaps).
        """
        self._heap = [
            (priority, order, item)
            for order, (item, priority) in enumerate(items_with_priorities)
        ]
        self._counter = itertools.count(len(self._heap))  # continue numbering after this
        # Start from the last parent node and heapify-down each one,
        # working backward to the root.
        last_parent = (len(self._heap) - 2) // 2
        for i in range(last_parent, -1, -1):
            self._heapify_down(i)

    def to_sorted_list(self):
        """
        Non-destructive view of all items in priority order (smallest first).
        Time: O(n log n) - repeatedly extracts from a COPY of the heap,
        used only for display purposes (e.g. the Data Structures demo
        page showing "here is the current priority order").
        """
        import copy
        temp = MinHeap()
        temp._heap = copy.deepcopy(self._heap)
        temp._counter = itertools.count()

        result = []
        while not temp.is_empty():
            result.append(temp.extract_min())
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parent(self, i):
        return (i - 1) // 2

    def _left(self, i):
        return 2 * i + 1

    def _right(self, i):
        return 2 * i + 2

    def _swap(self, i, j):
        self._heap[i], self._heap[j] = self._heap[j], self._heap[i]

    def _heapify_up(self, i):
        """Bubble a node up toward the root until the heap property holds."""
        while i > 0 and self._heap[i] < self._heap[self._parent(i)]:
            self._swap(i, self._parent(i))
            i = self._parent(i)

    def _heapify_down(self, i):
        """Bubble a node down toward the leaves until the heap property holds."""
        size = len(self._heap)
        while True:
            smallest = i
            left = self._left(i)
            right = self._right(i)

            if left < size and self._heap[left] < self._heap[smallest]:
                smallest = left
            if right < size and self._heap[right] < self._heap[smallest]:
                smallest = right

            if smallest == i:
                break

            self._swap(i, smallest)
            i = smallest

    def __repr__(self):
        return f"<MinHeap size={self.size()}>"
