import os
import time
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.trie import trie_db
from app.cache import cache
from app.trending import recency_tracker
from app.batch_writer import batch_writer
from app.consistent_hash import hash_ring

_start_time: float = 0.0
_word_count: int = 0


class SearchQuery(BaseModel):
    query: str


def load_initial_data() -> int:
    dataset_path = "dataset.txt"
    count = 0
    if os.path.exists(dataset_path):
        with open(dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if "\t" in line:
                    parts = line.split("\t", 1)
                    word = parts[0].strip().lower()
                    try:
                        score = int(parts[1].strip())
                    except (ValueError, IndexError):
                        score = 1
                else:
                    word = line.lower()
                    score = 1
                if word:
                    trie_db.insert(word, score=score)
                    count += 1
        print(f"✅ Loaded {count:,} words from {dataset_path}")
    else:
        for w, s in [("apple", 100), ("app", 50), ("application", 200),
                     ("api", 150), ("banana", 10), ("band", 20)]:
            trie_db.insert(w, score=s)
            count += 1
        print(f"⚠️  dataset.txt not found, loaded {count} defaults.")
    return count


async def _periodic_flush():
    while True:
        await asyncio.sleep(batch_writer.flush_interval)
        if batch_writer.pending_count > 0:
            result = await batch_writer.flush(trie_db, cache)
            print(f"[BatchWriter] Periodic flush: {result}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time, _word_count
    _start_time = time.time()
    await cache.init()
    _word_count = load_initial_data()
    task = asyncio.create_task(_periodic_flush())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if batch_writer.pending_count > 0:
        await batch_writer.flush(trie_db, cache)
    await cache.close()


app = FastAPI(
    title="Search Typeahead API",
    version="2.0.0",
    description="Typeahead backend: Trie + Redis (consistent hashing) + recency ranking + batch writes.",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def serve_frontend():
    try:
        with open("frontend/index.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse("<h2>Frontend not found. Visit <a href='/docs'>/docs</a>.</h2>")


@app.get("/suggest", response_model=List[str], summary="Get typeahead suggestions")
async def get_suggestions(
    q: str = Query(..., description="Search prefix"),
    mode: str = Query("trending", description="'classic' or 'trending'"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    prefix = q.lower().strip()
    if not prefix:
        return []
    if mode not in ("classic", "trending"):
        mode = "trending"

    cache_key = f"{mode}:{prefix}"
    cached = await cache.get_suggestions(cache_key)
    if cached is not None:
        return cached

    score_fn = (lambda w, h: recency_tracker.get_combined_score(w, h)) if mode == "trending" else None
    suggestions = trie_db.get_top_k(prefix, k=10, score_fn=score_fn)
    background_tasks.add_task(cache.set_suggestions, cache_key, suggestions, 3600)
    return suggestions


@app.post("/search", summary="Submit a search query")
async def submit_search(search_query: SearchQuery, background_tasks: BackgroundTasks):
    query = search_query.query.lower().strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    recency_tracker.record(query)
    should_flush = await batch_writer.add(query)
    if should_flush:
        background_tasks.add_task(batch_writer.flush, trie_db, cache)
    return {"message": "Searched", "query": query}


@app.get("/trending", summary="Get trending searches")
async def get_trending(top_k: int = Query(10, ge=1, le=50)):
    trending = recency_tracker.get_trending(top_k=top_k)
    return {
        "trending": [{"query": q, "recency_score": s} for q, s in trending],
        "scoring_model": "exponential_decay",
        "half_life_seconds": recency_tracker.half_life,
        "recency_multiplier": recency_tracker.recency_multiplier,
    }


@app.get("/cache/debug", summary="Inspect consistent-hash routing for a prefix")
async def cache_debug(
    prefix: str = Query(..., description="Prefix to inspect"),
    mode: str = Query("trending", description="'classic' or 'trending'"),
):
    return await cache.debug_prefix(prefix.lower().strip(), mode=mode)


@app.get("/health", summary="Health check")
async def health_check() -> Dict[str, Any]:
    redis_ok = False
    if cache.client:
        try:
            await cache.client.ping()
            redis_ok = True
        except Exception:
            pass
    return {
        "status": "healthy" if redis_ok else "degraded",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "dependencies": {
            "redis": "connected" if redis_ok else "unavailable",
            "trie": "loaded",
            "consistent_hash_ring": f"{len(hash_ring.nodes)} nodes active",
        },
    }


@app.get("/stats", summary="Runtime statistics")
async def get_stats() -> Dict[str, Any]:
    redis_info: Dict[str, Any] = {"status": "unavailable"}
    if cache.client:
        try:
            info = await cache.client.info("stats")
            clients = await cache.client.info("clients")
            hits = info.get("keyspace_hits", 0)
            misses = info.get("keyspace_misses", 0)
            redis_info = {
                "status": "connected",
                "keyspace_hits": hits,
                "keyspace_misses": misses,
                "hit_rate": round(hits / max(1, hits + misses), 4),
                "total_commands": info.get("total_commands_processed", 0),
                "connected_clients": clients.get("connected_clients", 0),
            }
        except Exception as e:
            redis_info = {"status": "error", "detail": str(e)}
    return {
        "uptime_seconds": round(time.time() - _start_time, 2),
        "trie": {
            "total_words": len(trie_db.word_scores),
            "top_10_by_historical_score": sorted(
                trie_db.word_scores.items(), key=lambda x: -x[1])[:10],
        },
        "redis": redis_info,
        "batch_writer": batch_writer.get_stats(),
        "consistent_hash_ring": {
            "nodes": hash_ring.nodes,
            "virtual_nodes_per_node": hash_ring.virtual_nodes,
            "distribution": hash_ring.get_distribution(),
        },
        "trending": {
            "tracked_words": len(recency_tracker._events),
            "half_life_seconds": recency_tracker.half_life,
        },
    }
