import logging
from typing import List, Optional
from ..models import MemoryBlock, ContextBundle
from ..store import MemoryStore
from .matcher import KeywordMatcher

logger = logging.getLogger(__name__)


class RecallStrategy:
    def __init__(self, store: MemoryStore, matcher: KeywordMatcher) -> None:
        self._store = store
        self._matcher = matcher

    def recall(
        self,
        context_text: str,
        top_n: int = 10,
        max_tokens: int = 4096,
        slot_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> ContextBundle:
        keywords = self._matcher.match(context_text)
        logger.debug(f"Matched keywords: {keywords}")

        candidates: List[MemoryBlock] = []

        if keywords:
            candidates = self._store.recall(
                keywords=keywords, top_n=top_n * 2, tenant_id=tenant_id
            )
        if slot_id:
            slot_candidates = self._store.recall(
                slot_id=slot_id, top_n=top_n * 2, tenant_id=tenant_id
            )
            if candidates:
                candidate_keys = {b.key for b in candidates}
                for b in slot_candidates:
                    if b.key not in candidate_keys:
                        candidates.append(b)
                        candidate_keys.add(b.key)
            else:
                candidates = slot_candidates
        if not keywords and not slot_id:
            candidates = self._store.recall(top_n=top_n, tenant_id=tenant_id)

        filtered = self._filter(candidates)
        bundle = ContextBundle.from_blocks(filtered, max_tokens=max_tokens)
        logger.info(
            f"Recalled {len(bundle.blocks)} blocks "
            f"(from {len(filtered)} candidates, keywords={keywords}, tenant={tenant_id})"
        )
        return bundle

    def _filter(self, blocks: List[MemoryBlock]) -> List[MemoryBlock]:
        return [b for b in blocks if not b.is_expired]
