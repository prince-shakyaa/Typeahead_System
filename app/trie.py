from typing import List, Dict, Optional, Callable


class TrieNode:
    __slots__ = ("children", "is_end_of_word", "word")
    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.is_end_of_word: bool = False
        self.word: Optional[str] = None


class Trie:
    def __init__(self):
        self.root = TrieNode()
        self.word_scores: Dict[str, int] = {}

    def insert(self, word: str, score: int = 1) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True
        node.word = word
        if word not in self.word_scores:
            self.word_scores[word] = score
        else:
            self.word_scores[word] += score

    def update_score(self, word: str, delta: int = 1) -> None:
        if word in self.word_scores:
            self.word_scores[word] += delta
        else:
            self.insert(word, score=delta)

    def search_prefix(self, prefix: str) -> Optional[TrieNode]:
        node = self.root
        for char in prefix:
            if char not in node.children:
                return None
            node = node.children[char]
        return node

    def get_top_k(self, prefix: str, k: int = 10,
                  score_fn: Optional[Callable[[str, int], float]] = None) -> List[str]:
        node = self.search_prefix(prefix)
        if not node:
            return []
        candidates = []
        def dfs(curr: TrieNode):
            if curr.is_end_of_word and curr.word:
                w = curr.word
                h = self.word_scores.get(w, 0)
                candidates.append((score_fn(w, h) if score_fn else float(h), w))
            for child in curr.children.values():
                dfs(child)
        dfs(node)
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return [w for _, w in candidates[:k]]


trie_db = Trie()
