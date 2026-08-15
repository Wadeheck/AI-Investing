#!/usr/bin/env python3
"""Daily, automatic re-check of the adviser-sizing evidence gate
(engine/ai_investing/brain/adviser_gate.py). Runs cheap SQL against brain.db and
journal.db (no market calls, no LLM), persists the verdict, and notifies on
Telegram ONLY when the eligibility flag actually changes -- so this is silent
noise on every one of the (many) days the answer is still "not yet", and says
something the one day it flips.

This is the whole point of the gate: nobody has to remember to check whether
the adviser's long-side calls have earned a say in position sizing. This does,
daily, on its own.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.adviser_gate import evaluate  # noqa: E402
from ai_investing.config import Settings  # noqa: E402


def main() -> int:
    settings = Settings()
    gate_path = Path(settings.state_path).parent / "adviser_gate.json"
    was_eligible = False
    try:
        was_eligible = bool(json.loads(gate_path.read_text()).get("eligible", False))
    except (OSError, json.JSONDecodeError):
        pass

    result = evaluate(settings)
    adv, fml = result["adviser_long"], result["formula_short"]
    print(f"adviser gate: eligible={result['eligible']}  "
          f"adviser_long n={adv['n']} days={adv['days']} hit={adv['hit']:.3f}  "
          f"formula_short n={fml['n']} days={fml['days']} hit={fml['hit']:.3f}",
          flush=True)

    if result["eligible"] != was_eligible:
        try:
            from ai_investing.alerts import get_notifier
            notifier = get_notifier(settings)
            if result["eligible"]:
                notifier.send(
                    "🔓 *Adviser sizing gate: now ELIGIBLE.*\n"
                    f"adviser long-side: {adv['hit']*100:.1f}% hit, n={adv['n']}, {adv['days']}d\n"
                    f"formula short/avoid: {fml['hit']*100:.1f}% hit, n={fml['n']}, {fml['days']}d\n"
                    "Adviser conviction now bounded-nudges position sizing "
                    "(brain/adviser_gate.py apply_adviser_gate, weight "
                    f"{result['threshold']}).")
            else:
                notifier.send("🔒 *Adviser sizing gate: back to NOT eligible* "
                              "(one of the four thresholds slipped below bar).")
        except Exception as exc:
            print(f"(notify failed: {exc})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
