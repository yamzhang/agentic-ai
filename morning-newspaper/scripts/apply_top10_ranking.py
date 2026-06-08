from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from morning_newspaper.common import write_json, write_text
from morning_newspaper.models import utc_now_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply ranked titles and build top10 publishable output.")
    parser.add_argument("--input", default=str(PROJECT_ROOT / "runtime" / "drafted_items.json"))
    parser.add_argument("--selected", default=str(PROJECT_ROOT / "runtime" / "top10_ranking_result.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "runtime" / "top10_publishable.json"))
    parser.add_argument("--final-output", default=str(PROJECT_ROOT / "runtime" / "final_newspaper.json"))
    parser.add_argument("--report", default=str(PROJECT_ROOT / "runtime" / "top10_publishable_preview.md"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    selected_path = Path(args.selected)
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")
    if not selected_path.exists():
        raise SystemExit(f"ranking result file not found: {selected_path}")

    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    selected_payload = json.loads(selected_path.read_text(encoding="utf-8"))
    items = input_payload.get("items", []) if isinstance(input_payload, dict) else []
    top10_rank_ids = selected_payload.get("top10_rank_ids", []) if isinstance(selected_payload, dict) else []
    top10_titles = selected_payload.get("top10_titles", []) if isinstance(selected_payload, dict) else []
    if not isinstance(items, list):
        raise SystemExit("invalid input format")

    if isinstance(top10_rank_ids, list) and top10_rank_ids:
        available_rank_ids = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            rank_id = str(item.get("rank_id", "")).strip()
            if not rank_id:
                shortlist_rank = item.get("shortlist_rank")
                rank_id = f"ID{shortlist_rank}" if shortlist_rank is not None else ""
            if rank_id:
                available_rank_ids.add(rank_id)
        matched_rank_ids = [str(rank_id).strip() for rank_id in top10_rank_ids if str(rank_id).strip() in available_rank_ids]
        if top10_rank_ids and (not matched_rank_ids or len(matched_rank_ids) < min(len(top10_rank_ids), max(3, len(top10_rank_ids) // 2))):
            raise SystemExit(
                f"ranking results appear stale or mismatched: matched {len(matched_rank_ids)}/{len(top10_rank_ids)} rank ids against current input"
            )

        ranking_map = {str(rank_id).strip(): idx for idx, rank_id in enumerate(top10_rank_ids, 1) if str(rank_id).strip()}
        publishable: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rank_id = str(item.get("rank_id", "")).strip()
            if not rank_id:
                shortlist_rank = item.get("shortlist_rank")
                rank_id = f"ID{shortlist_rank}" if shortlist_rank is not None else ""
            rank = ranking_map.get(rank_id)
            if rank is None:
                continue
            publishable.append({
                "rank": rank,
                "item_id": str(item.get("item_id", "")).strip(),
                "title": str(item.get("title_zh", "")).strip() or str(item.get("title", "")).strip(),
                "summary": str(item.get("summary_main", "")).strip(),
                "published_at": str(item.get("published_at", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "source_name": str(item.get("source_name", "")).strip(),
                "source_type": str(item.get("source_type", "")).strip(),
            })
    else:
        if not isinstance(top10_titles, list):
            raise SystemExit("invalid input format")
        available_titles = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            title_zh = str(item.get("title_zh", "")).strip()
            if title:
                available_titles.add(title)
            if title_zh:
                available_titles.add(title_zh)
        matched_titles = [str(title).strip() for title in top10_titles if str(title).strip() in available_titles]
        if top10_titles and (not matched_titles or len(matched_titles) < min(len(top10_titles), max(3, len(top10_titles) // 2))):
            raise SystemExit(
                f"ranking results appear stale or mismatched: matched {len(matched_titles)}/{len(top10_titles)} titles against current input"
            )

        ranking_map = {str(title).strip(): idx for idx, title in enumerate(top10_titles, 1) if str(title).strip()}
        publishable: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            title_zh = str(item.get("title_zh", "")).strip()
            rank = ranking_map.get(title)
            if rank is None and title_zh:
                rank = ranking_map.get(title_zh)
            if rank is None:
                continue
            publishable.append({
                "rank": rank,
                "item_id": str(item.get("item_id", "")).strip(),
                "title": str(item.get("title_zh", "")).strip() or title,
                "summary": str(item.get("summary_main", "")).strip(),
                "published_at": str(item.get("published_at", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "source_name": str(item.get("source_name", "")).strip(),
                "source_type": str(item.get("source_type", "")).strip(),
            })

    publishable.sort(key=lambda row: int(row.get("rank", 10**9)))
    generated_at = utc_now_iso()
    publishable_payload = {
        "generated_at": generated_at,
        "input": str(input_path),
        "ranking_result_file": str(selected_path),
        "count": len(publishable),
        "items": publishable,
    }
    write_json(Path(args.output), publishable_payload)
    write_json(Path(args.final_output), {
        "generated_at": generated_at,
        "headline": "今日 AI 早报",
        "count": len(publishable),
        "source_count": len(publishable),
        "items_used": [str(item.get("item_id", "")).strip() for item in publishable],
        "generation_mode": "publishable_synced",
        "items": [
            {
                "rank": item.get("rank"),
                "item_id": item.get("item_id", ""),
                "title": item.get("title", ""),
                "title_zh": item.get("title", ""),
                "source_name": item.get("source_name", ""),
                "source_type": item.get("source_type", ""),
                "priority": "Important" if int(item.get("rank", 99) or 99) <= 3 else "FYI",
                "url": item.get("url", ""),
                "published_at": item.get("published_at", ""),
                "summary_zh": item.get("summary", ""),
                "summary_main": item.get("summary", ""),
                "card_title": item.get("title", ""),
                "card_summary": item.get("summary", ""),
            }
            for item in publishable
        ],
    })
    write_text(Path(args.report), _render_report(publishable))
    print(f"publishable items={len(publishable)}")
    print(f"wrote {args.output}")
    print(f"wrote {args.final_output}")


def _render_report(items: List[Dict[str, Any]]) -> str:
    lines = [
        "# Top10 Publishable Preview",
        "",
        f"- generated_at: {utc_now_iso()}",
        f"- count: {len(items)}",
        "",
    ]
    for item in items:
        lines.append(
            f"{item.get('rank', '')}. {item.get('title', '')} "
            f"({item.get('published_at', '')})"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
