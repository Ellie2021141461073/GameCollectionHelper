"""Dataset statistics for games.csv, used for the CS5481 report.

This script reuses :mod:`recommender.clean` so the numbers it reports describe
exactly the records the recommender can actually consume. That matters because
the source CSV has 39 header labels but 40 values per row: any naive
``pandas.read_csv`` / ``csv.DictReader`` access shifts every column after
``DiscountDLC count`` by one position and therefore under-reports
``About the game`` coverage by an order of magnitude.

Usage:
    python -m recommender.dataset_stats
    python -m recommender.dataset_stats --data games.csv --min-reviews 20
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from .clean import iter_games

# Kept local so this script depends on the standard library only: it must run
# before `pip install -r recommender/requirements.txt` has happened.
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report games.csv dataset statistics")
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "games.csv")
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=20,
        help="Review threshold considered the usable pool (default: 20)",
    )
    return parser.parse_args()


def count_raw_rows(path: Path) -> int:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"Dataset not found: {args.data}")

    raw_rows = count_raw_rows(args.data)
    total = 0
    with_description = 0
    long_description = 0
    usable = 0
    usable_with_description = 0
    trading_cards = 0
    free = 0
    app_ids: set[int] = set()
    description_buckets: Counter[str] = Counter()
    years: Counter[int] = Counter()
    genres: Counter[str] = Counter()

    for game in iter_games(args.data, exclude_non_games=False):
        total += 1
        app_ids.add(game.app_id)
        if game.description:
            with_description += 1
        if len(game.description) >= 200:
            long_description += 1
        length = len(game.description)
        if length == 0:
            description_buckets["0"] += 1
        elif length < 200:
            description_buckets["1-199"] += 1
        elif length < 1000:
            description_buckets["200-999"] += 1
        elif length < 5000:
            description_buckets["1k-5k"] += 1
        else:
            description_buckets["5k+"] += 1
        if game.release_date:
            years[game.release_date.year] += 1
        for genre in game.genres:
            genres[genre] += 1
        if any("trading card" in category.casefold() for category in game.categories):
            trading_cards += 1
        if game.price == 0:
            free += 1
        if game.review_count >= args.min_reviews:
            usable += 1
            if game.description:
                usable_with_description += 1

    print(f"file                : {args.data}")
    print(f"size                : {args.data.stat().st_size:,} bytes")
    print(f"raw csv rows        : {raw_rows:,}")
    print(f"parsed records      : {total:,}")
    print(f"unique AppIDs       : {len(app_ids):,}")
    print(f"non-empty About     : {with_description:,} ({with_description / max(1, total):.1%})")
    print(f"About >= 200 chars  : {long_description:,}")
    print(f"price == 0 (free)   : {free:,}")
    print(f"has trading cards   : {trading_cards:,}")
    print(f"reviews >= {args.min_reviews:<3}     : {usable:,}")
    print(f"  + has description : {usable_with_description:,}")
    print()
    print("description length buckets:")
    for label in ("0", "1-199", "200-999", "1k-5k", "5k+"):
        value = description_buckets.get(label, 0)
        print(f"  {label:<8} {value:>8,}")
    print()
    print("top 15 release years:")
    for year, count in years.most_common(15):
        print(f"  {year}  {count:>7,}")
    print()
    print("top 15 genres:")
    for genre, count in genres.most_common(15):
        print(f"  {genre:<28} {count:>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
