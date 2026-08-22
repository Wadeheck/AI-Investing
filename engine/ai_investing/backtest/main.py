"""Backtest + walk-forward CLI.

    cd engine
    python3 -m ai_investing.backtest.main --optimize          # curate θ (walk-forward)
    python3 -m ai_investing.backtest.main --optimize --save   # ...and persist the winner
    python3 -m ai_investing.backtest.main --run               # backtest the saved formula
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from ai_investing.backtest.engine import Backtester
from ai_investing.backtest.walkforward import WalkForwardOptimizer
from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.execution.costs import CostModel
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.store import ParamStore
from ai_investing.models import Asset, AssetClass


def _load_data(limit: int = 400):
    provider = get_provider(settings)
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    bars_by_key = {a.key: provider.get_bars(a, limit=limit) for a in assets}
    bars_by_key = {k: v for k, v in bars_by_key.items() if v}
    assets = [a for a in assets if a.key in bars_by_key]
    return assets, bars_by_key


def _print_metrics(label: str, m: dict) -> None:
    print(f"  {label:<12} Sharpe {m['sharpe']:>6}  return {m['total_return'] * 100:>7.1f}%  "
          f"maxDD {m['max_drawdown'] * 100:>5.1f}%  trades {m['n_trades']:>3}  "
          f"final ${m['final_equity']:,.0f}")


def _dump(assets, chosen, default_res, chosen_res, result=None) -> None:
    """Write data/backtest.json so the dashboard has a chart + formula immediately."""
    path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "backtest.json")
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "provider": settings.data_provider,
        "assets": [a.symbol for a in assets],
        "adopted": (result or {}).get("adopted"),
        "dsr": (result or {}).get("dsr"),
        "n_trials": (result or {}).get("n_trials"),
        "challenger_avg": (result or {}).get("challenger_avg"),
        "default_avg": (result or {}).get("default_avg"),
        "windows": (result or {}).get("windows", []),
        "metrics_default": default_res.metrics,
        "metrics_chosen": chosen_res.metrics,
        "equity_curve_default": [round(x, 2) for x in default_res.equity_curve],
        "equity_curve_chosen": [round(x, 2) for x in chosen_res.equity_curve],
        "model_type": (result or {}).get("model_type", "linear"),
        "formula": {
            "version": chosen.version, "fitted": chosen.fitted,
            # An MLP has no per-feature weight; the dashboard gets an empty dict rather
            # than a fabricated attribution (see NNFormulaModel.weight_of).
            "weights": dict(zip(chosen.feature_names, chosen.weights))
                       if hasattr(chosen, "weights") else {},
            "gain": chosen.gain, "entry_threshold": chosen.entry_threshold,
            "size_scale": chosen.size_scale, "stop_loss": chosen.stop_loss,
            "take_profit": chosen.take_profit,
        },
    }
    if result and "nn_dsr" in result:
        # Both candidates, win or lose -- scripts/nn_challenger_report.py reads this.
        payload["nn_challenger"] = {
            k[3:] if k.startswith("nn_") else k: result[k]
            for k in ("nn_challenger_avg", "nn_dsr", "nn_n_trials", "nn_windows",
                      "nn_reason", "nn_train_samples", "nn_n_params", "nn_windows_fit",
                      "nn_min_dsr", "nn_adoption_margin", "nn_ok", "linear_ok",
                      "adoption_case")
        }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"  wrote {path}")


def _save_nn_shadow(settings, result) -> None:
    """Persist the fitted net so the shadow book has something to trade.

    THIS IS NOT ADOPTION and must never become it. The deflated-Sharpe gate
    decides what the engine trades; this decides only what the SHADOW trades,
    and the shadow cannot place a real order. A net the gate refused is exactly
    the one worth watching — refusing to record it is how you never find out
    whether the refusal was right.

    THE GUARD IS STRUCTURAL. The write is refused unless the destination sits
    inside a directory named `nn_shadow`. Redirecting PARAMS_PATH in the systemd
    unit is a convention and conventions get edited; this is a rule the code
    enforces, so a mis-set env var cannot put an unadopted net where the live
    engine loads its formula.
    """
    from pathlib import Path as _P
    model = (result or {}).get("nn_model")
    if model is None:
        print("\n  [nn-shadow] no net was fitted this run — nothing to save.")
        return
    dest = _P(settings.params_path).resolve()
    if "nn_shadow" not in dest.parts:
        print(f"\n  !! REFUSED to write an unadopted net to {dest}\n"
              f"     --save-nn-shadow only writes inside an nn_shadow directory.\n"
              f"     Set PARAMS_PATH to .../data/nn_shadow/formula.json.")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    ParamStore(str(dest)).save(model)
    print(f"\n  [nn-shadow] fitted net saved -> {dest}\n"
          f"     NOT adopted; the live formula is untouched. The shadow book "
          f"will trade this net and journal every call.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest and walk-forward optimize the formula.")
    parser.add_argument("--optimize", action="store_true", help="run walk-forward curation (default)")
    parser.add_argument("--run", action="store_true", help="just backtest the saved/default formula")
    parser.add_argument("--save", action="store_true", help="persist the matured formula")
    parser.add_argument("--save-nn-shadow", action="store_true",
                        help="persist the FITTED NN (win or lose) for the shadow "
                             "book to trade. Refuses any path outside an "
                             "nn_shadow directory. Never adopts.")
    args = parser.parse_args()

    assets, bars_by_key = _load_data()
    if not assets:
        print("No data for any watchlist asset (check DATA_PROVIDER / connectivity).")
        return
    print(f"Data: {settings.data_provider} | assets: {', '.join(a.symbol for a in assets)} "
          f"| bars: {min(len(v) for v in bars_by_key.values())}")

    costs = CostModel(enabled=settings.cost.enabled, commission_bps=settings.cost.commission_bps,
                      spread_bps=settings.cost.spread_bps, slippage_coef=settings.cost.slippage_coef)
    bt = Backtester(starting_cash=settings.starting_cash, horizon=settings.learning.horizon, cost_model=costs)
    print(f"costs: {'ON' if costs.enabled else 'OFF'} "
          f"(commission {costs.commission_bps}bps + spread {costs.spread_bps}bps + sqrt-impact)")

    if args.run:
        model = ParamStore(settings.params_path).load_model()
        print("\nBacktesting saved formula:")
        print(model.describe())
        res = bt.run(model, assets, bars_by_key)
        _print_metrics("result", res.metrics)
        _dump(assets, model, res, res)
        return

    print("\nWalk-forward optimization (train -> validate out-of-sample -> champion/challenger)")
    opt = WalkForwardOptimizer(bt, n_windows=settings.learning.walkforward_windows,
                               search=settings.learning.walkforward_search, embargo=settings.learning.embargo)
    lc = settings.learning
    result = opt.optimize(assets, bars_by_key, prior_model=FormulaModel(), min_dsr=lc.min_dsr,
                          try_nn=lc.nn_challenger_enabled, nn_min_dsr=lc.nn_min_dsr,
                          nn_adoption_margin=lc.nn_adoption_margin, nn_hidden=lc.nn_hidden,
                          nn_min_samples=lc.nn_min_samples)

    for w in result["windows"]:
        print(f"  window {w['window']}: default Sharpe {w['default_sharpe']:>6}  "
              f"challenger {w['challenger_sharpe']:>6}  (val bars {w['train_end']}..{w['val_end']})")
    print(f"\n  challenger avg Sharpe {result['challenger_avg']}  vs default {result['default_avg']}")
    print(f"  Deflated Sharpe {result['dsr']} over {result['n_trials']} trials "
          f"(need >= {result.get('min_dsr', 0.6)}) "
          f"-> {'ADOPT new formula' if result['adopted'] else 'KEEP incumbent (not significant)'}")

    if "nn_dsr" in result:
        # Both candidates, side by side -- never just the winner (see brain_audit.py:
        # "A track record that reports only its winners is a brochure").
        print(f"\n  NN challenger: fit in {result['nn_windows_fit']}/{len(result['nn_windows'])} "
              f"windows, {result['nn_train_samples']} training rows for "
              f"{result['nn_n_params']} parameters"
              f"{'  [' + result['nn_reason'] + ']' if result['nn_reason'] else ''}")
        for w in result["nn_windows"]:
            print(f"    window {w['window']}: default Sharpe {w['default_sharpe']:>6}  "
                  f"NN {str(w['nn_sharpe']):>6}  ({w['train_samples']} train rows)")
        print(f"    NN avg Sharpe {result['nn_challenger_avg']} vs linear "
              f"{result['challenger_avg']}  |  NN DSR {result['nn_dsr']} over "
              f"{result['nn_n_trials']} trials (need >= {result['nn_min_dsr']})")
        print(f"    adoption -> {result['adoption_case']}")

    chosen = result["model"]
    print("\nChosen formula:")
    print(chosen.describe())

    default_res = bt.run(FormulaModel(), assets, bars_by_key)
    chosen_res = bt.run(chosen, assets, bars_by_key)
    print("\nFull-period backtest comparison:")
    _print_metrics("default", default_res.metrics)
    _print_metrics("chosen", chosen_res.metrics)
    _dump(assets, chosen, default_res, chosen_res, result)

    if args.save:
        ParamStore(settings.params_path).save(chosen, metrics=chosen_res.metrics)
        print(f"\nSaved matured formula -> {settings.params_path} (version {chosen.version})")

    if args.save_nn_shadow:
        _save_nn_shadow(settings, result)


if __name__ == "__main__":
    main()
