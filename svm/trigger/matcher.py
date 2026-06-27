import logging
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

try:
    import ahocorasick

    HAS_AHOCORASICK = True
except ImportError:
    HAS_AHOCORASICK = False


class _TrieNode:
    __slots__ = ("children", "fail", "output")

    def __init__(self) -> None:
        self.children: dict[str, "_TrieNode"] = {}
        self.fail: Optional["_TrieNode"] = None
        self.output: list[str] = []


class _AhoCorasickPy:
    def __init__(self) -> None:
        self._root = _TrieNode()
        self._built = False
        self._keyword_count = 0

    def add_keyword(self, keyword: str) -> None:
        node = self._root
        for char in keyword:
            if char not in node.children:
                node.children[char] = _TrieNode()
            node = node.children[char]
        if keyword not in node.output:
            node.output.append(keyword)
            self._keyword_count += 1
        self._built = False

    def build(self) -> None:
        from collections import deque

        queue: deque[_TrieNode] = deque()
        for child in self._root.children.values():
            child.fail = self._root
            queue.append(child)

        while queue:
            current = queue.popleft()
            for char, child in current.children.items():
                queue.append(child)
                fail = current.fail
                while fail is not None and char not in fail.children:
                    fail = fail.fail
                child.fail = fail.children[char] if fail and char in fail.children else self._root
                if child.fail:
                    child.output.extend(child.fail.output)
        self._built = True

    def match(self, text: str) -> list[str]:
        if not self._built:
            self.build()
        if self._keyword_count == 0:
            return []
        node = self._root
        matched: list[str] = []
        for char in text:
            while node is not self._root and char not in node.children:
                node = node.fail
            if char in node.children:
                node = node.children[char]
            if node.output:
                matched.extend(node.output)
        return matched


class KeywordMatcher:
    def __init__(self) -> None:
        self._keywords: Set[str] = set()
        self._use_ac = HAS_AHOCORASICK
        if self._use_ac:
            self._ac = ahocorasick.Automaton()
            self._ac_ready = False
        else:
            self._ac_py = _AhoCorasickPy()
            self._ac_py_ready = False

    def add_keyword(self, keyword: str) -> None:
        kw = keyword.strip().lower()
        if kw and kw not in self._keywords:
            self._keywords.add(kw)
            if self._use_ac:
                self._ac.add_word(kw, kw)
                self._ac_ready = False
            else:
                self._ac_py.add_keyword(kw)
                self._ac_py_ready = False

    def add_keywords(self, keywords: List[str]) -> None:
        for kw in keywords:
            self.add_keyword(kw)

    def remove_keyword(self, keyword: str) -> None:
        kw = keyword.strip().lower()
        self._keywords.discard(kw)
        self._rebuild_ac()

    def _rebuild_ac(self) -> None:
        if self._use_ac:
            self._ac = ahocorasick.Automaton()
            self._ac_ready = False
            for kw in self._keywords:
                self._ac.add_word(kw, kw)
        else:
            self._ac_py = _AhoCorasickPy()
            self._ac_py_ready = False
            for kw in self._keywords:
                self._ac_py.add_keyword(kw)

    def match(self, text: str) -> List[str]:
        if not self._keywords:
            return []
        text_lower = text.lower()
        if self._use_ac:
            if not self._ac_ready:
                self._ac.make_automaton()
                self._ac_ready = True
            return list(dict.fromkeys(self._ac.iter(text_lower)))
        else:
            if not self._ac_py_ready:
                self._ac_py.build()
                self._ac_py_ready = True
            return self._ac_py.match(text_lower)

    def match_all(self, texts: List[str]) -> List[str]:
        matched: Set[str] = set()
        for text in texts:
            matched.update(self.match(text))
        return list(matched)

    @property
    def count(self) -> int:
        return len(self._keywords)

    def clear(self) -> None:
        self._keywords.clear()
        self._rebuild_ac()
