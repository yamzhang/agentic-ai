from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _validate_title_shortlist_result(selected_path: Path, candidates_path: Path) -> None:
    if not selected_path.exists() or not candidates_path.exists():
        raise SystemExit(f'missing required result files: {selected_path.name}')
    selected_payload = _load_json(selected_path)
    candidates_payload = _load_json(candidates_path)
    ranked_titles = selected_payload.get('ranked_titles', []) or selected_payload.get('selected_titles', [])
    titles = candidates_payload.get('titles', [])
    available_titles = {str(row.get('title', '')).strip() for row in titles if isinstance(row, dict) and str(row.get('title', '')).strip()}
    ranked_titles = [str(title).strip() for title in ranked_titles if str(title).strip()]
    matched_titles = [title for title in ranked_titles if title in available_titles]
    if ranked_titles and (not matched_titles or len(matched_titles) < min(len(ranked_titles), max(3, len(ranked_titles) // 2))):
        raise SystemExit(
            f'title_shortlist_result.json stale or mismatched for current title_candidates.json: matched {len(matched_titles)}/{len(ranked_titles)}'
        )


def _validate_draft_result(result_path: Path, input_path: Path) -> None:
    if not result_path.exists() or not input_path.exists():
        raise SystemExit(f'missing required result files: {result_path.name}')
    result_payload = _load_json(result_path)
    input_payload = _load_json(input_path)
    drafts = result_payload.get('drafts', [])
    items = input_payload.get('items', [])
    valid_rank_ids = {f"ID{row.get('shortlist_rank')}" for row in items if isinstance(row, dict) and row.get('shortlist_rank') is not None}
    valid_titles = {str(row.get('title', '')).strip() for row in items if isinstance(row, dict) and str(row.get('title', '')).strip()}
    draft_rank_ids = [str(row.get('rank_id', '')).strip() for row in drafts if isinstance(row, dict) and str(row.get('rank_id', '')).strip()]
    draft_titles = [str(row.get('title', '')).strip() for row in drafts if isinstance(row, dict) and str(row.get('title', '')).strip()]
    rank_matches = [rank_id for rank_id in draft_rank_ids if rank_id in valid_rank_ids]
    title_matches = [title for title in draft_titles if title in valid_titles]
    if drafts and not rank_matches and not title_matches:
        raise SystemExit('draft_result.json stale or mismatched for current draft_input.json: no entries match by rank_id or title')


def _validate_ranking_result(result_path: Path, input_path: Path) -> None:
    if not result_path.exists() or not input_path.exists():
        raise SystemExit(f'missing required result files: {result_path.name}')
    result_payload = _load_json(result_path)
    input_payload = _load_json(input_path)
    items = input_payload.get('items', [])
    top10_rank_ids = result_payload.get('top10_rank_ids', [])
    top10_titles = result_payload.get('top10_titles', [])
    available_rank_ids = set()
    available_titles = set()
    for row in items:
        if not isinstance(row, dict):
            continue
        rank_id = str(row.get('rank_id', '')).strip()
        if not rank_id and row.get('shortlist_rank') is not None:
            rank_id = f"ID{row.get('shortlist_rank')}"
        if rank_id:
            available_rank_ids.add(rank_id)
        title = str(row.get('title', '')).strip()
        title_zh = str(row.get('title_zh', '')).strip()
        if title:
            available_titles.add(title)
        if title_zh:
            available_titles.add(title_zh)
    selected_rank_ids = [str(x).strip() for x in top10_rank_ids if str(x).strip()]
    selected_titles = [str(x).strip() for x in top10_titles if str(x).strip()]
    if selected_rank_ids:
        matched_rank_ids = [rank_id for rank_id in selected_rank_ids if rank_id in available_rank_ids]
        if not matched_rank_ids or len(matched_rank_ids) < min(len(selected_rank_ids), max(3, len(selected_rank_ids) // 2)):
            raise SystemExit(
                f'top10_ranking_result.json stale or mismatched for current top10_ranking_input.json: matched {len(matched_rank_ids)}/{len(selected_rank_ids)} rank ids'
            )
    elif selected_titles:
        matched_titles = [title for title in selected_titles if title in available_titles]
        if not matched_titles or len(matched_titles) < min(len(selected_titles), max(3, len(selected_titles) // 2)):
            raise SystemExit(
                f'top10_ranking_result.json stale or mismatched for current top10_ranking_input.json: matched {len(matched_titles)}/{len(selected_titles)} titles'
            )
    else:
        raise SystemExit('top10_ranking_result.json invalid: missing top10_rank_ids/top10_titles')


def run(cmd: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run stable daily Morning-Newspaper-Assistant pipeline.')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--skip-tavily', action='store_true')
    parser.add_argument('--rebuild-dashboard-only', action='store_true')
    parser.add_argument('--results-dir', default='runtime_results', help='Directory containing LLM/manual result files for this run.')
    args = parser.parse_args()

    py = args.python
    root = PROJECT_ROOT

    if args.rebuild_dashboard_only:
        run([py, 'scripts/build_dashboard.py'], cwd=root)
        run([py, 'scripts/check_runtime_status.py'], cwd=root)
        return

    run([py, 'scripts/collect_mailbox.py'], cwd=root)

    collect_cmd = [py, 'scripts/collect_raw.py']
    if args.skip_tavily:
        collect_cmd.append('--skip-tavily')
    run(collect_cmd, cwd=root)
    run([py, 'scripts/enrich_content.py'], cwd=root)
    run([py, 'scripts/prepare_title_shortlist.py'], cwd=root)

    runtime = root / 'runtime'
    results_dir = root / args.results_dir
    required = [
        results_dir / 'title_shortlist_result.json',
        results_dir / 'draft_result.json',
        results_dir / 'top10_ranking_result.json',
    ]
    missing = [str(p.name) for p in required if not p.exists()]
    if missing:
        raise SystemExit('missing required result files: ' + ', '.join(missing))

    title_result = results_dir / 'title_shortlist_result.json'
    draft_result = results_dir / 'draft_result.json'
    ranking_result = results_dir / 'top10_ranking_result.json'

    _validate_title_shortlist_result(title_result, runtime / 'title_candidates.json')
    run([py, 'scripts/apply_title_shortlist.py', '--selected', str(title_result)], cwd=root)
    run([py, 'scripts/prepare_draft_input.py'], cwd=root)
    _validate_draft_result(draft_result, runtime / 'draft_input.json')
    run([py, 'scripts/apply_draft_results.py', '--result', str(draft_result)], cwd=root)
    run([py, 'scripts/prepare_top10_ranking.py'], cwd=root)
    _validate_ranking_result(ranking_result, runtime / 'top10_ranking_input.json')
    run([py, 'scripts/apply_top10_ranking.py', '--selected', str(ranking_result)], cwd=root)
    run([py, 'scripts/build_dashboard.py'], cwd=root)
    run([py, 'scripts/check_runtime_status.py'], cwd=root)


if __name__ == '__main__':
    main()
