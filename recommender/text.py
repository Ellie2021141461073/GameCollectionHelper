"""Tokenizer shared by the recommender service and its unit tests.

The corpus is English metadata with Chinese LLM summaries, so the tokenizer
keeps latin word pieces and also emits CJK bigrams (BGE-M3 handles the vector
side, while BM25 needs explicit CJK tokens because there are no spaces).

This module is deliberately dependency free: importing it must never pull in
Qdrant, sentence-transformers or an OpenAI client.
"""

from __future__ import annotations

import re

STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "your", "you",
    "are", "its", "game", "games", "steam", "about", "will", "can", "all",
})

ENGLISH_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]+")

# Very short runs produce noise tokens, so single-character CJK runs only get
# indexed when the whole run is that short (see :func:`tokenize`).
MIN_ENGLISH_TOKEN_LENGTH = 2
CJK_UNIGRAM_MAX_LENGTH = 4


def tokenize(text: str) -> list[str]:
    """Split ``text`` into BM25 terms.

    Latin runs are lowercased, stripped of punctuation and filtered by length
    and stop words. Every CJK run additionally contributes its overlapping
    bigrams; runs of four characters or fewer are also kept as a whole so short
    words such as ``模拟`` stay searchable.
    """
    lowered = (text or "").casefold()
    tokens = [
        token
        for token in ENGLISH_TOKEN.findall(lowered)
        if len(token) >= MIN_ENGLISH_TOKEN_LENGTH and token not in STOP_WORDS
    ]
    for run in CHINESE_RUN.findall(lowered):
        if len(run) <= CJK_UNIGRAM_MAX_LENGTH:
            tokens.append(run)
        tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    return tokens
