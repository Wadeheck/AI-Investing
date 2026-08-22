#!/usr/bin/env python3
"""What the NN challenger actually did, both candidates, win or lose.

    python3 scripts/nn_challenger_report.py [--json]

Reads data/backtest.json (written by `python3 -m ai_investing.backtest.main --optimize`)
and data/formula.json. Prints the linear and NN candidates SIDE BY SIDE — never just
the winner. A report that shows only its winner is a brochure (brain_audit.py's own
"HOW TO READ THIS" makes the same point about symbol tracking), and here it would hide
the single number that decides whether any of this is trustworthy: how many training
rows there were per free parameter.

See docs/design/NN_CHALLENGER.md §2.8. "insufficient data" and "did not clear the bar"
are successful outcomes for this phase, not failures — they mean the gate is working.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

from ai_investing.config import settings   # noqa: E402


def _data_dir() -> str:
    return os.path.dirname(os.path.abspath(settings.state_path))


def _read(name: str) -> dict:
    try:
        with open(os.path.join(_data_dir(), name)) as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_path(path: str) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def collect() -> dict:
    bt = _read("backtest.json")
    # settings.params_path, NOT data_dir/formula.json: the shadow curation job
    # redirects PARAMS_PATH so it cannot touch the live formula, and building the
    # path by hand made this read the (absent) shadow file and report it as the
    # live model at "version None". Name the file it actually read so which
    # formula this describes is never a guess.
    formula = _read_path(settings.params_path)
    nn = bt.get("nn_challenger") or {}
    out = {
        "backtest_updated": bt.get("updated"),
        "model_path": settings.params_path,
        "model_present": bool(formula),
        "live_model_type": formula.get("model_type", "linear") if formula else None,
        "live_model_version": (formula.get("model") or {}).get("version"),
        "adopted_model_type": bt.get("model_type"),
        "nn_attempted": bool(nn),
    }
    if not nn:
        return out

    n_params = nn.get("n_params") or 0
    rows = nn.get("train_samples") or 0
    out.update({
        "n_params": n_params,
        "n_training_samples": rows,
        # The ratio §2.3's minimum-sample rule exists to protect: this codebase's rule
        # of thumb is at least 10 rows per free parameter. Below that a fit memorizes,
        # and a memorized net that clears a Sharpe gate by luck is the exact failure
        # this whole challenger apparatus exists to prevent.
        "samples_per_param": round(rows / n_params, 1) if n_params else None,
        "meets_10x_rule": bool(n_params and rows >= 10 * n_params),
        "windows_fit": nn.get("windows_fit"),
        "reason": nn.get("reason") or "",
        "linear": {"avg_sharpe": bt.get("challenger_avg"), "dsr": bt.get("dsr"),
                   "n_trials": bt.get("n_trials"), "cleared_bar": nn.get("linear_ok")},
        "nn": {"avg_sharpe": nn.get("challenger_avg"), "dsr": nn.get("dsr"),
               "n_trials": nn.get("n_trials"), "min_dsr": nn.get("min_dsr"),
               "cleared_bar": nn.get("ok")},
        "adoption_margin": nn.get("adoption_margin"),
        "adoption_case": nn.get("adoption_case"),
        "per_window": [
            {"window": w.get("window"), "train_samples": w.get("train_samples"),
             "default_sharpe": w.get("default_sharpe"), "nn_sharpe": w.get("nn_sharpe"),
             "linear_sharpe": (bt.get("windows") or [{}] * 99)[w.get("window", 0)].get("challenger_sharpe")
             if w.get("window", 0) < len(bt.get("windows") or []) else None}
            for w in (nn.get("windows") or [])
        ],
    })
    return out


def render(r: dict) -> str:
    L = [f"NN CHALLENGER REPORT  (backtest written {r.get('backtest_updated') or 'never'})", ""]
    if r["model_present"]:
        L.append(f"  model at {r['model_path']}")
        L.append(f"    -> {r['live_model_type']} (version {r['live_model_version']})")
    else:
        L.append(f"  no model file at {r['model_path']}")
        L.append("    -> nothing has been adopted at this path (expected for the "
                 "shadow job,")
        L.append("       which redirects PARAMS_PATH precisely so it cannot adopt "
                 "anything)")
    if not r["nn_attempted"]:
        L += ["", "  The NN challenger has not been run.",
              "  Enable it with LEARN_NN_ENABLED=true and re-run:",
              "      python3 -m ai_investing.backtest.main --optimize", ""]
        return "\n".join(L)

    L += ["",
          f"  capacity vs evidence : {r['n_params']} free parameters, "
          f"{r['n_training_samples']} training rows "
          f"({r['samples_per_param']} rows/param)"]
    L.append(f"                         10-rows-per-parameter rule: "
             f"{'met on row count' if r['meets_10x_rule'] else 'NOT MET -- any fit here is suspect'}")
    # Stated every time, pass or fail. A row is one (symbol, day); twenty symbols on the
    # same day are one market moving, not twenty independent draws, so this count is an
    # UPPER bound on the evidence and the rule clearing it is necessary, not sufficient.
    # This is the same overcounting docs/status/BRAIN_REVIEW_2026-08-21.md found (65x),
    # pointed at the NN's own guard rather than at the track record.
    L.append("                         caveat: rows are (symbol, day) pairs, NOT")
    L.append("                         independent observations -- cross-sectionally")
    L.append("                         correlated, so this is an UPPER bound on evidence.")
    if r["reason"]:
        L.append(f"  refusal              : {r['reason']} "
                 f"(fit in {r['windows_fit']} window(s))")

    L += ["", "  per window (both candidates, win or lose):",
          "    win   train_rows   default    linear     NN"]
    for w in r["per_window"]:
        L.append(f"    {str(w['window']):<5} {str(w['train_samples']):>10}   "
                 f"{str(w['default_sharpe']):>7}  {str(w['linear_sharpe']):>8}  "
                 f"{str(w['nn_sharpe']):>6}")

    lin, nn = r["linear"], r["nn"]
    L += ["", "  gate:",
          f"    linear : avg Sharpe {lin['avg_sharpe']}  DSR {lin['dsr']} over "
          f"{lin['n_trials']} trials  -> cleared={lin['cleared_bar']}",
          f"    NN     : avg Sharpe {nn['avg_sharpe']}  DSR {nn['dsr']} over "
          f"{nn['n_trials']} trials (need >= {nn['min_dsr']})  -> cleared={nn['cleared_bar']}",
          f"    margin the NN must beat linear by: {r['adoption_margin']}",
          "", f"  outcome: {r['adoption_case']}",
          f"           adopted model type = {r['adopted_model_type']}", ""]
    if not nn["cleared_bar"]:
        L += ["  Note: the NN not clearing its bar is a SUCCESSFUL outcome for this phase.",
              "  It means the deflated-Sharpe gate refused a 49-parameter model that the",
              "  available evidence cannot support. More data (Track A) is the fix; a",
              "  bigger network is not.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    # argv is a parameter, not sys.argv, so a test can drive this (see
    # tests/test_data_path_isolation.py: a main() reading global state its caller
    # cannot set is neither testable nor configurable).
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="emit the raw dict")
    args = ap.parse_args(argv)
    r = collect()
    print(json.dumps(r, indent=2) if args.json else render(r))


if __name__ == "__main__":
    main(sys.argv[1:])
