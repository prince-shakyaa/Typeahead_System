import time
import math
from typing import Dict, List, Tuple
from collections import defaultdict


class RecencyTracker:
    """
    Tracks search events with exponential time-decay scoring.
    score(word) = Σ 2^(-age / half_life) for each event.
    Combined: historical_count + recency_multiplier * recency_score.
    """
    def __init__(self, half_life_seconds: float = 3600.0,
                 max_events_per_word: int = 1000,
                 recency_multiplier: float = 100.0):
        self.half_life = half_life_seconds
        self.max_events = max_events_per_word
        self.recency_multiplier = recency_multiplier
        self._events: Dict[str, List[float]] = defaultdict(list)

    def record(self, word: str) -> None:
        events = self._events[word]
        events.append(time.time())
        if len(events) > self.max_events:
            self._events[word] = events[-self.max_events:]

    def get_recency_score(self, word: str) -> float:
        if word not in self._events:
            return 0.0
        now = time.time()
        cutoff = now - self.half_life * 10
        score = 0.0
        valid = []
        for ts in self._events[word]:
            if ts < cutoff:
                continue
            score += math.pow(2.0, -(now - ts) / self.half_life)
            valid.append(ts)
        self._events[word] = valid
        return score

    def get_combined_score(self, word: str, historical_score: int) -> float:
        return historical_score + self.recency_multiplier * self.get_recency_score(word)

    def get_trending(self, top_k: int = 10) -> List[Tuple[str, float]]:
        scored = [
            (w, round(self.get_recency_score(w), 4))
            for w in list(self._events.keys())
            if self.get_recency_score(w) > 0.001
        ]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def explain(self, word: str) -> Dict:
        now = time.time()
        events = self._events.get(word, [])
        breakdown = [
            {"age_seconds": round(now - ts, 1),
             "contribution": round(math.pow(2.0, -(now - ts) / self.half_life), 6)}
            for ts in events[-10:]
        ]
        return {
            "word": word,
            "total_events": len(events),
            "recency_score": round(self.get_recency_score(word), 4),
            "half_life_seconds": self.half_life,
            "last_10_events": breakdown,
        }


recency_tracker = RecencyTracker(
    half_life_seconds=3600.0,
    max_events_per_word=1000,
    recency_multiplier=100.0,
)
