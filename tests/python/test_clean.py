"""Unit tests for :mod:`recommender.clean`.

Focus: the 39-label / 40-value column shift in the source CSV, plus the small
parsers whose edge cases the enrichment pipeline depends on.

Run with:  python -m unittest discover -s tests/python
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from recommender.clean import (
    CSV_COLUMNS,
    clean_text,
    iter_games,
    normalize_name,
    parse_date,
    parse_list,
    parse_owners,
    row_to_game,
)

#: Header as it really appears in games.csv: 39 labels for 40 values.
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


def build_row(**overrides: str) -> list[str]:
    """Build a 40-value row laid out the way games.csv actually stores it."""
    values = [""] * len(CSV_COLUMNS)
    values[0] = "413150"
    values[1] = "Stardew Valley"
    values[2] = "Feb 26, 2016"
    values[3] = "1,000,000 - 2,000,000"
    values[4] = "90000"
    values[5] = "0"
    values[6] = "14.99"          # Price
    values[7] = "0"              # Discount
    values[8] = "0"              # DLC count  <-- the column the header loses
    values[9] = "You inherited a farm."  # About the game
    values[10] = "['English']"
    values[17] = "True"
    values[23] = "1000"          # Positive
    values[24] = "10"            # Negative
    values[27] = "5000"          # Recommendations
    values[33] = "['ConcernedApe']"
    values[34] = "['ConcernedApe']"
    values[35] = "['Steam Trading Cards']"
    values[36] = "['Indie','RPG']"
    values[37] = "['Farming','Pixel Graphics']"
    for key, value in overrides.items():
        values[CSV_COLUMNS.index(key)] = value
    return values


class ColumnAlignmentTest(unittest.TestCase):
    def test_header_has_one_label_less_than_values(self) -> None:
        self.assertEqual(len(CSV_COLUMNS), 40)
        self.assertEqual(len(BROKEN_HEADER), 39)
        self.assertEqual(len(build_row()), len(BROKEN_HEADER) + 1)

    def test_naive_header_zip_reads_the_wrong_column(self) -> None:
        """Documents the bug: zipping the header shifts every field by one."""
        row = build_row()
        naive = dict(zip(BROKEN_HEADER, row))
        self.assertEqual(naive["About the game"], "0")  # actually the DLC count
        self.assertEqual(naive["Supported languages"], "You inherited a farm.")

    def test_row_to_game_recovers_the_real_columns(self) -> None:
        game = row_to_game(build_row())
        assert game is not None
        self.assertEqual(game.app_id, 413150)
        self.assertEqual(game.name, "Stardew Valley")
        self.assertEqual(game.price, 14.99)
        self.assertEqual(game.dlc_count, 0)
        self.assertEqual(game.description, "You inherited a farm.")
        self.assertEqual(game.categories, ["Steam Trading Cards"])
        self.assertEqual(game.genres, ["Indie", "RPG"])
        self.assertEqual(game.source_tags, ["Farming", "Pixel Graphics"])
        self.assertEqual(game.developers, ["ConcernedApe"])
        self.assertEqual(game.review_count, 1010)
        self.assertEqual(game.release_date, date(2016, 2, 26))
        self.assertEqual((game.estimated_owners_min, game.estimated_owners_max), (1000000, 2000000))

    def test_short_rows_are_padded_instead_of_crashing(self) -> None:
        row = build_row()[:10]
        game = row_to_game(row)
        assert game is not None
        self.assertEqual(game.app_id, 413150)
        self.assertEqual(game.genres, [])


class ParserTest(unittest.TestCase):
    def test_parse_date_formats(self) -> None:
        self.assertEqual(parse_date("Aug 1, 2023"), date(2023, 8, 1))
        self.assertEqual(parse_date("2023-08-01"), date(2023, 8, 1))
        self.assertEqual(parse_date("Aug 2023"), date(2023, 8, 1))
        self.assertEqual(parse_date("2023"), date(2023, 1, 1))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("coming soon"))

    def test_parse_owners(self) -> None:
        self.assertEqual(parse_owners("0 - 20000"), (0, 20000))
        self.assertEqual(parse_owners("5,000 - 10,000"), (5000, 10000))
        self.assertEqual(parse_owners("100"), (100, 100))
        self.assertEqual(parse_owners(""), (None, None))

    def test_parse_list_handles_python_literals_and_csv_fallback(self) -> None:
        self.assertEqual(parse_list("['English', 'French']"), ["English", "French"])
        self.assertEqual(parse_list("Action, Indie"), ["Action", "Indie"])
        self.assertEqual(parse_list("[]"), [])
        self.assertEqual(parse_list(""), [])

    def test_parse_list_dedupes_case_insensitively_and_keeps_source_order(self) -> None:
        self.assertEqual(parse_list("['Indie', 'indie', 'RPG']"), ["Indie", "RPG"])

    def test_normalize_name_is_shared_by_index_and_query_side(self) -> None:
        self.assertEqual(normalize_name("Dungeons & Dragons"), "dungeons and dragons")
        self.assertEqual(normalize_name("Half-Life 2"), "half life 2")
        self.assertEqual(normalize_name("  Spaced   Out  "), "spaced out")
        self.assertEqual(normalize_name("星露谷物语"), "星露谷物语")

    def test_clean_text_strips_markup_and_entities(self) -> None:
        raw = "<p>You inherited a farm &amp; more.</p>"
        self.assertEqual(clean_text(raw), "You inherited a farm & more.")
        self.assertEqual(clean_text("abcdef", max_chars=3), "abc")


class FilteringTest(unittest.TestCase):
    def test_rejects_missing_app_id_or_name(self) -> None:
        self.assertIsNone(row_to_game(build_row(AppID="0")))
        self.assertIsNone(row_to_game(build_row(Name="")))

    def test_excludes_playtests_and_demos_by_default(self) -> None:
        row = build_row(Name="Black Dragon Mage Playtest")
        self.assertIsNone(row_to_game(row))
        self.assertIsNotNone(row_to_game(row, exclude_non_games=False))

    def test_min_reviews_threshold(self) -> None:
        row = build_row(Positive="10", Negative="5")
        self.assertIsNone(row_to_game(row, min_reviews=20))
        self.assertIsNotNone(row_to_game(row, min_reviews=15))

    def test_search_text_joins_name_genres_tags_and_description(self) -> None:
        game = row_to_game(build_row())
        assert game is not None
        for fragment in ("Stardew Valley", "Indie", "Farming", "You inherited a farm."):
            self.assertIn(fragment, game.search_text)


class IterGamesTest(unittest.TestCase):
    def test_skips_duplicates_and_honours_limit(self) -> None:
        import csv

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "games.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(BROKEN_HEADER)
                writer.writerow(build_row())
                writer.writerow(build_row())                       # duplicate AppID
                writer.writerow(build_row(AppID="730", Name="Counter-Strike 2"))
                writer.writerow(build_row(AppID="0"))              # invalid, dropped

            games = list(iter_games(path))
            self.assertEqual([game.app_id for game in games], [413150, 730])

            limited = list(iter_games(path, limit=1))
            self.assertEqual([game.app_id for game in limited], [413150])


if __name__ == "__main__":
    unittest.main()
