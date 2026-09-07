#!/usr/bin/env python3
"""Evaluate the Enza visual evidence index with indexed-image queries."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.build_vision_index import CudaVisionEmbedder, l2_normalize, resolve_data_root
    from tools.query_evidence import SIMILARITY_EPSILON, load_evidence_index
except ModuleNotFoundError as error:
    if error.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.build_vision_index import CudaVisionEmbedder, l2_normalize, resolve_data_root
    from tools.query_evidence import SIMILARITY_EPSILON, load_evidence_index


def _references(row: dict[str, Any], singular: str, related: str) -> set[str]:
    value = row.get(singular, row.get(related))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    return set()


def _state_key(row: dict[str, Any]) -> str | None:
    phase = row.get("phase")
    if isinstance(phase, str) and phase:
        return f"phase:{phase}"
    state = row.get("state")
    if state is None:
        return None
    return "state:" + json.dumps(state, ensure_ascii=False, sort_keys=True)


def _rate(hits: int, eligible: int) -> float | None:
    return hits / eligible if eligible else None


def evaluate_retrieval(
    root: Path,
    *,
    sample_size: int,
    top_k: int,
    seed: int,
    device: int = 0,
    faiss_module: Any | None = None,
    embedder_factory: Any = CudaVisionEmbedder,
) -> dict[str, Any]:
    if sample_size <= 0 or top_k <= 0:
        raise ValueError("sample-size and top-k must be positive")
    index, rows_by_vector, state = load_evidence_index(root, faiss_module=faiss_module)
    available_ids = [
        vector_id for vector_id, row in rows_by_vector.items()
        if isinstance(row.get("path"), str) and (root / row["path"]).is_file()
    ]
    if not available_ids:
        raise RuntimeError("no indexed images are available for evaluation")
    selected_ids = sorted(random.Random(seed).sample(available_ids, min(sample_size, len(available_ids))))
    paths = [root / rows_by_vector[vector_id]["path"] for vector_id in selected_ids]
    embedder = embedder_factory(str(state["model_id"]), device=device)
    vectors = l2_normalize(embedder.embed_images(paths, batch_size=min(32, len(paths))))
    if vectors.shape != (len(paths), int(index.d)):
        raise RuntimeError("evaluation embedding shape does not match the FAISS index")
    search_k = min(int(index.ntotal), top_k + 1)
    scores, identifiers = index.search(vectors, search_k)

    exact_hits = 0
    content_self_hits = content_self_eligible = 0
    run_hits = run_eligible = 0
    state_hits = state_eligible = 0
    failure_hits = failure_eligible = 0
    neighbor_scores: list[float] = []
    cases: list[dict[str, Any]] = []
    for offset, query_id in enumerate(selected_ids):
        query_row = rows_by_vector[query_id]
        ranked: list[tuple[int, float]] = []
        for identifier, raw_score in zip(identifiers[offset], scores[offset]):
            result_id = int(identifier)
            if result_id < 0:
                continue
            score = float(raw_score)
            if score > 1.0 + SIMILARITY_EPSILON or score < -1.0 - SIMILARITY_EPSILON:
                raise RuntimeError(f"similarity outside cosine bounds: {score}")
            ranked.append((result_id, max(-1.0, min(1.0, score))))
        exact = bool(ranked and ranked[0][0] == query_id)
        exact_hits += int(exact)
        query_sha = query_row.get("sha256")
        content_self = None
        if isinstance(query_sha, str) and query_sha:
            content_self_eligible += 1
            content_self = bool(
                ranked and rows_by_vector[ranked[0][0]].get("sha256") == query_sha
            )
            content_self_hits += int(content_self)
        neighbors = [(identifier, score) for identifier, score in ranked if identifier != query_id][:top_k]
        neighbor_scores.extend(score for _, score in neighbors)

        query_run = query_row.get("run_id", query_row.get("source_run"))
        same_run = None
        if query_run:
            run_eligible += 1
            same_run = any(
                rows_by_vector[identifier].get("run_id", rows_by_vector[identifier].get("source_run")) == query_run
                for identifier, _ in neighbors
            )
            run_hits += int(same_run)

        query_state = _state_key(query_row)
        same_state = None
        if query_state:
            state_eligible += 1
            same_state = any(_state_key(rows_by_vector[identifier]) == query_state for identifier, _ in neighbors)
            state_hits += int(same_state)

        query_failures = _references(query_row, "failure", "related_failures")
        same_failure = None
        if query_failures:
            failure_eligible += 1
            same_failure = any(
                bool(query_failures & _references(rows_by_vector[identifier], "failure", "related_failures"))
                for identifier, _ in neighbors
            )
            failure_hits += int(same_failure)

        cases.append({
            "query": query_row.get("path"),
            "self_rank_1": exact,
            "same_content_rank_1": content_self,
            "best_neighbor": rows_by_vector[neighbors[0][0]].get("path") if neighbors else None,
            "best_neighbor_similarity": neighbors[0][1] if neighbors else None,
            "same_run_hit": same_run,
            "same_state_hit": same_state,
            "failure_association_hit": same_failure,
        })

    import numpy as np
    distribution = {}
    if neighbor_scores:
        values = np.asarray(neighbor_scores, dtype="float32")
        distribution = {
            "min": float(values.min()),
            "p10": float(np.quantile(values, 0.10)),
            "p25": float(np.quantile(values, 0.25)),
            "median": float(np.quantile(values, 0.50)),
            "p75": float(np.quantile(values, 0.75)),
            "p90": float(np.quantile(values, 0.90)),
            "max": float(values.max()),
        }
    metrics = {
        "exact_self_retrieval_rate": _rate(exact_hits, len(selected_ids)),
        "same_content_self_retrieval_rate": _rate(content_self_hits, content_self_eligible),
        "same_run_hit_rate": _rate(run_hits, run_eligible),
        "same_phase_state_hit_rate": _rate(state_hits, state_eligible),
        "failure_association_hit_rate": _rate(failure_hits, failure_eligible),
        "average_similarity": float(np.mean(neighbor_scores)) if neighbor_scores else None,
        "score_distribution": distribution,
        "eligible_queries": {
            "same_run": run_eligible,
            "same_phase_state": state_eligible,
            "failure_association": failure_eligible,
            "same_content_self": content_self_eligible,
        },
    }
    metadata_coverage = {
        "run_id": sum(bool(row.get("run_id", row.get("source_run"))) for row in rows_by_vector.values()),
        "trajectory": sum(bool(_references(row, "trajectory", "related_trajectories")) for row in rows_by_vector.values()),
        "failure": sum(bool(_references(row, "failure", "related_failures")) for row in rows_by_vector.values()),
        "observation": sum(bool(_references(row, "observation", "related_observations")) for row in rows_by_vector.values()),
        "phase": sum(bool(row.get("phase")) for row in rows_by_vector.values()),
        "state": sum(row.get("state") is not None for row in rows_by_vector.values()),
    }
    good = [case for case in cases if case["self_rank_1"] and not any(value is False for value in (
        case["same_run_hit"], case["same_state_hit"], case["failure_association_hit"]
    ))][:5]
    bad = [case for case in cases if not case["self_rank_1"] or any(value is False for value in (
        case["same_run_hit"], case["same_state_hit"], case["failure_association_hit"]
    ))][:5]
    return {
        "model_id": state["model_id"],
        "total_indexed_images": int(index.ntotal),
        "evaluated_queries": len(selected_ids),
        "top_k": top_k,
        "seed": seed,
        "metrics": metrics,
        "metadata_coverage": metadata_coverage,
        "representative_good_cases": good,
        "representative_bad_cases": bad,
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def render_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    eligible = metrics["eligible_queries"]
    lines = [
        "# Evidence retrieval evaluation",
        "",
        f"- Model: `{result['model_id']}`",
        f"- Total indexed images: {result['total_indexed_images']}",
        f"- Evaluated queries: {result['evaluated_queries']}",
        f"- Top-k neighbors: {result['top_k']}",
        f"- Sampling seed: {result['seed']}",
        "",
        "Association metrics exclude the query image itself. Exact self retrieval is measured at rank 1.",
        "Average similarity and score distribution cover non-self top-k neighbors.",
        "",
        "| Metric | Value | Eligible queries |",
        "| --- | ---: | ---: |",
        f"| Exact self retrieval rate | {_percent(metrics['exact_self_retrieval_rate'])} | {result['evaluated_queries']} |",
        f"| Same-content rank-1 retrieval rate | {_percent(metrics['same_content_self_retrieval_rate'])} | {eligible['same_content_self']} |",
        f"| Same run hit rate | {_percent(metrics['same_run_hit_rate'])} | {eligible['same_run']} |",
        f"| Same phase/state hit rate | {_percent(metrics['same_phase_state_hit_rate'])} | {eligible['same_phase_state']} |",
        f"| Failure association hit rate | {_percent(metrics['failure_association_hit_rate'])} | {eligible['failure_association']} |",
        f"| Average similarity | {metrics['average_similarity'] if metrics['average_similarity'] is not None else 'n/a'} | — |",
        "",
        "## Metadata coverage",
        "",
        "| Field | Images | Total |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| {field} | {count} | {result['total_indexed_images']} |"
        for field, count in result["metadata_coverage"].items()
    )
    lines.extend([
        "",
        "## Score distribution",
        "",
        "```json",
        json.dumps(metrics["score_distribution"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Interpretation",
        "",
        "Exact path self retrieval can be lower than same-content retrieval when duplicate image bytes "
        "share a score and FAISS resolves the tie to another vector ID.",
        "Association rates with small eligible-query counts are diagnostic only; they are not broad "
        "quality estimates until metadata coverage increases.",
    ])
    for title, key in (("Representative good cases", "representative_good_cases"),
                       ("Representative bad cases", "representative_bad_cases")):
        lines.extend(["", f"## {title}", ""])
        cases = result[key]
        if not cases:
            lines.append("None in this sample.")
            continue
        lines.extend([
            "| Query | Same content rank 1 | Best non-self neighbor | Similarity | Same run | Same state | Same failure |",
            "| --- | --- | --- | ---: | --- | --- | --- |",
        ])
        for case in cases:
            lines.append(
                f"| {case['query']} | {case['same_content_rank_1']} | {case['best_neighbor']} | "
                f"{case['best_neighbor_similarity']} | "
                f"{case['same_run_hit']} | {case['same_state_hit']} | {case['failure_association_hit']} |"
            )
    lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", help="Override ENZA_DATA_ROOT")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--output", default="docs/evidence_retrieval_evaluation.md")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = evaluate_retrieval(
            resolve_data_root(args.data_root), sample_size=args.sample_size,
            top_k=args.top_k, seed=args.seed, device=args.device,
        )
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_report(result), encoding="utf-8")
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(output), **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
