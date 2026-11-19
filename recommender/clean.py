from __future__ import annotations

import ast
import csv
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator


# The source CSV has 39 header labels but 40 values per row:
# "DiscountDLC count" is actually two columns.
CSV_COLUMNS = [
    "AppID", "Name", "Release date", "Estimated owners", "Peak CCU", "Required age",
    "Price", "Discount", "DLC count", "About the game", "Supported languages",
    "Full audio languages", "Reviews", "Header image", "Website", "Support url",
    "Support email", "Windows", "Mac", "Linux", "Metacritic score", "Metacritic url",
    "User score", "Positive", "Negative", "Score rank", "Achievements",
    "Recommendations", "Notes", "Average playtime forever", "Average playtime two weeks",
    "Median playtime forever", "Median playtime two weeks", "Developers", "Publishers",
    "Categories", "Genres", "Tags", "Screenshots", "Movies",
]

DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%Y-%m-%d", "%b %Y", "%Y")
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
DEMO_RE = re.compile(r"\b(playtest|demo|soundtrack|original soundtrack|beta)\b", re.I)


@dataclass(frozen=True)
class CleanGame:
    app_id: int
    name: str
    normalized_name: str
    release_date: date | None
    estimated_owners_min: int | None
    estimated_owners_max: int | None
    peak_ccu: int
    price: float
    discount: int
    dlc_count: int
    description: str
    header_image: str
    website: str
    developers: list[str]
    publishers: list[str]
    categories: list[str]
    genres: list[str]
    source_tags: list[str]
    positive: int
    negative: int
    review_count: int
    recommendations: int
    achievements: int
    windows: bool
    mac: bool
    linux: bool
    average_playtime_forever: int
    median_playtime_forever: int
    search_text: str

    def as_db_tuple(self) -> tuple:
        return (
            self.app_id,
            self.name,
            self.normalized_name,
            self.release_date,
            self.estimated_owners_min,
            self.estimated_owners_max,
            self.peak_ccu,
            self.price,
            self.discount,
            self.dlc_count,
            self.description,
            self.header_image,
            self.website,
            self.developers,
            self.publishers,
            self.categories,
            self.genres,
            self.source_tags,
            self.positive,
            self.negative,
            self.review_count,
            self.recommendations,
            self.achievements,
            self.windows,
            self.mac,
            self.linux,
            self.average_playtime_forever,
            self.median_playtime_forever,
            self.search_text,
        )


def clean_text(value: str, max_chars: int | None = None) -> str:
    text = html.unescape(value or "")
    text = HTML_TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text[:max_chars] if max_chars else text


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()
    value = value.replace("&", " and ")
    return SPACE_RE.sub(" ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)).strip()


def parse_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d[\d,]*", value or "")
    if not match:
        return default
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return default


def parse_float(value: str, default: float = 0.0) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", (value or "").replace(",", ""))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def parse_bool(value: str) -> bool:
    return (value or "").strip().casefold() in {"true", "1", "yes", "y"}


def parse_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def parse_owners(value: str) -> tuple[int | None, int | None]:
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", value or "")]
    if not numbers:
        return None, None
    return numbers[0], numbers[1] if len(numbers) > 1 else numbers[0]


def parse_list(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parsed: list[str] = []
    is_literal = False
    if raw.startswith("["):
        try:
            candidate = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            candidate = None
        else:
            is_literal = True
        if isinstance(candidate, (list, tuple, set)):
            parsed = [str(item) for item in candidate]
    # "[]" means "no values": only fall back to comma splitting when the cell
    # was not a parseable Python literal, otherwise the empty list would turn
    # into a literal "[]" tag (8.7k rows of games.csv carry Tags="[]").
    if not is_literal:
        parsed = raw.split(",")
    seen: set[str] = set()
    result: list[str] = []
    for item in parsed:
        cleaned = clean_text(item).strip(" '\"")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def row_to_game(
    values: list[str],
    *,
    min_reviews: int = 0,
    exclude_non_games: bool = True,
) -> CleanGame | None:
    if len(values) < len(CSV_COLUMNS):
        values = values + [""] * (len(CSV_COLUMNS) - len(values))
    row = dict(zip(CSV_COLUMNS, values[:len(CSV_COLUMNS)]))
    app_id = parse_int(row["AppID"], 0)
    name = clean_text(row["Name"])
    if app_id <= 0 or not name:
        return None
    if exclude_non_games and DEMO_RE.search(name):
        return None

    owners_min, owners_max = parse_owners(row["Estimated owners"])
    positive = max(0, parse_int(row["Positive"]))
    negative = max(0, parse_int(row["Negative"]))
    review_count = positive + negative
    if review_count < min_reviews:
        return None

    description = clean_text(row["About the game"], max_chars=20_000)
    genres = parse_list(row["Genres"])
    categories = parse_list(row["Categories"])
    source_tags = parse_list(row["Tags"])
    developers = parse_list(row["Developers"])
    publishers = parse_list(row["Publishers"])
    search_text = " ".join([
        name,
        " ".join(genres),
        " ".join(source_tags),
        " ".join(developers),
        " ".join(publishers),
        description,
    ]).strip()

    return CleanGame(
        app_id=app_id,
        name=name,
        normalized_name=normalize_name(name),
        release_date=parse_date(row["Release date"]),
        estimated_owners_min=owners_min,
        estimated_owners_max=owners_max,
        peak_ccu=max(0, parse_int(row["Peak CCU"])),
        price=max(0.0, parse_float(row["Price"])),
        discount=max(0, min(100, parse_int(row["Discount"]))),
        dlc_count=max(0, parse_int(row["DLC count"])),
        description=description,
        header_image=clean_text(row["Header image"]),
        website=clean_text(row["Website"]),
        developers=developers,
        publishers=publishers,
        categories=categories,
        genres=genres,
        source_tags=source_tags,
        positive=positive,
        negative=negative,
        review_count=review_count,
        recommendations=max(0, parse_int(row["Recommendations"])),
        achievements=max(0, parse_int(row["Achievements"])),
        windows=parse_bool(row["Windows"]),
        mac=parse_bool(row["Mac"]),
        linux=parse_bool(row["Linux"]),
        average_playtime_forever=max(0, parse_int(row["Average playtime forever"])),
        median_playtime_forever=max(0, parse_int(row["Median playtime forever"])),
        search_text=search_text,
    )


def iter_games(
    path: str | Path,
    *,
    limit: int | None = None,
    min_reviews: int = 0,
    exclude_non_games: bool = True,
) -> Iterator[CleanGame]:
    seen_app_ids: set[int] = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # Ignore the malformed 39-label source header.
        emitted = 0
        for values in reader:
            game = row_to_game(
                values,
                min_reviews=min_reviews,
                exclude_non_games=exclude_non_games,
            )
            if game is None or game.app_id in seen_app_ids:
                continue
            seen_app_ids.add(game.app_id)
            yield game
            emitted += 1
            if limit is not None and emitted >= limit:
                return
