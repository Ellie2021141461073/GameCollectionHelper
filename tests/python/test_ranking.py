"""Unit tests for :mod:`recommender.ranking`.

These cover the retrieval maths that the hybrid recommender relies on: BM25
scoring, the quality prior, and RRF fusion. No Qdrant, no LLM, no network.

Run with:  python -m unittest discover -s tests/python
"""

from __future__ import annotations

import math
import unittest

from recommender.ranking import (
    BM25Index,
    QUALITY_WEIGHT,
    RRF_K,
    merge_rankings,
    quality_score,
)


class BM25Test(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            ["cozy", "farming", "simulation"],
            ["farming", "building", "simulation"],
            ["fast", "action", "shooter"],
        ]
        self.index = BM25Index(self.documents)

    def test_ranks_matching_documents_above_non_matching(self) -> None:
        results = self.index.search(["farming"], limit=10)
        self.assertEqual({index for index, _ in results}, {0, 1})

    def test_excludes_zero_scoring_documents(self) -> None:
        results = self.index.search(["shooter"], limit=10)
        self.assertEqual([index for index, _ in results], [2])

    def test_unknown_term_returns_nothing(self) -> None:
        self.assertEqual(self.index.search(["nonexistent"], limit=10), [])

    def test_respects_limit(self) -> None:
        results = self.index.search(["farming", "simulation"], limit=1)
        self.assertEqual(len(results), 1)

    def test_duplicate_query_terms_are_not_double_counted(self) -> None:
        once = self.index.search(["farming"], limit=10)
        twice = self.index.search(["farming", "farming"], limit=10)
        self.assertEqual(once, twice)

    def test_index_stats(self) -> None:
        self.assertEqual(self.index.document_count, 3)
        self.assertEqual(self.index.lengths, [3, 3, 3])
        self.assertAlmostEqual(self.index.average_length, 3.0)
        # "shooter" appears in a single document, so it is more informative
        # than "simulation", which appears in two.
        self.assertGreater(self.index.idf["shooter"], self.index.idf["simulation"])

    def test_matches_the_textbook_formula_for_one_term(self) -> None:
        index = BM25Index([["farming"], ["farming", "farming"], ["other"]])
        results = dict(index.search(["farming"], limit=10))
        total, frequencies, length, average = 3, 2, 1, index.average_length
        idf = math.log(1 + (total - frequencies + 0.5) / (frequencies + 0.5))
        length_norm = 1 - index.b + index.b * length / average
        expected = idf * 1 * (index.k1 + 1) / (1 + index.k1 * length_norm)
        self.assertAlmostEqual(results[0], expected)

    def test_empty_index_is_safe(self) -> None:
        index = BM25Index([])
        self.assertEqual(index.search(["anything"], limit=5), [])
        self.assertEqual(index.average_length, 0.0)


class QualityScoreTest(unittest.TestCase):
    def test_no_reviews_falls_back_to_the_prior(self) -> None:
        score = quality_score({"positive": 0, "negative": 0, "recommendations": 0})
        self.assertAlmostEqual(score, 0.8 * 0.8)

    def test_more_positive_ratio_scores_higher(self) -> None:
        good = quality_score({"positive": 900, "negative": 100, "recommendations": 0})
        bad = quality_score({"positive": 100, "negative": 900, "recommendations": 0})
        self.assertGreater(good, bad)

    def test_popularity_term_is_capped(self) -> None:
        modest = quality_score({"positive": 0, "negative": 0, "recommendations": 10})
        huge = quality_score({"positive": 0, "negative": 0, "recommendations": 10**9})
        self.assertGreater(huge, modest)
        self.assertLessEqual(huge, 0.8 * 0.8 + 0.2 + 1e-9)

    def test_missing_fields_do_not_raise(self) -> None:
        self.assertAlmostEqual(quality_score({}), 0.8 * 0.8)


class MergeRankingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payloads = {
            1: {"positive": 0, "negative": 0, "recommendations": 0},
            2: {"positive": 0, "negative": 0, "recommendations": 0},
            3: {"positive": 0, "negative": 0, "recommendations": 0},
        }
        # document index -> app_id
        self.lexical_ids = [1, 2, 3]

    def fuse(self, vector_results, lexical_results, **kwargs):
        return merge_rankings(
            vector_results=vector_results,
            lexical_results=lexical_results,
            lexical_ids=self.lexical_ids,
            payloads=self.payloads,
            limit=kwargs.pop("limit", 10),
            **kwargs,
        )

    def test_single_retriever_uses_the_rrf_formula(self) -> None:
        results = self.fuse([(1, 0.9)], [])
        self.assertEqual(results[0]["app_id"], 1)
        self.assertAlmostEqual(results[0]["rrf"], 1 / (RRF_K + 1))
        expected = 1 / (RRF_K + 1) + QUALITY_WEIGHT * quality_score(self.payloads[1])
        self.assertAlmostEqual(results[0]["hybrid_score"], expected)
        self.assertAlmostEqual(results[0]["match_percent"], 100.0)

    def test_hit_in_both_rankings_outranks_a_hit_in_one(self) -> None:
        # lexical tuples carry document indexes, and lexical_ids maps index -> app_id.
        results = self.fuse([(1, 0.9), (2, 0.8)], [(0, 5.0)])
        self.assertEqual([item["app_id"] for item in results], [1, 2])
        self.assertAlmostEqual(results[0]["rrf"], 2 / (RRF_K + 1))
        self.assertAlmostEqual(results[1]["rrf"], 1 / (RRF_K + 2))

    def test_lexical_indices_map_through_lexical_ids(self) -> None:
        results = self.fuse([], [(2, 7.0)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["app_id"], 3)
        self.assertEqual(results[0]["bm25_score"], 7.0)
        self.assertNotIn("vector_score", results[0])

    def test_exclude_id_drops_the_query_item_from_both_lists(self) -> None:
        results = self.fuse([(1, 0.99), (2, 0.5)], [(0, 9.0), (1, 8.0)], exclude_id=1)
        self.assertEqual([item["app_id"] for item in results], [2])

    def test_limit_truncates_after_fusion(self) -> None:
        results = self.fuse([(1, 0.9), (2, 0.8), (3, 0.7)], [], limit=2)
        self.assertEqual(len(results), 2)

    def test_unknown_ids_without_payload_are_ranked_last(self) -> None:
        results = self.fuse([(1, 0.9), (99, 0.95)], [])
        self.assertEqual(results[0]["app_id"], 1)
        self.assertEqual(results[-1]["app_id"], 99)
        self.assertNotIn("hybrid_score", results[-1])
        self.assertAlmostEqual(results[-1]["match_percent"], 0.0)

    def test_match_percent_is_relative_to_the_best_hit(self) -> None:
        results = self.fuse([(1, 0.9), (2, 0.8)], [])
        best, second = results[0], results[1]
        expected = round(second["hybrid_score"] / best["hybrid_score"] * 100, 1)
        self.assertAlmostEqual(second["match_percent"], expected)
        self.assertLess(second["match_percent"], best["match_percent"])

    def test_empty_inputs_produce_empty_output(self) -> None:
        self.assertEqual(self.fuse([], []), [])


if __name__ == "__main__":
    unittest.main()
