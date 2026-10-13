"""
data_structures/graph.py

Graph data structure, implemented using an ADJACENCY LIST.

WHAT IT REPRESENTS IN THIS PROJECT:
    Vertex = a location (the Depot, or a waste Bin)
    Edge   = a road/path between two locations
    Weight = the geographic distance between them (in km)

WHY ADJACENCY LIST (not Adjacency Matrix)?
    Our graph is SPARSE - a depot with 5-10 bins does not need an edge
    between every possible pair of locations, only the ones that are
    actually relevant to route-building. An adjacency list only stores
    edges that exist, giving:
        Space:  O(V + E)   instead of O(V^2) for a matrix
        Get neighbors of a vertex: O(1) average (dict lookup) + O(k)
                                     to iterate its k neighbors
    For 5-10 bins this difference is small in absolute terms, but it is
    the textbook-correct choice and is easy to justify in viva.

INTERNAL REPRESENTATION:
    self.adjacency_list = {
        "Depot":  {"Bin A": 2.4, "Bin B": 3.1},
        "Bin A":  {"Depot": 2.4, "Bin C": 1.2},
        "Bin B":  {"Depot": 3.1},
        "Bin C":  {"Bin A": 1.2},
    }
    Each vertex maps to a dict of {neighbor: weight}. Using a dict
    (hash table) for the neighbor list itself also gives O(1) average
    edge-weight lookup between any two known-adjacent vertices.

This graph is UNDIRECTED by default (a road between two points can be
travelled in both directions) - add_edge() inserts both directions
unless directed=True is passed.

NO EXTERNAL LIBRARIES: this class does not use NetworkX or any other
graph library. Every operation below is implemented manually.
"""

from collections import deque


class Graph:
    def __init__(self):
        # vertex_name -> { neighbor_name: weight, ... }
        self.adjacency_list = {}

        # vertex_name -> arbitrary data payload (e.g. lat/lon, or a Bin object)
        # Kept separate from adjacency_list so the adjacency structure
        # itself stays clean and purely about connectivity/weights.
        self.vertex_data = {}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add_vertex(self, vertex, data=None):
        """
        Add a vertex (location) to the graph.
        Time: O(1) average (dict insertion).
        If the vertex already exists, its data is updated but its
        existing edges are preserved (so re-adding a bin after an
        update doesn't wipe its connections).
        """
        if vertex not in self.adjacency_list:
            self.adjacency_list[vertex] = {}
        self.vertex_data[vertex] = data

    def add_edge(self, source, destination, weight, directed=False):
        """
        Add an edge between two vertices with the given weight.
        Time: O(1) average.
        Automatically adds the vertices if they don't already exist,
        so callers don't need to call add_vertex() first every time.
        """
        if source not in self.adjacency_list:
            self.add_vertex(source)
        if destination not in self.adjacency_list:
            self.add_vertex(destination)

        self.adjacency_list[source][destination] = weight
        if not directed:
            self.adjacency_list[destination][source] = weight

    def get_neighbors(self, vertex):
        """
        Return {neighbor: weight} for the given vertex.
        Time: O(1) average lookup + the dict itself has O(k) entries
        where k is that vertex's degree.
        """
        return self.adjacency_list.get(vertex, {})

    def get_weight(self, source, destination):
        """Return the edge weight between two vertices, or None if no edge exists."""
        return self.adjacency_list.get(source, {}).get(destination)

    def has_vertex(self, vertex):
        return vertex in self.adjacency_list

    def has_edge(self, source, destination):
        return destination in self.adjacency_list.get(source, {})

    def get_vertices(self):
        """List of all vertex names. Time: O(V)."""
        return list(self.adjacency_list.keys())

    def get_vertex_data(self, vertex):
        return self.vertex_data.get(vertex)

    def remove_vertex(self, vertex):
        """
        Remove a vertex and every edge pointing to it.
        Time: O(V) - must scan every other vertex's neighbor dict to
        remove the back-reference (there's no cheaper way without
        maintaining a reverse index, which isn't needed at this scale).
        """
        if vertex not in self.adjacency_list:
            return
        del self.adjacency_list[vertex]
        self.vertex_data.pop(vertex, None)
        for neighbors in self.adjacency_list.values():
            neighbors.pop(vertex, None)

    def vertex_count(self):
        return len(self.adjacency_list)

    def edge_count(self):
        """Counts each undirected edge once."""
        total = sum(len(neighbors) for neighbors in self.adjacency_list.values())
        return total // 2

    # ------------------------------------------------------------------
    # Traversal (used for connectivity checks / error handling -
    # e.g. detecting a "disconnected graph" as required in Section 26)
    # ------------------------------------------------------------------

    def bfs(self, start_vertex):
        """
        Breadth-First Search from start_vertex.
        Time: O(V + E) - every vertex and edge is visited at most once.
        Uses a Queue (Python's deque here; our own Queue class from
        data_structures/queue.py is used instead wherever we want to
        visibly demonstrate OUR Queue implementation, e.g. on the
        Data Structures demo page).
        Returns the list of vertices in the order they were visited.
        """
        if start_vertex not in self.adjacency_list:
            return []

        visited = set()
        order = []
        q = deque([start_vertex])
        visited.add(start_vertex)

        while q:
            current = q.popleft()
            order.append(current)
            for neighbor in self.adjacency_list[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    q.append(neighbor)

        return order

    def is_connected(self):
        """
        Check whether every vertex is reachable from an arbitrary
        starting vertex. Used to detect a disconnected graph before
        route-building (e.g. a bin with no path back to the depot).
        Time: O(V + E).
        """
        if not self.adjacency_list:
            return True  # an empty graph is trivially connected
        start = next(iter(self.adjacency_list))
        visited_count = len(self.bfs(start))
        return visited_count == self.vertex_count()

    # ------------------------------------------------------------------
    # Demonstration helper
    # ------------------------------------------------------------------

    def to_display_dict(self):
        """
        A clean {vertex: [(neighbor, weight), ...]} structure, used by
        the /api and Data Structures demo page to show the adjacency
        list exactly as described in the project spec's example:
            Depot
             |-- Bin A : 2.4 km
             |-- Bin B : 3.1 km
        """
        return {
            vertex: sorted(neighbors.items(), key=lambda item: item[1])
            for vertex, neighbors in self.adjacency_list.items()
        }

    def __repr__(self):
        return f"<Graph vertices={self.vertex_count()} edges={self.edge_count()}>"
