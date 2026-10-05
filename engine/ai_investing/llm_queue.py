"""Scheduled ProDesk-side LLM queue drain.

The autonomous engine only creates durable jobs when ``LLM_QUEUE_ENABLED`` is
true. This command is the sole release valve: systemd starts it at the three
configured Singapore-time windows, and it sends one request at a time. Results
land in the normal inference cache, so the next engine cycle consumes them
without a second provider call.
"""
from __future__ import annotations

import argparse
import json

from ai_investing.config import settings
from ai_investing.data.inference_control import DeferredInference, InferenceControl
from ai_investing.data.news import _call_llm_uncached, llm_fingerprint
from ai_investing.brain import events as events_mod
from ai_investing.brain.graph import KnowledgeGraph


def _run_job(job: dict):
    return _call_llm_uncached(
        job["prompt"], settings,
        max_tokens=int(job["max_tokens"]),
        tier=job["tier"],
        json_mode=bool(job["json_mode"]),
    )


def _materialize_pending_events(control: InferenceControl) -> int:
    """Turn every durable headline into the normal ten-item extraction jobs.

    This is intentionally separate from the drain: it only writes queue rows and
    never contacts an LLM. The scheduled worker can therefore build the complete
    backlog first, then release it one request at a time.
    """
    rows = control.db.execute(
        "SELECT payload FROM pending_news ORDER BY first_seen, id").fetchall()
    headlines = []
    for row in rows:
        try:
            item = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("title"):
            headlines.append(item)
    if not headlines:
        return 0
    graph = KnowledgeGraph.load(settings.brain.graph_path)
    node_ids = ", ".join(
        f"{node.id} [{node.label}]" if getattr(node, "label", "") else node.id
        for node in graph.nodes.values() if node.type != "asset")
    fingerprint = llm_fingerprint(settings, "fast", 6000, True)
    queued = 0
    for start in range(0, len(headlines), events_mod._BATCH):
        chunk = headlines[start:start + events_mod._BATCH]
        prompt = events_mod._prompt(chunk, node_ids, graph)
        result = control.call(
            "event_extraction", fingerprint, prompt, lambda: None,
            json_mode=True, max_tokens=6000, tier="fast", settings=settings)
        if isinstance(result, DeferredInference):
            queued += 1
    return queued


def main() -> int:
    parser = argparse.ArgumentParser(description="Drain the scheduled AI-Investing LLM queue")
    parser.add_argument("--status", action="store_true", help="print queue counts and exit")
    parser.add_argument("--max-jobs", type=int, default=None,
                        help="override the per-run job limit; 0 means no limit")
    parser.add_argument("--materialize-only", action="store_true",
                        help="create queued jobs from all pending headlines without sending them")
    args = parser.parse_args()

    control = InferenceControl(settings)
    try:
        if args.status:
            print(json.dumps(control.queue_status(), indent=2))
            print(f"pending={control.pending_count()}")
            return 0
        materialized = _materialize_pending_events(control)
        if args.materialize_only:
            print(json.dumps({"materialized_event_batches": materialized,
                              "pending": control.pending_count()}, sort_keys=True))
            return 0
        max_jobs = settings.llm_queue_max_jobs if args.max_jobs is None else args.max_jobs
        report = control.drain(
            _run_job,
            lease_seconds=settings.llm_queue_lease_seconds,
            max_jobs=max(0, int(max_jobs)),
        )
        report["materialized_event_batches"] = materialized
        print(json.dumps(report, sort_keys=True))
        return 0 if report["failed"] == 0 else 1
    finally:
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
