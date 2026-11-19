"""Unit tests for :mod:`recommender.text`.

The tokenizer feeds BM25, which needs latin words *and* CJK bigrams because the
LLM summaries are Chinese while the source metadata is English.

Run with:  python -m unittest discover -s tests/python
"""

from __future__ import annotations

import unittest

from recommender.text import STOP_WORDS, tokenize


class EnglishTokenTest(unittest.TestCase):
    def test_lowercases_and_splits_on_punctuation(self) -> None:
        self.assertEqual(tokenize("Cozy, Farming!"), ["cozy", "farming"])

    def test_drops_single_characters(self) -> None:
        self.assertEqual(tokenize("a b ab"), ["ab"])

    def test_drops_stop_words(self) -> None:
        tokens = tokenize("The game with all of its friends")
        for word in ("the", "game", "with", "all", "its"):
            self.assertIn(word, STOP_WORDS)
            self.assertNotIn(word, tokens)
        self.assertEqual(tokens, ["of", "friends"])

    def test_keeps_engine_specific_suffixes(self) -> None:
        self.assertEqual(tokenize("Unity C# 2.5D"), ["unity", "c#", "2.5d"])

    def test_empty_and_none_like_input(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])


class ChineseTokenTest(unittest.TestCase):
    def test_short_runs_keep_the_whole_word_and_its_bigrams(self) -> None:
        self.assertEqual(tokenize("农场模拟"), ["农场模拟", "农场", "场模", "模拟"])

    def test_long_runs_emit_only_bigrams(self) -> None:
        tokens = tokenize("一款舒适的农场模拟游戏")
        self.assertNotIn("一款舒适的农场模拟游戏", tokens)
        self.assertIn("农场", tokens)
        self.assertIn("模拟", tokens)
        # 11 characters -> 10 overlapping bigrams, and no whole-run token.
        self.assertEqual(len([token for token in tokens if len(token) == 2]), 10)

    def test_mixed_script_keeps_both_sides(self) -> None:
        tokens = tokenize("Stardew Valley 星露谷物语")
        self.assertEqual(tokens[:2], ["stardew", "valley"])
        self.assertIn("星露", tokens)


if __name__ == "__main__":
    unittest.main()
