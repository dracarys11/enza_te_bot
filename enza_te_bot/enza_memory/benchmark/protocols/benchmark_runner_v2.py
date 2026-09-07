#!/usr/bin/env python3
"""Run identical ENZA benchmark cases for multiple offline participants."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BENCHMARK_ROOT.parents[1]
DEFAULT_CASES_DIR = BENCHMARK_ROOT / "cases"
DEFAULT_RESULTS_DIR = REPOSITORY_ROOT / "benchmark_results"

if str(BENCHMARK_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_ROOT))

from adapters._common import AdapterError, normalize_response  # noqa: E402
from adapters.gemini_adapter import adapt_response as adapt_gemini  # noqa: E402
from adapters.local_vlm_adapter import adapt_response as adapt_local_vlm  # noqa: E402
from adapters.openai_adapter import adapt_response as adapt_openai  # noqa: E402
from adapters.zcode_adapter import adapt_response as adapt_zcode  # noqa: E402
from evaluator.runner import evaluate  # noqa: E402


PARTICIPANT_KINDS = frozenset({"VLM", "AGENT", "HUMAN"})
ADAPTERS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "canonical": normalize_response,
    "openai": adapt_openai,
    "gemini": adapt_gemini,
    "zcode": adapt_zcode,
    "local_vlm": adapt_local_vlm,
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProtocolError(ValueError):
    """The offline comparison protocol is incomplete or inconsistent."""


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{name} must be a JSON object")
    return value


def load_cases(cases_dir: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for path in sorted(cases_dir.glob("ARB*/case.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProtocolError(f"cannot load case {path}: {error}") from error
        case_id = case.get("case_id") if isinstance(case, Mapping) else None
        if not isinstance(case_id, str) or not case_id:
            raise ProtocolError(f"case has no valid case_id: {path}")
        if case_id in cases:
            raise ProtocolError(f"duplicate case_id: {case_id}")
        cases[case_id] = dict(case)
    if not cases:
        raise ProtocolError(f"no ARB case.json files found in {cases_dir}")
    return cases


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), "manifest")
    except (OSError, json.JSONDecodeError) as error:
        raise ProtocolError(f"cannot load protocol manifest: {error}") from error


def _response_path(manifest_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ProtocolError("response path must be a non-empty string")
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _validate_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ProtocolError(f"{field} must match {SAFE_ID.pattern}")
    return value


def execute_protocol(
    manifest_path: Path,
    *,
    cases_dir: Path = DEFAULT_CASES_DIR,
    results_dir: Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Validate and score a model-free multi-participant comparison run."""
    manifest = _load_manifest(manifest_path)
    if manifest.get("protocol_version") != 1:
        raise ProtocolError("protocol_version must be 1")
    run_id = _validate_id(manifest.get("run_id"), "run_id")
    participants = manifest.get("participants")
    if not isinstance(participants, list) or not participants:
        raise ProtocolError("participants must be a non-empty array")

    cases = load_cases(cases_dir)
    required_case_ids = set(cases)
    seen_participants: set[str] = set()
    completed: list[dict[str, Any]] = []

    for offset, raw_participant in enumerate(participants):
        participant = _object(raw_participant, f"participants[{offset}]")
        participant_id = _validate_id(participant.get("participant_id"), "participant_id")
        if participant_id in seen_participants:
            raise ProtocolError(f"duplicate participant_id: {participant_id}")
        seen_participants.add(participant_id)

        kind = participant.get("kind")
        if kind not in PARTICIPANT_KINDS:
            raise ProtocolError(f"{participant_id}: kind must be VLM, AGENT, or HUMAN")
        adapter_name = participant.get("adapter")
        if adapter_name not in ADAPTERS:
            raise ProtocolError(f"{participant_id}: unknown adapter {adapter_name!r}")
        responses = _object(participant.get("responses"), f"{participant_id}.responses")
        response_case_ids = set(responses)
        if response_case_ids != required_case_ids:
            missing = sorted(required_case_ids - response_case_ids)
            extra = sorted(response_case_ids - required_case_ids)
            raise ProtocolError(
                f"{participant_id}: responses must match the common case set; "
                f"missing={missing}, extra={extra}"
            )

        evaluations = []
        adapter = ADAPTERS[str(adapter_name)]
        for case_id in sorted(cases):
            response_path = _response_path(manifest_path, responses[case_id])
            try:
                raw_response = json.loads(response_path.read_text(encoding="utf-8"))
                normalized = adapter(raw_response)
            except (OSError, json.JSONDecodeError, AdapterError) as error:
                raise ProtocolError(
                    f"{participant_id}/{case_id}: invalid response: {error}"
                ) from error
            evaluation = evaluate(cases[case_id], normalized)
            evaluation["response"] = normalized
            evaluations.append(evaluation)

        total = sum(item["score"]["total"] for item in evaluations)
        completed.append({
            "participant_id": participant_id,
            "kind": kind,
            "adapter": adapter_name,
            "case_count": len(evaluations),
            "score_total": total,
            "score_average": total / len(evaluations),
            "evaluations": evaluations,
        })

    output = results_dir / run_id
    if output.exists():
        raise ProtocolError(f"result directory already exists: {output}")
    output.mkdir(parents=True)
    for participant in completed:
        path = output / f"{participant['participant_id']}.json"
        path.write_text(
            json.dumps(participant, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    summary = {
        "protocol_version": 1,
        "run_id": run_id,
        "offline_only": True,
        "model_calls": False,
        "game_interaction": False,
        "case_ids": sorted(cases),
        "participants": [
            {key: item[key] for key in (
                "participant_id", "kind", "adapter", "case_count",
                "score_total", "score_average",
            )}
            for item in completed
        ],
    }
    (output / "run_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = execute_protocol(
            args.manifest,
            cases_dir=args.cases_dir,
            results_dir=args.results_dir,
        )
    except ProtocolError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(output)
    print("BENCHMARK_EXECUTION_PROTOCOL_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
