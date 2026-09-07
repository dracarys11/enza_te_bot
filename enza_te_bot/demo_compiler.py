"""Compile recorded human clicks into a reviewable, non-executable candidate."""
from __future__ import annotations
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def validate_demo_metadata(metadata: dict) -> None:
    if metadata.get("status") != "COMPLETED":
        raise ValueError(f"Demo is not completed (status={metadata.get('status')!r})")

def _latest(name: str) -> Path | None:
    demos = BASE_DIR / "logs" / "demos"
    exact = demos / name / "episode.jsonl"
    paths = [exact] if exact.exists() else sorted(demos.glob(f"{name}_*/episode.jsonl"), reverse=True)
    for path in paths:
        metadata_path = path.parent / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("status") == "COMPLETED":
            return path
    return None

def compile_demo(name: str) -> dict:
    trace = _latest(name)
    if trace is None: raise FileNotFoundError(f"No recorded demo found for {name}")
    metadata_path = trace.parent / "metadata.json"
    if not metadata_path.exists():
        raise ValueError(f"Demo {name} is incomplete: missing metadata status")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    validate_demo_metadata(metadata)
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    actions = {a["name"]: (state, a) for state, spec in config.get("states", {}).items() for a in spec.get("allowed_actions", [])}
    steps = []; unresolved = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("kind") not in {"demo_step", "normalized_interaction"} and rec.get("record_type") != "demo_step":
            continue
        point = rec["action"]["normalized_point"]
        captured = rec.get("human_action", rec["action"])
        matched = None
        if captured.get("classification") == "NAMED_ACTION":
            matched = {"name": captured.get("name"), "state": rec["pre"]["state"]}
        for name_, (state, action) in actions.items():
            if matched is not None:
                break
            box = action.get("box", [])
            if state == rec["pre"]["state"] and len(box) == 4 and box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]:
                matched = {"name":name_,"state":state}
                break
        item = {"step":rec["step"], "pre_state":rec["pre"]["state"], "post_state":rec["post"]["state"], "normalized_point":point,
                "matched_action":matched, "effect_evidence":{"state_changed":rec["pre"]["state"] != rec["post"]["state"]}}
        if matched is None: unresolved.append(item)
        steps.append(item)
    result = {"demo":name, "source_trace":str(trace), "preconditions":{}, "steps":steps,
              "unresolved_steps":unresolved, "production_config_modified":False}
    out = BASE_DIR / "compiled_demos"; out.mkdir(exist_ok=True); path = out / f"{name}.json"; path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / f"{name}.md").write_text("# Compiled candidate: " + name + "\n\n" + "\n".join(f"- Step {s['step']}: {s['matched_action'] or 'UNRESOLVED'}" for s in steps), encoding="utf-8")
    return result

def review_demo(name: str) -> int:
    trace = _latest(name)
    if trace is None:
        raise FileNotFoundError(f"No completed recorded demo found for {name}")
    metadata = json.loads((trace.parent / "metadata.json").read_text(encoding="utf-8"))
    validate_demo_metadata(metadata)
    print(f"Demo: {metadata['demo_id']} status={metadata['status']} steps={metadata.get('steps', '?')}")
    for line in trace.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("kind") not in {"demo_step", "normalized_interaction"} and record.get("record_type") != "demo_step":
            continue
        pre = record.get("observation", record.get("pre", {}))
        post = record.get("after_observation", record.get("post", {}))
        action = record.get("human_action", record.get("action", {}))
        transition = record.get("transition_result", record.get("effect_evidence", {}))
        parsed = pre.get("numeric", {}).get("parsed")
        week = parsed.get("weeks_remaining") if parsed else "?"
        print(f"\nStep {record['step']} / Week {week}")
        print(f"Observation: state={pre.get('state')} screenshot={pre.get('screenshot')}")
        print(f"Human action: {action.get('name') or 'UNKNOWN_CLICK'} point={action.get('normalized_point')}")
        print(f"Result: state={post.get('state')} transition={transition.get('classification')}")
        need = record.get("need_human_explanation")
        if need:
            print(f"NeedHumanExplanation: {need.get('question')}")
    print(f"\ntrace={trace}")
    return 0
