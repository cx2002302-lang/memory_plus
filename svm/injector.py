from typing import List, Optional
from .models import MemoryBlock, ContextBundle


MEMORY_HEADER = "[Memory Context]"
MEMORY_FOOTER = "[/Memory Context]"


class ContextInjector:
    def __init__(self, header: str = MEMORY_HEADER, footer: str = MEMORY_FOOTER):
        self._header = header
        self._footer = footer

    def format_bundle(self, bundle: ContextBundle) -> str:
        if not bundle.blocks:
            return ""

        lines = [self._header]
        for block in bundle.blocks:
            lines.extend(self._format_block(block))
        lines.append(self._footer)
        return "\n".join(lines)

    def _format_block(self, block: MemoryBlock) -> List[str]:
        parts = [
            f"  [{block.key}]",
            f"    {block.value}",
        ]
        if block.weight != 0.5:
            parts.append(f"    (weight: {block.weight})")
        return parts

    def inject_into_prompt(
        self, system_prompt: str, bundle: ContextBundle
    ) -> str:
        memory_text = self.format_bundle(bundle)
        if not memory_text:
            return system_prompt
        return f"{system_prompt}\n\n{memory_text}"
