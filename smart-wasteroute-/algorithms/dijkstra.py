"""
algorithms/dijkstra.py

Dijkstra's Shortest Path Algorithm - a SUPPORTING ALGORITHM that
operates ON TOP OF our Graph data structure. Dijkstra is NOT itself a
data structure - it is a procedure that uses two data structures we
already built:
    - Graph (data_structures/graph.py)          - to know which
      locations connect to which, and at what distance.
    - MinHeap (data_structures/min_heap.py)     - to always expand the
      currently-closest unvisited location next, efficiently.
    - Stack (data_structures/stack.py)          - reused here to
      reconstruct the final path by backtracking (see
      reconstruct_path() below) - a natural, genuine use of the Stack,
      not a forced one.

WHY DIJKSTRA IS ONLY A SUPPORTING FEATURE (per project spec):
    The main route-building logic (a later step) uses the Priority
    Queue to decide COLLECTION ORDER (which bin is most urgent), not
    Dijkstra. Dijkstra is offered as a SEPARATE, OPTIONAL feature: "what
    is the shortest path between any two points in the network?" - useful
    for the Data Structures demo page and for answering a one-off
    question, but it is not what decides the day-to-day collection route.

NO EXTERNAL LIBRARIES:
    This does not use NetworkX, Google Maps' routing, or Python's
    heapq. It uses OUR MinHeap, exactly the same class the Priority
    Queue is built on - which is itself worth pointing out in viva:
    the same Min Heap data structure powers two different features.

ALGORITHM (informal):
    1. Set distance to the start vertex = 0, all others = infinity.
    2. Push the start vertex into a MinHeap keyed by current known distance.
    3. Repeatedly extract the vertex with the smallest known distance.
       If we've already finalized it, skip (this can happen because we
       don't support decrease-key in our MinHeap - see note below).
    4. For each of its neighbors, if going through the current vertex
       gives a SHORTER distance than what we know so far, update it
       ("relax" the edge) and push the neighbor into the heap with its
       new distance.
    5. Repeat until the heap is empty. Every vertex now holds its
       shortest distance from the start.

NOTE ON "LAZY DELETION":
    A textbook-optimal Dijkstra uses a heap that supports decrease-key.
    Our MinHeap (built in Step 5) does not implement decrease-key,
    because adding it would meaningfully complicate that class for a
    feature only Dijkstra needs. Instead we use the standard, widely
    taught workaround: when a shorter distance to a vertex is found,
    we simply INSERT a new entry into the heap rather than updating the
    old one, and skip over any already-visited vertex if it's popped
    again later ("lazy deletion"). This keeps correctness identical to
    the optimal version, at the cost of the heap doing a bit more work
    in the presence of many relaxations - for this project's graph
    size (<=11 vertices), the difference is not measurable.

COMPLEXITY:
    Time:  O((V + E) log V) - each edge can cause one heap insertion
           (O(log V)), and we do this across all E edges, plus the
           initial insertion of V vertices.
    Space: O(V) for the distances/previous dictionaries, plus O(E) in
           the worst case for extra heap entries from lazy deletion.
"""

from data_structures.min_heap import MinHeap
from data_structures.stack import Stack


def dijkstra(graph, start):
    """
    Run Dijkstra's algorithm from a single start vertex.

    Args:
        graph: a data_structures.graph.Graph instance.
        start: the vertex name to start from (must exist in the graph).

    Returns:
        A dict with:
            "distances": {vertex: shortest_distance_from_start}
                         (float('inf') if unreachable)
            "previous":  {vertex: the vertex right before it on the
                          shortest path from start, or None}
            "visited_order": list of vertices in the order they were
                          FINALIZED (useful for the demo page to show
                          "visited nodes" step by step)
    """
    if not graph.has_vertex(start):
        raise ValueError(f"Start vertex '{start}' does not exist in the graph")

    distances = {v: float("inf") for v in graph.get_vertices()}
    previous = {v: None for v in graph.get_vertices()}
    distances[start] = 0

    visited = set()
    visited_order = []

    heap = MinHeap()
    heap.insert(start, 0)

    while not heap.is_empty():
        current, current_dist = heap.extract_min()

        # Lazy deletion: this vertex may have been pushed multiple
        # times with different distances (see note above). Once it has
        # been finalized once, any later pop of it is stale - skip it.
        if current in visited:
            continue
        visited.add(current)
        visited_order.append(current)

        for neighbor, weight in graph.get_neighbors(current).items():
            if neighbor in visited:
                continue
            new_dist = current_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                previous[neighbor] = current
                heap.insert(neighbor, new_dist)

    return {
        "distances": distances,
        "previous": previous,
        "visited_order": visited_order,
    }


def reconstruct_path(previous, start, destination):
    """
    Rebuild the shortest path from start to destination using the
    'previous' map produced by dijkstra().

    IMPLEMENTATION USES OUR OWN STACK:
    Backtracking naturally walks from destination -> ... -> start
    (backwards), but we want to DISPLAY the path forwards (start -> ...
    -> destination). Pushing each node onto a Stack while walking
    backwards, then popping everything off, is exactly what a Stack is
    for - it reverses the order for us for free, and reuses the exact
    Stack class from data_structures/stack.py instead of just calling
    list.reverse().

    Returns:
        A list of vertex names from start to destination (inclusive),
        or an empty list if no path exists.
    """
    if destination not in previous:
        return []

    path_stack = Stack()
    current = destination

    # Walk backwards from destination to start, pushing each step.
    while current is not None:
        path_stack.push(current)
        if current == start:
            break
        current = previous[current]
    else:
        # Loop completed without hitting `break`, meaning we ran off
        # the end (current became None) before reaching start - no path exists.
        return []

    # Confirm we actually reached the start vertex (not just ran out of previous links)
    if path_stack.peek() != start:
        return []

    # Pop everything off - this naturally reverses backward order into forward order.
    path = []
    while not path_stack.is_empty():
        path.append(path_stack.pop())

    return path


def shortest_path(graph, start, destination):
    """
    Convenience wrapper combining dijkstra() + reconstruct_path() into
    the exact shape the UI demonstration (Section 17 of the spec) needs:
        Start:
        Destination:
        Shortest Distance:
        Path:
        Visited Nodes:

    Returns a dict with keys: start, destination, distance, path,
    visited_nodes, reachable (bool).
    """
    result = dijkstra(graph, start)
    distance = result["distances"].get(destination, float("inf"))
    reachable = distance != float("inf")

    path = reconstruct_path(result["previous"], start, destination) if reachable else []

    return {
        "start": start,
        "destination": destination,
        "distance": distance if reachable else None,
        "path": path,
        "visited_nodes": result["visited_order"],
        "reachable": reachable,
    }
