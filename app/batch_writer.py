import asyncio
import time
import os
from typing import Dict, Any
from collections import defaultdict


class BatchWriter:
    """
    Buffers search events and flushes them in bulk to reduce write pressure.
    Flushes when buffer >= batch_size OR flush_interval seconds elapsed.
    Trade-off: buffered counts are lost on crash before flush.
    """
    def __init__(self, batch_size: int = 50, flush_interval: float = 10.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._last_flush_time = time.time()
        self.total_received: int = 0
        self.total_flushed: int = 0
        self.total_trie_writes: int = 0
        self.flush_count: int = 0

    async def add(self, word: str) -> bool:
        async with self._lock:
            self._buffer[word] += 1
            self.total_received += 1
            buffered = sum(self._buffer.values())
            elapsed = time.time() - self._last_flush_time
            return buffered >= self.batch_size or elapsed >= self.flush_interval

    async def flush(self, trie_db, cache) -> Dict[str, Any]:
        async with self._lock:
            if not self._buffer:
                return {"flushed_events": 0, "unique_words": 0}
            batch = dict(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.time()

        for word, count in batch.items():
            trie_db.update_score(word, delta=count)
            self.total_trie_writes += 1

        for word in batch:
            await cache.invalidate_prefixes(word)

        total = sum(batch.values())
        self.total_flushed += total
        self.flush_count += 1
        return {
            "flushed_events": total,
            "unique_words": len(batch),
            "writes_saved": total - len(batch),
            "sample_words": list(batch.keys())[:5],
        }

    def get_stats(self) -> Dict[str, Any]:
        saves = max(0, self.total_received - self.total_trie_writes)
        pct = round(100 * saves / max(1, self.total_received), 1)
        return {
            "batch_size_threshold": self.batch_size,
            "flush_interval_seconds": self.flush_interval,
            "currently_buffered": sum(self._buffer.values()),
            "total_search_events_received": self.total_received,
            "total_trie_writes_executed": self.total_trie_writes,
            "writes_saved_by_batching": saves,
            "write_reduction_percent": pct,
            "total_flush_operations": self.flush_count,
        }

    @property
    def pending_count(self) -> int:
        return sum(self._buffer.values())


batch_writer = BatchWriter(
    batch_size=int(os.getenv("BATCH_SIZE", "50")),
    flush_interval=float(os.getenv("BATCH_FLUSH_INTERVAL", "10")),
)
