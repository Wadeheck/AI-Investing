#!/usr/bin/env python3
"""One-time: seed `abs_ratio` in `learning_state.json` from the settled record.

§4.45 split `ratio` into a signed average (drift detection) and a magnitude
average (`abs_ratio`, which `calibration_gain` reads). Existing buckets have no
`abs_ratio`, so they fall back to the old signed reading — which is the very
inversion the fix exists to remove. On the live record that fallback gives a
gain of 0.732: still shrinking an expectation the same data says is ~14x too
small. It self-corrects once about a dozen new claims settle, i.e. roughly a
week of the event sleeve, and running backwards for a week is avoidable.

`expectations.jsonl` already holds every settled claim with its expected and
realised move, so the magnitude can be computed from what actually happened
rather than assumed.

METHOD, and why it is the conservative choice:

  - MEDIAN of |realised / expected| over settled, non-gap-affected claims. Not
    the mean: the record contains a 106x observation (`000660.KS`, expected
    0.11%, realised 11.4%) and a mean would let one outcome set the correction,
    which is precisely what RATIO_CLIP was written to prevent.
  - `n` is NOT touched. The gain is shrunk by sample count, so leaving `n`
    alone keeps the correction appropriately damped — this seeds the estimate,
    it does not claim more evidence than exists.
  - Bounded by MAG_CLIP, same as the live path.
  - Idempotent: a bucket that already has `abs_ratio` is left alone.

Read-only against `expectations.jsonl`; writes only `learning_state.json`, and
only the one field. `--dry-run` first.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.config import Settings                       # noqa: E402
from ai_investing.learning.spine import MAG_CLIP               # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args(argv)

    settings = Settings()
    data = Path(os.path.dirname(os.path.abspath(settings.state_path)))
    state_path = data / "learning_state.json"
    claims_path = data / "expectations.jsonl"

    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {state_path}: {exc}")
        return 1

    # policy -> [|true ratio|, ...]
    mags: dict[str, list[float]] = {}
    settled = clipped = 0
    try:
        for line in claims_path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("state") != "settled" or r.get("gap_affected"):
                continue
            exp, real = r.get("expected_move"), r.get("realized_move")
            if not exp or real is None:
                continue
            settled += 1
            true = abs(real / exp)
            clipped += abs(r.get("ratio", 0)) >= 2.999
            mags.setdefault(r.get("policy") or "?", []).append(min(MAG_CLIP, true))
    except OSError as exc:
        print(f"cannot read {claims_path}: {exc}")
        return 1

    if not mags:
        print("no settled claims to learn from — nothing to do")
        return 0

    print(f"settled claims: {settled}  (clipped at +/-3.0: {clipped})")
    changed = []
    for scope in ("policies", "drivers"):
        for key, bucket in (state.get(scope) or {}).items():
            policy = key.split("@")[0]
            vals = mags.get(policy) or (mags.get("?") if scope == "drivers" else None)
            if not vals or bucket.get("abs_ratio") is not None:
                continue
            vals = sorted(vals)
            median = vals[len(vals) // 2]
            changed.append((scope, key, bucket.get("ratio"), median, bucket.get("n")))
            if not args.dry_run:
                bucket["abs_ratio"] = round(median, 4)

    if not changed:
        print("every bucket already has abs_ratio — nothing to do")
        return 0

    print(f"\n{'bucket':34s}{'n':>4}{'signed':>9}{'-> abs_ratio':>14}")
    for scope, key, signed, median, n in changed:
        print(f"{scope + '/' + key:34s}{n or 0:>4}"
              f"{(signed if signed is not None else 0):>9.3f}{median:>14.2f}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(state_path)
    print(f"\nwritten to {state_path}")

    from ai_investing.learning.spine import LearningSpine
    sp = LearningSpine(settings)
    for _, key, _, _, _ in changed:
        if "/" not in key and "@" not in key:
            print(f"  calibration_gain({key}) is now "
                  f"{sp.calibration_gain(key):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
