"""
Integration Tests for the FastAPI application (app/main.py) — v2.

Covers all endpoints:
  GET  /suggest   (classic and trending modes)
  POST /search    (returns {"message": "Searched"})
  GET  /trending
  GET  /cache/debug
  GET  /health
  GET  /stats

Redis, RecencyTracker, and BatchWriter are fully mocked.

Run with:
    pytest tests/test_api.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.trie import Trie


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_trie():
    """Reset global trie_db and recency_tracker before each test."""
    from app import trie as trie_module
    fresh = Trie()
    fresh.insert("apple", score=100)
    fresh.insert("app", score=50)
    fresh.insert("application", score=200)
    fresh.insert("api", score=150)
    fresh.insert("banana", score=10)
    fresh.insert("band", score=20)
    fresh.insert("car", score=50)
    trie_module.trie_db = fresh

    import app.main as main_module
    main_module.trie_db = fresh

    # Reset recency tracker
    from app.trending import recency_tracker
    recency_tracker._events.clear()

    yield


@pytest.fixture
def mock_cache():
    """Patch cache so all operations are no-ops / cache-miss by default."""
    with patch("app.main.cache") as mock:
        mock.init = AsyncMock()
        mock.close = AsyncMock()
        mock.get_suggestions = AsyncMock(return_value=None)
        mock.set_suggestions = AsyncMock()
        mock.invalidate_prefixes = AsyncMock()
        mock.client = MagicMock()
        mock.client.ping = AsyncMock()
        mock.client.info = AsyncMock(return_value={
            "keyspace_hits": 800,
            "keyspace_misses": 200,
            "total_commands_processed": 1000,
            "connected_clients": 3,
        })
        mock.debug_prefix = AsyncMock(return_value={
            "prefix": "app",
            "mode": "trending",
            "cache_node": "cache_node_2",
            "redis_key": "cache_node_2:prefix:trending:app",
            "cache_status": "MISS",
            "cached_suggestions": None,
            "hash_ring_info": {
                "node": "cache_node_2",
                "key_hash": 123456789,
                "total_nodes": 3,
                "virtual_nodes_per_node": 150,
            },
            "all_nodes": ["cache_node_1", "cache_node_2", "cache_node_3"],
            "node_distribution": {"cache_node_1": 150, "cache_node_2": 150, "cache_node_3": 150},
        })
        yield mock


@pytest.fixture
def mock_batch():
    """Patch batch_writer to avoid async lock issues."""
    with patch("app.main.batch_writer") as mock:
        mock.add = AsyncMock(return_value=False)
        mock.flush = AsyncMock(return_value={"flushed_events": 0, "unique_words": 0})
        mock.pending_count = 0
        mock.flush_interval = 10.0
        mock.get_stats = MagicMock(return_value={
            "batch_size_threshold": 50,
            "flush_interval_seconds": 10,
            "currently_buffered": 0,
            "total_search_events_received": 5,
            "total_trie_writes_executed": 1,
            "writes_saved_by_batching": 4,
            "write_reduction_percent": 80.0,
            "total_flush_operations": 1,
        })
        yield mock


@pytest.fixture
def client(mock_cache, mock_batch):
    """Standard test client with cache miss and batch mock."""
    return TestClient(app)


@pytest.fixture
def client_cache_hit(mock_batch):
    """Test client where Redis returns a cache hit."""
    with patch("app.main.cache") as mock:
        mock.init = AsyncMock()
        mock.close = AsyncMock()
        mock.get_suggestions = AsyncMock(return_value=["application", "apple", "app"])
        mock.set_suggestions = AsyncMock()
        mock.invalidate_prefixes = AsyncMock()
        mock.client = MagicMock()
        mock.client.ping = AsyncMock()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /suggest
# ---------------------------------------------------------------------------

class TestSuggestEndpoint:
    def test_returns_200(self, client):
        assert client.get("/suggest?q=app").status_code == 200

    def test_returns_list(self, client):
        assert isinstance(client.get("/suggest?q=app").json(), list)

    def test_results_are_strings(self, client):
        for item in client.get("/suggest?q=app").json():
            assert isinstance(item, str)

    def test_prefix_filtered(self, client):
        for word in client.get("/suggest?q=app").json():
            assert word.startswith("app")

    def test_ranked_by_score_classic(self, client):
        """application(200) > apple(100) > app(50) in classic mode."""
        results = client.get("/suggest?q=app&mode=classic").json()
        assert results[0] == "application"

    def test_empty_prefix_returns_empty(self, client):
        r = client.get("/suggest?q=")
        assert r.status_code == 200
        assert r.json() == []

    def test_unknown_prefix_returns_empty(self, client):
        assert client.get("/suggest?q=xyz123").json() == []

    def test_cache_hit_returned(self, client_cache_hit):
        r = client_cache_hit.get("/suggest?q=app")
        assert r.status_code == 200
        assert r.json() == ["application", "apple", "app"]

    def test_lowercase_normalisation(self, client):
        lower = client.get("/suggest?q=app").json()
        upper = client.get("/suggest?q=APP").json()
        assert lower == upper

    def test_at_most_ten_results(self, client):
        assert len(client.get("/suggest?q=a").json()) <= 10

    def test_missing_q_returns_422(self, client):
        assert client.get("/suggest").status_code == 422

    def test_classic_mode_accepted(self, client):
        r = client.get("/suggest?q=app&mode=classic")
        assert r.status_code == 200

    def test_trending_mode_accepted(self, client):
        r = client.get("/suggest?q=app&mode=trending")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------

class TestSearchEndpoint:
    def test_returns_200(self, client):
        assert client.post("/search", json={"query": "apple"}).status_code == 200

    def test_response_message_is_searched(self, client):
        """Response must contain {"message": "Searched"} per assignment spec."""
        body = client.post("/search", json={"query": "apple"}).json()
        assert body["message"] == "Searched"

    def test_response_contains_query(self, client):
        body = client.post("/search", json={"query": "banana"}).json()
        assert body["query"] == "banana"

    def test_records_in_recency_tracker(self, client):
        """POST /search should record the event in the recency tracker."""
        from app.trending import recency_tracker
        assert "apple" not in recency_tracker._events
        client.post("/search", json={"query": "apple"})
        assert "apple" in recency_tracker._events
        assert len(recency_tracker._events["apple"]) == 1

    def test_empty_query_returns_400(self, client):
        assert client.post("/search", json={"query": ""}).status_code == 400

    def test_whitespace_query_returns_400(self, client):
        assert client.post("/search", json={"query": "   "}).status_code == 400

    def test_missing_body_returns_422(self, client):
        assert client.post("/search").status_code == 422

    def test_lowercase_normalisation(self, client):
        from app.trending import recency_tracker
        client.post("/search", json={"query": "APPLE"})
        # Should record lowercased
        assert "apple" in recency_tracker._events


# ---------------------------------------------------------------------------
# GET /trending
# ---------------------------------------------------------------------------

class TestTrendingEndpoint:
    def test_returns_200(self, client):
        assert client.get("/trending").status_code == 200

    def test_response_has_trending_key(self, client):
        body = client.get("/trending").json()
        assert "trending" in body

    def test_empty_initially(self, client):
        body = client.get("/trending").json()
        assert body["trending"] == []

    def test_appears_after_search(self, client):
        client.post("/search", json={"query": "python"})
        client.post("/search", json={"query": "python"})
        body = client.get("/trending").json()
        queries = [t["query"] for t in body["trending"]]
        assert "python" in queries

    def test_has_recency_score(self, client):
        client.post("/search", json={"query": "redis"})
        body = client.get("/trending").json()
        for item in body["trending"]:
            assert "recency_score" in item
            assert isinstance(item["recency_score"], float)

    def test_response_has_scoring_model(self, client):
        body = client.get("/trending").json()
        assert "scoring_model" in body
        assert body["scoring_model"] == "exponential_decay"

    def test_top_k_param(self, client):
        for q in ["python", "docker", "redis", "golang", "rust"]:
            client.post("/search", json={"query": q})
        body = client.get("/trending?top_k=3").json()
        assert len(body["trending"]) <= 3


# ---------------------------------------------------------------------------
# GET /cache/debug
# ---------------------------------------------------------------------------

class TestCacheDebugEndpoint:
    def test_returns_200(self, client):
        assert client.get("/cache/debug?prefix=app").status_code == 200

    def test_has_cache_node(self, client):
        body = client.get("/cache/debug?prefix=app").json()
        assert "cache_node" in body

    def test_has_redis_key(self, client):
        body = client.get("/cache/debug?prefix=app").json()
        assert "redis_key" in body

    def test_has_cache_status(self, client):
        body = client.get("/cache/debug?prefix=app").json()
        assert body["cache_status"] in ("HIT", "MISS")

    def test_has_hash_ring_info(self, client):
        body = client.get("/cache/debug?prefix=app").json()
        assert "hash_ring_info" in body

    def test_has_all_nodes(self, client):
        body = client.get("/cache/debug?prefix=app").json()
        assert "all_nodes" in body
        assert len(body["all_nodes"]) == 3

    def test_missing_prefix_returns_422(self, client):
        assert client.get("/cache/debug").status_code == 422


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_has_status_key(self, client):
        assert "status" in client.get("/health").json()

    def test_has_uptime(self, client):
        body = client.get("/health").json()
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], (int, float))

    def test_has_dependencies(self, client):
        deps = client.get("/health").json().get("dependencies", {})
        assert "redis" in deps
        assert "trie" in deps

    def test_trie_always_loaded(self, client):
        body = client.get("/health").json()
        assert body["dependencies"]["trie"] == "loaded"


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

class TestStatsEndpoint:
    def test_returns_200(self, client):
        assert client.get("/stats").status_code == 200

    def test_has_trie_key(self, client):
        assert "trie" in client.get("/stats").json()

    def test_has_redis_key(self, client):
        assert "redis" in client.get("/stats").json()

    def test_has_batch_writer_key(self, client):
        assert "batch_writer" in client.get("/stats").json()

    def test_has_consistent_hash_ring(self, client):
        assert "consistent_hash_ring" in client.get("/stats").json()

    def test_trie_total_words(self, client):
        body = client.get("/stats").json()
        assert body["trie"]["total_words"] == 7

    def test_has_uptime(self, client):
        assert "uptime_seconds" in client.get("/stats").json()
