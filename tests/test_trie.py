"""
Unit Tests for the Trie data structure (app/trie.py) — v2.

Tests the core Trie operations in complete isolation (no HTTP, no Redis, no I/O).

Run with:
    pytest tests/test_trie.py -v
"""

import pytest
from app.trie import Trie


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_trie():
    return Trie()


@pytest.fixture
def populated_trie():
    t = Trie()
    t.insert("apple", score=100)
    t.insert("app", score=50)
    t.insert("application", score=200)
    t.insert("api", score=150)
    t.insert("banana", score=10)
    t.insert("band", score=20)
    t.insert("bandwidth", score=30)
    t.insert("cat", score=5)
    t.insert("car", score=50)
    t.insert("cart", score=10)
    return t


# ---------------------------------------------------------------------------
# Test: insert
# ---------------------------------------------------------------------------

class TestInsert:
    def test_insert_single_word(self, empty_trie):
        empty_trie.insert("hello")
        assert "hello" in empty_trie.word_scores

    def test_insert_multiple_words(self, empty_trie):
        for w in ["alpha", "beta", "gamma"]:
            empty_trie.insert(w)
            assert w in empty_trie.word_scores

    def test_insert_default_score_is_one(self, empty_trie):
        empty_trie.insert("hello")
        assert empty_trie.word_scores["hello"] == 1

    def test_insert_custom_score(self, empty_trie):
        empty_trie.insert("world", score=42)
        assert empty_trie.word_scores["world"] == 42

    def test_insert_duplicate_accumulates(self, empty_trie):
        empty_trie.insert("hello", score=10)
        empty_trie.insert("hello", score=5)
        assert empty_trie.word_scores["hello"] == 15

    def test_insert_marks_end_of_word(self, empty_trie):
        empty_trie.insert("hi")
        node = empty_trie.root.children["h"].children["i"]
        assert node.is_end_of_word is True
        assert node.word == "hi"

    def test_insert_empty_string_no_crash(self, empty_trie):
        try:
            empty_trie.insert("")
        except Exception as e:
            pytest.fail(f"insert('') raised: {e}")


# ---------------------------------------------------------------------------
# Test: update_score
# ---------------------------------------------------------------------------

class TestUpdateScore:
    def test_update_existing_word(self, populated_trie):
        old = populated_trie.word_scores["apple"]
        populated_trie.update_score("apple", delta=10)
        assert populated_trie.word_scores["apple"] == old + 10

    def test_update_new_word_inserts(self, empty_trie):
        empty_trie.update_score("newword", delta=5)
        assert "newword" in empty_trie.word_scores
        assert empty_trie.word_scores["newword"] == 5

    def test_update_default_delta_is_one(self, populated_trie):
        old = populated_trie.word_scores["api"]
        populated_trie.update_score("api")
        assert populated_trie.word_scores["api"] == old + 1


# ---------------------------------------------------------------------------
# Test: search_prefix
# ---------------------------------------------------------------------------

class TestSearchPrefix:
    def test_valid_prefix_found(self, populated_trie):
        assert populated_trie.search_prefix("app") is not None

    def test_invalid_prefix_returns_none(self, populated_trie):
        assert populated_trie.search_prefix("xyz") is None

    def test_exact_word_is_end_of_word(self, populated_trie):
        node = populated_trie.search_prefix("apple")
        assert node is not None
        assert node.is_end_of_word is True

    def test_single_char_prefix(self, populated_trie):
        assert populated_trie.search_prefix("a") is not None


# ---------------------------------------------------------------------------
# Test: get_top_k  (classic mode — no score_fn)
# ---------------------------------------------------------------------------

class TestGetTopK:
    def test_returns_list(self, populated_trie):
        assert isinstance(populated_trie.get_top_k("app"), list)

    def test_no_match_returns_empty(self, populated_trie):
        assert populated_trie.get_top_k("xyz") == []

    def test_order_by_score_descending(self, populated_trie):
        result = populated_trie.get_top_k("app")
        # application(200) > apple(100) > app(50)
        assert result[0] == "application"
        assert result[1] == "apple"
        assert result[2] == "app"

    def test_respects_k_limit(self, empty_trie):
        for i in range(15):
            empty_trie.insert(f"word{i}", score=i)
        assert len(empty_trie.get_top_k("word", k=5)) <= 5

    def test_alphabetical_tiebreaker(self, empty_trie):
        for w in ["gamma", "alpha", "beta"]:
            empty_trie.insert(w, score=10)
        result = empty_trie.get_top_k("", k=3)
        assert result == ["alpha", "beta", "gamma"]

    def test_includes_exact_word(self, populated_trie):
        assert "app" in populated_trie.get_top_k("app")

    def test_prefix_b_correct_order(self, populated_trie):
        result = populated_trie.get_top_k("b")
        # bandwidth(30) > band(20) > banana(10)
        assert result.index("bandwidth") < result.index("band")
        assert result.index("band") < result.index("banana")

    def test_after_score_update(self, populated_trie):
        populated_trie.update_score("app", delta=500)
        assert populated_trie.get_top_k("app")[0] == "app"

    def test_single_char_prefix(self, populated_trie):
        for w in populated_trie.get_top_k("c"):
            assert w.startswith("c")

    def test_all_results_are_strings(self, populated_trie):
        for item in populated_trie.get_top_k("a"):
            assert isinstance(item, str)

    def test_custom_score_fn(self, populated_trie):
        """score_fn should override ranking — words with longest name win."""
        def score_fn(word, hist):
            return float(len(word))  # rank by word length

        result = populated_trie.get_top_k("app", k=3, score_fn=score_fn)
        # "application" (11 chars) should rank first
        assert result[0] == "application"

    def test_trending_score_fn_changes_order(self, populated_trie):
        """After recency boosting 'app', it should surface above application."""
        from app.trending import RecencyTracker
        tracker = RecencyTracker(half_life_seconds=3600, recency_multiplier=10000)
        for _ in range(5):
            tracker.record("app")

        result = populated_trie.get_top_k(
            "app", k=3,
            score_fn=lambda w, h: tracker.get_combined_score(w, h)
        )
        assert result[0] == "app"
