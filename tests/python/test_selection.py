"""Unit tests for :mod:`recommender.selection`.

Run with:  python -m unittest discover -s tests/python
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from recommender.clean import CSV_COLUMNS
from recommender.selection import rank_by_review_count, select_new_app_ids

#: The header games.csv really has: 39 labels for 40 values.
BROKEN_HEADER = [
    "AppID", "Name", "Release date", "Estimated owners", "Peak CCU", "Required age",
    "Price", "DiscountDLC count", "About the game", "Supported languages",
    "Full audio languages", "Reviews", "Header image", "Website", "Support url",
    "Support email", "Windows", "Mac", "Linux", "Metacritic score", "Metacritic url",
    "User score", "Positive", "Negative", "Score rank", "Achievements",
    "Recommendations", "Notes", "Average playtime forever", "Average playtime two weeks",
    "Median playtime forever", "Median playtime two weeks", "Developers", "Publishers",
    "Categories", "Genres", "Tags", "Screenshots", "Movies",
]


def write_catalog(path: Path, rows: list[tuple[int, str, int]]) -> None:
    """Write a minimal games.csv-shaped file from (app_id, name, positive)."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(BROKEN_HEADER)
        for app_id, name, positive in rows:
            values = [""] * len(CSV_COLUMNS)
            values[0] = str(app_id)
            values[1] = name
            values[9] = f"{name} description"
            values[23] = str(positive)   # Positive
            values[24] = "0"             # Negative
            writer.writerow(values)


class RankByReviewCountTest(unittest.TestCase):
    def test_orders_descending_by_review_count(self) -> None:
        ranked = rank_by_review_count([(10, 100), (500, 200), (50, 300)])
        self.assertEqual(ranked, [200, 300, 100])

    def test_limit_keeps_the_most_reviewed(self) -> None:
        ranked = rank_by_review_count([(10, 100), (500, 200), (50, 300)], limit=2)
        self.assertEqual(ranked, [200, 300])

    def test_ties_keep_input_order(self) -> None:
        self.assertEqual(rank_by_review_count([(10, 1), (10, 2), (10, 3)]), [1, 2, 3])

    def test_empty_and_zero_limit(self) -> None:
        self.assertEqual(rank_by_review_count([]), [])
        self.assertEqual(rank_by_review_count([(1, 1)], limit=0), [])


class SelectNewAppIdsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "games.csv"
        write_catalog(self.path, [
            (1, "Obscure Game", 30),
            (2, "Popular Game", 9000),
            (3, "Mid Game", 400),
            (4, "Already Enriched", 50000),
            (5, "Almost No Reviews", 5),
        ])

    def test_reviews_order_prefers_popular_and_skips_known(self) -> None:
        selected = select_new_app_ids(
            self.path,
            limit=2,
            min_reviews=20,
            known_ids={4},
            order="reviews",
        )
        self.assertEqual(selected, [2, 3])

    def test_file_order_follows_the_csv(self) -> None:
        selected = select_new_app_ids(self.path, limit=3, min_reviews=20, order="file")
        self.assertEqual(selected, [1, 2, 3])

    def test_min_reviews_filters_low_signal_rows(self) -> None:
        selected = select_new_app_ids(self.path, limit=10, min_reviews=20, order="reviews")
        self.assertNotIn(5, selected)
        self.assertEqual(selected, [4, 2, 3, 1])

    def test_rejects_unknown_order(self) -> None:
        with self.assertRaises(ValueError):
            select_new_app_ids(self.path, limit=1, order="popularity")


if __name__ == "__main__":
    unittest.main()
