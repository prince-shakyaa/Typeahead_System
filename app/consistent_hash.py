import hashlib
import bisect
from typing import List, Dict, Optional, Any


class ConsistentHashRing:
    def __init__(self, nodes: List[str], virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self.ring: Dict[int, str] = {}
        self.sorted_keys: List[int] = []
        self._nodes: List[str] = []
        for node in nodes:
            self.add_node(node)

    def _hash(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node: str) -> None:
        self._nodes.append(node)
        for i in range(self.virtual_nodes):
            vkey = self._hash(f"{node}:vnode:{i}")
            self.ring[vkey] = node
            bisect.insort(self.sorted_keys, vkey)

    def remove_node(self, node: str) -> None:
        if node in self._nodes:
            self._nodes.remove(node)
        for i in range(self.virtual_nodes):
            vkey = self._hash(f"{node}:vnode:{i}")
            if vkey in self.ring:
                del self.ring[vkey]
                idx = bisect.bisect_left(self.sorted_keys, vkey)
                if idx < len(self.sorted_keys) and self.sorted_keys[idx] == vkey:
                    self.sorted_keys.pop(idx)

    def get_node(self, key: str) -> Optional[str]:
        if not self.ring:
            return None
        key_hash = self._hash(key)
        idx = bisect.bisect_left(self.sorted_keys, key_hash)
        if idx == len(self.sorted_keys):
            idx = 0
        return self.ring[self.sorted_keys[idx]]

    def get_node_info(self, key: str) -> Dict[str, Any]:
        if not self.ring:
            return {"node": None, "key_hash": None, "total_nodes": 0}
        key_hash = self._hash(key)
        return {
            "node": self.get_node(key),
            "key_hash": key_hash % (10 ** 15),
            "total_nodes": len(self._nodes),
            "virtual_nodes_per_node": self.virtual_nodes,
            "total_virtual_nodes": len(self.sorted_keys),
        }

    def get_distribution(self) -> Dict[str, int]:
        dist: Dict[str, int] = {n: 0 for n in self._nodes}
        for node in self.ring.values():
            dist[node] = dist.get(node, 0) + 1
        return dist

    @property
    def nodes(self) -> List[str]:
        return list(self._nodes)


CACHE_NODES = ["cache_node_1", "cache_node_2", "cache_node_3"]
hash_ring = ConsistentHashRing(nodes=CACHE_NODES, virtual_nodes=150)
