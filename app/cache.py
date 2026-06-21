import json
import os
from typing import List, Optional, Dict, Any
import redis.asyncio as redis
from app.consistent_hash import hash_ring

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class CacheManager:
    """Redis cache with consistent hashing for key routing."""
    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def init(self) -> None:
        self.client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            await self.client.ping()
            print(f"✅ Redis connected at {REDIS_URL}")
        except Exception as e:
            print(f"⚠️  Redis unavailable: {e}")
            self.client = None

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()

    def _make_key(self, cache_key: str) -> str:
        node = hash_ring.get_node(cache_key) or "cache_node_1"
        return f"{node}:prefix:{cache_key}"

    async def get_suggestions(self, cache_key: str) -> Optional[List[str]]:
        if not self.client:
            return None
        try:
            v = await self.client.get(self._make_key(cache_key))
            return json.loads(v) if v else None
        except Exception as e:
            print(f"Redis GET error: {e}")
            return None

    async def set_suggestions(self, cache_key: str, suggestions: List[str], ttl: int = 3600) -> None:
        if not self.client:
            return
        try:
            await self.client.set(self._make_key(cache_key), json.dumps(suggestions), ex=ttl)
        except Exception as e:
            print(f"Redis SET error: {e}")

    async def invalidate_prefixes(self, word: str) -> None:
        if not self.client:
            return
        try:
            pipe = self.client.pipeline()
            for i in range(1, len(word) + 1):
                for mode in ("classic", "trending"):
                    pipe.delete(self._make_key(f"{mode}:{word[:i]}"))
            await pipe.execute()
        except Exception as e:
            print(f"Redis invalidate error: {e}")

    async def debug_prefix(self, prefix: str, mode: str = "trending") -> Dict[str, Any]:
        cache_key = f"{mode}:{prefix}"
        redis_key = self._make_key(cache_key)
        node_info = hash_ring.get_node_info(cache_key)
        is_hit, cached = False, None
        if self.client:
            try:
                raw = await self.client.get(redis_key)
                if raw:
                    is_hit = True
                    cached = json.loads(raw)
            except Exception:
                pass
        return {
            "prefix": prefix,
            "mode": mode,
            "cache_node": node_info.get("node"),
            "redis_key": redis_key,
            "cache_status": "HIT" if is_hit else "MISS",
            "cached_suggestions": cached,
            "hash_ring_info": node_info,
            "all_nodes": hash_ring.nodes,
            "node_distribution": hash_ring.get_distribution(),
        }


cache = CacheManager()
