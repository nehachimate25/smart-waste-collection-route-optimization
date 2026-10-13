"""
data_structures/hash_table.py

A custom HASH TABLE, implemented manually with SEPARATE CHAINING for
collision handling. This exists specifically for the Data Structures
demonstration page, so we have a real, inspectable hash table (with a
visible hash function, bucket array, and collision behaviour) rather
than just pointing at Python's opaque built-in dict.

WHAT IT'S USED FOR IN THIS PROJECT:
    Fast lookup of a Bin or Vehicle by its string ID:
        "BIN001" -> Bin object
        "BIN002" -> Bin object
        "VEH001" -> Vehicle object
    Without a hash table, finding a bin by ID would mean scanning every
    bin in a list - O(n). A hash table gives O(1) average lookup.

IMPORTANT - THIS FILE vs. PYTHON'S dict:
    The LIVE application (services/bin_service.py, vehicle_service.py)
    uses Python's built-in `dict` for these lookups in normal
    operation, because dict IS a hash table internally (CPython
    implements it with open addressing) and re-implementing our own
    for every real lookup in the app would be needless overhead for
    zero benefit. This HashTable class is the one used specifically on
    the Data Structures demo page, where the goal is to SHOW the
    mechanics (hash function, bucket index, chaining) that Python's
    dict normally hides from view. Both are legitimately "the hash
    table data structure" - one is hand-built for teaching purposes,
    the other is the production-grade version doing the same job.

HOW THE HASH FUNCTION WORKS:
    We use a simple polynomial rolling hash over the characters of the
    key, then take it modulo the number of buckets:

        hash(key) = ( sum( ord(char) * 31^i ) ) % num_buckets

    This is the same style of hash function used internally by Java's
    String.hashCode() - easy to explain in viva, and spreads keys
    reasonably evenly across buckets.

COLLISION HANDLING - SEPARATE CHAINING:
    Each bucket holds a LIST of (key, value) pairs instead of a single
    value. If two different keys hash to the same bucket index (a
    "collision"), both are simply appended to that bucket's list and
    distinguished by comparing the actual key during lookup. This is
    simpler to implement correctly than open addressing and is the
    standard first hash table design taught in a DSA course.
"""


class HashTable:
    def __init__(self, num_buckets=16):
        self.num_buckets = num_buckets
        # Each bucket is a list of [key, value] pairs (separate chaining)
        self.buckets = [[] for _ in range(num_buckets)]
        self._count = 0  # total number of key-value pairs stored

    def _hash(self, key):
        """
        Compute the bucket index for a given key using a polynomial
        rolling hash. Time: O(k) where k = length of the key string
        (effectively O(1) since bin/vehicle IDs are short, fixed-ish
        length strings like "BIN001").
        """
        key = str(key)
        hash_value = 0
        for i, char in enumerate(key):
            hash_value += ord(char) * (31 ** i)
        return hash_value % self.num_buckets

    def get_hash(self, key):
        """Public accessor so the demo page can display 'Key -> Hash' directly."""
        return self._hash(key)

    def put(self, key, value):
        """
        Insert or update a key-value pair.
        Time: O(1) average (assuming few collisions per bucket);
        O(n) worst case if every key hashed into the same bucket,
        which is why a good hash function matters.
        """
        index = self._hash(key)
        bucket = self.buckets[index]

        for pair in bucket:
            if pair[0] == key:
                pair[1] = value  # key already exists - update in place
                return

        bucket.append([key, value])
        self._count += 1

    def get(self, key):
        """
        Look up a value by key.
        Time: O(1) average.
        Returns None if the key is not found.
        """
        index = self._hash(key)
        bucket = self.buckets[index]

        for pair in bucket:
            if pair[0] == key:
                return pair[1]
        return None

    def contains(self, key):
        return self.get(key) is not None

    def delete(self, key):
        """
        Remove a key-value pair.
        Time: O(1) average.
        Returns True if something was deleted, False if the key wasn't found.
        """
        index = self._hash(key)
        bucket = self.buckets[index]

        for i, pair in enumerate(bucket):
            if pair[0] == key:
                bucket.pop(i)
                self._count -= 1
                return True
        return False

    def size(self):
        return self._count

    def keys(self):
        """All stored keys. Time: O(n)."""
        return [pair[0] for bucket in self.buckets for pair in bucket]

    def items(self):
        """All (key, value) pairs. Time: O(n)."""
        return [(pair[0], pair[1]) for bucket in self.buckets for pair in bucket]

    def to_display_rows(self):
        """
        Build exactly the "Key | Hash | Stored Value | Lookup" rows the
        Data Structures demo page needs (Section 16 of the spec), one
        row per stored item, bucket by bucket so collisions are visible
        (two rows sharing the same Hash value = a real collision).
        """
        rows = []
        for bucket_index, bucket in enumerate(self.buckets):
            for key, value in bucket:
                rows.append({
                    "key": key,
                    "hash": bucket_index,
                    "value": repr(value),
                    "collision": len(bucket) > 1,
                })
        return rows

    def __repr__(self):
        return f"<HashTable buckets={self.num_buckets} items={self._count}>"
