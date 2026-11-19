#!/usr/bin/env python3
"""Acceptance test for CS5481 Topic 1 (LLM-Enhanced Hybrid Recommendation System).

Every check is tagged with the requirement it belongs to, so a run doubles as a
requirements-coverage report:

    R1 Data Ingestion      >= 20,000 items with rich descriptive text
    R2 Feature Enrichment  LLM tags + summaries + vector embeddings per item
    R3 Data Management     raw data, structured metadata and vectors persisted
    R4 Hybrid Retrieval    item -> similar, and free-text -> BM25 + vector
    R5 Explanation         short LLM justification for every returned item

Standard library only on purpose: it must run against the docker-compose stack
or a host venv without installing anything.

    python scripts/acceptance_test.py
    python scripts/acceptance_test.py --api http://127.0.0.1:8000 --web http://127.0.0.1:3000
    python scripts/acceptance_test.py --skip-web --verbose
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

VECTOR_SIZE = 1024
MIN_ITEMS = 20_000
SAMPLE_POINTS = 300
#: A query from the assignment brief, used verbatim.
ASSIGNMENT_QUERY = "a relaxing video game with beautiful art but no combat"


class Report:
    """Collects PASS/FAIL lines grouped by requirement."""

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.rows: list[tuple[str, str, bool, str]] = []

    def section(self, title: str) -> None:
        print(f"\n=== {title} ===")

    def check(self, requirement: str, name: str, passed: bool, detail: str = "") -> bool:
        self.rows.append((requirement, name, passed, detail))
        mark = "PASS" if passed else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        return passed

    def info(self, message: str) -> None:
        if self.verbose:
            print(f"         {message}")

    @property
    def failed(self) -> list[tuple[str, str, bool, str]]:
        return [row for row in self.rows if not row[2]]

    def summary(self) -> int:
        total = len(self.rows)
        failures = self.failed
        print("\n" + "=" * 68)
        print(f"结果：{total - len(failures)}/{total} 通过")
        by_requirement: dict[str, list[bool]] = {}
        for requirement, _, passed, _ in self.rows:
            by_requirement.setdefault(requirement, []).append(passed)
        for requirement in sorted(by_requirement):
            marks = by_requirement[requirement]
            status = "OK" if all(marks) else "FAIL"
            print(f"  {requirement}  {sum(marks)}/{len(marks)}  [{status}]")
        if failures:
            print("\n失败项：")
            for requirement, name, _, detail in failures:
                print(f"  - {requirement} / {name} — {detail}")
            return 1
        print("\n全部通过")
        return 0


def http_json(
    url: str,
    *,
    data: Any | None = None,
    timeout: float = 180.0,
) -> tuple[int, Any, float]:
    """Return (status, parsed body, elapsed seconds); never raises on 4xx/5xx."""
    headers = {"Accept": "application/json"}
    body = None
    method = "GET"
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, _parse_body(raw), (time.perf_counter() - started)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return error.code, _parse_body(raw), time.perf_counter() - started


def _parse_body(raw: str) -> Any:
    """Parse JSON when possible; Next.js HTML pages and empty bodies stay raw."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:400], "chars": len(raw)}


def api_url(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def scroll_points(
    qdrant: str,
    collection: str,
    *,
    total: int,
    with_vector: bool,
) -> list[dict[str, Any]]:
    """Walk the collection in pages until ``total`` points or the end."""
    collected: list[dict[str, Any]] = []
    offset: Any = None
    while len(collected) < total:
        payload: dict[str, Any] = {
            "limit": min(100, total - len(collected)),
            "with_payload": not with_vector,
            "with_vector": with_vector,
        }
        if offset is not None:
            payload["offset"] = offset
        status, body, _ = http_json(
            api_url(qdrant, f"/collections/{collection}/points/scroll"),
            data=payload,
        )
        if status != 200:
            break
        result = (body or {}).get("result") or {}
        points = result.get("points") or []
        if not points:
            break
        collected.extend(points)
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return collected


def percentiles(samples: list[float]) -> str:
    if not samples:
        return "n/a"
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return (
        f"n={len(ordered)} min={ordered[0]:.2f}s p50={p50:.2f}s "
        f"p95={p95:.2f}s max={ordered[-1]:.2f}s "
        f"mean={statistics.mean(ordered):.2f}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Requirement-level acceptance test for the recommender stack"
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--qdrant", default="http://127.0.0.1:6333", help="Qdrant base URL")
    parser.add_argument("--web", default="http://127.0.0.1:3000", help="Next.js base URL")
    parser.add_argument("--collection", default="steam_games")
    parser.add_argument("--skip-web", action="store_true", help="Skip the Next.js checks")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    report = Report(args.verbose)

    # ------------------------------------------------------------------ R0
    report.section("基础连通性")
    status_code, health, _ = http_json(api_url(args.api, "/health"))
    report.check("R0", "FastAPI /health 返回 200", status_code == 200 and health == {"ok": True},
                 f"http={status_code}")

    status_code, status_body, status_time = http_json(api_url(args.api, "/status"), timeout=600)
    ready = bool((status_body or {}).get("ready"))
    documents = int((status_body or {}).get("documents") or 0)
    report.check("R0", "推荐服务 ready 且已载入索引", ready and documents > 0,
                 f"ready={ready} documents={documents:,} 冷启动 {status_time:.1f}s")
    report.info(f"/status: {json.dumps(status_body, ensure_ascii=False)[:300]}")

    # ------------------------------------------------------------------ R1
    report.section("R1 数据采集：≥20,000 个带丰富描述的物品")
    report.check("R1", f"已入库物品数 ≥ {MIN_ITEMS:,}", documents >= MIN_ITEMS,
                 f"documents={documents:,}")
    sampled = scroll_points(args.qdrant, args.collection, total=SAMPLE_POINTS, with_vector=False)
    descriptions = [
        str((point.get("payload") or {}).get("description") or "")
        for point in sampled
    ]
    non_empty = sum(1 for text in descriptions if text.strip())
    long_enough = sum(1 for text in descriptions if len(text) >= 200)
    # A small fraction of games.csv rows genuinely have an empty "About the game"
    # cell (54 of the first 25,110 enriched items, 0.2%). Those games are still
    # enriched from name/genres/tags, and dropping them would remove well-known
    # titles, so this is asserted as a ratio rather than per-point.
    non_empty_ratio = non_empty / len(sampled) if sampled else 0.0
    report.check("R1", "抽样点描述非空（≥98%）", non_empty_ratio >= 0.98,
                 f"{non_empty}/{len(sampled)}（{non_empty_ratio:.1%}）")
    long_ratio = long_enough / len(sampled) if sampled else 0.0
    report.check("R1", "抽样点描述长度 ≥200 字符（≥95%）", long_ratio >= 0.95,
                 f"{long_enough}/{len(sampled)} 条 ≥200 字符（{long_ratio:.1%}）")

    # ------------------------------------------------------------------ R2
    report.section("R2 特征增强：LLM 标签 + 摘要 + 向量嵌入")
    with_tags = 0
    with_summary = 0
    tag_counts: list[int] = []
    for point in sampled:
        payload = point.get("payload") or {}
        tags = payload.get("llm_tags") or []
        summary = str(payload.get("summary") or "")
        if isinstance(tags, list) and tags:
            with_tags += 1
            tag_counts.append(len(tags))
        if summary.strip():
            with_summary += 1
    report.check("R2", "每个物品都有非空 llm_tags", with_tags == len(sampled),
                 f"{with_tags}/{len(sampled)}")
    if tag_counts:
        report.info(
            f"标签数 min={min(tag_counts)} max={max(tag_counts)} "
            f"avg={statistics.mean(tag_counts):.1f}"
        )
    report.check("R2", "每个物品都有非空摘要", with_summary == len(sampled),
                 f"{with_summary}/{len(sampled)}")

    vectored = scroll_points(args.qdrant, args.collection, total=20, with_vector=True)
    dims = set()
    for point in vectored:
        vector = point.get("vector")
        if isinstance(vector, dict):
            vector = next(iter(vector.values()), None)
        if isinstance(vector, list):
            dims.add(len(vector))
    report.check("R2", f"每个物品都有 {VECTOR_SIZE} 维向量", dims == {VECTOR_SIZE},
                 f"抽样 {len(vectored)} 条，维度集合={sorted(dims)}")
    sample_payload = (sampled[0].get("payload") if sampled else {}) or {}
    report.info(
        f"样例：{sample_payload.get('name')} | tags={sample_payload.get('llm_tags')}"
    )
    report.info(f"摘要：{str(sample_payload.get('summary'))[:120]}")
    report.check("R2", "增强来源可追溯（enrichment_model 已记录）",
                 bool(sample_payload.get("enrichment_model")),
                 str(sample_payload.get("enrichment_model")))

    # ------------------------------------------------------------------ R3
    report.section("R3 数据管理：原始数据 + 结构化元数据 + 向量同库存储")
    status_code, collection_body, _ = http_json(
        api_url(args.qdrant, f"/collections/{args.collection}")
    )
    result = (collection_body or {}).get("result") or {}
    points_count = int(result.get("points_count") or 0)
    vectors_config = ((result.get("config") or {}).get("params") or {}).get("vectors") or {}
    size = vectors_config.get("size") if isinstance(vectors_config, dict) else None
    distance = vectors_config.get("distance") if isinstance(vectors_config, dict) else None
    report.check(
        "R3",
        "Qdrant 集合存在且点数一致",
        status_code == 200 and points_count == documents,
        f"points_count={points_count:,} size={size} distance={distance}",
    )

    required_fields = {
        "app_id", "name", "normalized_name", "description", "genres", "source_tags",
        "llm_tags", "summary", "positive", "negative", "review_count", "price",
        "release_date", "developers",
    }
    missing = sorted(
        field for field in required_fields
        if field not in sample_payload
    )
    report.check("R3", "结构化元数据字段齐全", not missing,
                 f"缺失字段={missing}" if missing else f"{len(required_fields)} 个关键字段全部存在")

    # ------------------------------------------------------------------ R4
    report.section("R4 混合检索：物品→相似 + 自由文本→BM25+向量")
    source_app_id = int(sample_payload.get("app_id") or 0)
    status_code, similar_body, similar_time = http_json(
        api_url(args.api, "/similar", {"q": str(source_app_id), "limit": 8})
    )
    similar_results = (similar_body or {}).get("results") or []
    source_name = ((similar_body or {}).get("source") or {}).get("name")
    returned_ids = [int(item["app_id"]) for item in similar_results]
    report.check(
        "R4",
        "按 AppID 返回前 N 个相似物品",
        status_code == 200 and len(similar_results) == 8,
        f"源={source_name}({source_app_id}) 返回 {len(similar_results)} 条"
        f"，{similar_time:.2f}s",
    )
    report.check("R4", "相似结果不包含源物品自身", source_app_id not in returned_ids,
                 f"返回 id={returned_ids}")
    for item in similar_results[:3]:
        report.info(
            f"  {item.get('name')} match={item.get('match_percent')}% "
            f"vec={item.get('vector_score')} bm25={item.get('bm25_score')}"
        )

    status_code, search_body, search_time = http_json(
        api_url(args.api, "/search", {"q": ASSIGNMENT_QUERY, "limit": 8})
    )
    search_results = (search_body or {}).get("results") or []
    report.check("R4", "自由文本查询返回排序结果",
                 status_code == 200 and len(search_results) > 0,
                 f"返回 {len(search_results)} 条，{search_time:.1f}s（含 CPU 嵌入+LLM 解释）")
    def has_vector(item: dict[str, Any]) -> bool:
        return float(item.get("vector_score") or 0) > 0

    def has_bm25(item: dict[str, Any]) -> bool:
        return float(item.get("bm25_score") or 0) > 0

    both = [item for item in search_results if has_vector(item) and has_bm25(item)]
    vector_only = [item for item in search_results if has_vector(item) and not has_bm25(item)]
    lexical_only = [item for item in search_results if has_bm25(item) and not has_vector(item)]
    breakdown = (
        f"两路同时命中 {len(both)} 条 / 仅向量 {len(vector_only)} 条"
        f" / 仅词法 {len(lexical_only)} 条"
    )
    report.check("R4", "向量与 BM25 两路都参与了融合", len(both) > 0, breakdown)
    for item in search_results[:3]:
        report.info(
            f"  {item.get('name')} match={item.get('match_percent')}% "
            f"vec={item.get('vector_score')} bm25={item.get('bm25_score')}"
        )

    status_code, limited_body, _ = http_json(
        api_url(args.api, "/search", {"q": "farming", "limit": 3})
    )
    report.check("R4", "limit 参数生效", len((limited_body or {}).get("results") or []) == 3,
                 f"limit=3 -> {len((limited_body or {}).get('results') or [])} 条")

    # ------------------------------------------------------------------ R5
    report.section("R5 解释生成：每个结果都有简短说明")
    def explained(item: dict[str, Any]) -> bool:
        return bool(str(item.get("explanation") or "").strip())

    search_explained = [item for item in search_results if explained(item)]
    similar_explained = [item for item in similar_results if explained(item)]
    report.check("R5", "自由文本查询的每个结果都有解释",
                 len(search_explained) == len(search_results) and bool(search_results),
                 f"{len(search_explained)}/{len(search_results)}")
    report.check("R5", "相似推荐的每个结果都有解释",
                 len(similar_explained) == len(similar_results) and bool(similar_results),
                 f"{len(similar_explained)}/{len(similar_results)}")
    llm_enabled = bool((status_body or {}).get("llm_explanations"))
    report.check("R5", "解释由 LLM 生成（而非标签回退）", llm_enabled,
                 f"llm_explanations={llm_enabled} model={(status_body or {}).get('chat_model')}")
    if search_explained:
        report.info(f"解释样例：{search_explained[0].get('explanation')}")
        lengths = [len(str(item.get("explanation"))) for item in search_explained]
        report.info(f"解释长度 min={min(lengths)} max={max(lengths)}")

    # ------------------------------------------------------------------ 健壮性
    report.section("健壮性：参数与错误处理")
    status_code, _, _ = http_json(api_url(args.api, "/similar", {"q": "No Such Game Xyzzy"}))
    report.check("R6", "不存在的游戏返回 404", status_code == 404, f"http={status_code}")
    status_code, _, _ = http_json(api_url(args.api, "/similar", {"q": "   "}))
    report.check("R6", "空白游戏名返回 400", status_code == 400, f"http={status_code}")
    status_code, _, _ = http_json(api_url(args.api, "/search", {"q": "farming", "limit": 50}))
    report.check("R6", "limit 超过上限返回 422", status_code == 422, f"http={status_code}")

    # ------------------------------------------------------------------ 延迟
    report.section("延迟（题目要求低延迟）")
    # A repeated (query, result-set) pair is served from the explanation cache, so
    # measuring the same string twice would report ~0.15s and hide the real cost.
    # Every query carries a one-off nonce: the first call exercises embedding +
    # LLM explanation, the immediate second call reflects retrieval alone.
    nonce = f"r{int(time.time()) % 100000}"
    bases = ("cozy farming", "puzzle art", "visual novel romance", "cold war strategy")
    cold: list[float] = []
    cached: list[float] = []
    for base in bases:
        query = f"{base} {nonce}"
        _, _, elapsed = http_json(api_url(args.api, "/search", {"q": query, "limit": 8}))
        cold.append(elapsed)
        _, _, elapsed = http_json(api_url(args.api, "/search", {"q": query, "limit": 8}))
        cached.append(elapsed)
    similar_latencies: list[float] = []
    for target in (source_app_id, 730, 570, 4000):
        status_code, _, elapsed = http_json(
            api_url(args.api, "/similar", {"q": str(target), "limit": 8})
        )
        if status_code == 200:
            similar_latencies.append(elapsed)
    print(f"  [INFO] /search 冷查询（含 CPU 嵌入 + LLM 解释） {percentiles(cold)}")
    print(f"  [INFO] /search 重复查询（检索，解释命中缓存）   {percentiles(cached)}")
    print(f"  [INFO] /similar（解释可能命中缓存）           {percentiles(similar_latencies)}")
    report.check("R7", "检索本身 p50 < 1s（解释命中缓存时）",
                 bool(cached) and statistics.median(cached) < 1.0,
                 f"p50={statistics.median(cached):.2f}s")
    report.check("R7", "含 LLM 解释的冷查询 p50 < 20s",
                 bool(cold) and statistics.median(cold) < 20.0,
                 f"p50={statistics.median(cold):.2f}s")

    # ------------------------------------------------------------------ web
    if not args.skip_web:
        report.section("Web 层（Next.js）")
        status_code, _, _ = http_json(api_url(args.web, "/"), timeout=120)
        report.check("R8", "首页 / 返回 200", status_code == 200, f"http={status_code}")
        status_code, proxy_body, proxy_time = http_json(
            api_url(args.web, "/api/recommender/status"), timeout=300
        )
        proxy_documents = int((proxy_body or {}).get("documents") or 0)
        report.check(
            "R8",
            "web → api 代理可达",
            status_code == 200 and proxy_documents == documents,
            f"documents={proxy_documents} {proxy_time:.2f}s",
        )
        status_code, deals_body, deals_time = http_json(
            api_url(args.web, "/api/deals", {"page": 1, "pageSize": 8}), timeout=600
        )
        total_items = int((deals_body or {}).get("totalItems") or 0)
        report.check("R8", "/api/deals 读取 games.csv 成功",
                     status_code == 200 and total_items > 0,
                     f"totalItems={total_items:,} {deals_time:.1f}s")

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
