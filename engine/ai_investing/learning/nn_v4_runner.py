#!/usr/bin/env python3
"""Train the isolated NNv4 challenger on the ThinkStation GPU."""
import json, os
from datetime import datetime, timezone

from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.models import Asset, AssetClass
from ai_investing.backtest.engine import Backtester
from ai_investing.learning.nn_v4 import build_nn4_samples, fit_nn4


def main():
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    provider = get_provider(settings); bars = {}
    for asset in assets:
        try:
            data = provider.get_bars(asset, limit=2000)
            if len(data) >= 1000: bars[asset.key] = data
        except Exception as exc:
            print(f"NNv4 data failure {asset.key}: {exc}", flush=True)
    assets = [a for a in assets if a.key in bars]
    bt = Backtester(starting_cash=settings.starting_cash, horizon=settings.learning.horizon)
    X, yr, yp, yk, t = build_nn4_samples(bt, assets, bars)
    print(f"NNv4 assets={len(assets)} samples={len(X)} dates={len(set(t))}", flush=True)
    model, reason = fit_nn4(X, yr, yp, yk, min_samples=2000, t_index=t, purge=bt.horizon,
                            device=os.environ.get("NN4_DEVICE", "auto"))
    if model is None:
        print("NNv4: " + reason, flush=True); return 0
    out = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "nn_v4")
    os.makedirs(out, exist_ok=True); path = os.path.join(out, "formula.json")
    candidate = path + ".candidate"
    with open(candidate, "w") as handle:
        json.dump({"model_type": "nn4", "model": model.to_dict(),
                   "updated": datetime.now(timezone.utc).isoformat(),
                   "assets": len(assets), "samples": len(X), "dates": len(set(t))}, handle, indent=2)
    prior = None
    try:
        with open(path) as handle: prior = json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass
    old_loss = ((prior or {}).get("model") or {}).get("val_loss")
    if old_loss is None or float(model.val_loss) < float(old_loss):
        os.replace(candidate, path)
        print(f"NNv4: promoted {path} params={model.n_params} val_loss={model.val_loss}", flush=True)
    else:
        os.unlink(candidate)
        print(f"NNv4: rejected candidate val_loss={model.val_loss} >= incumbent={old_loss}", flush=True)
    return 0


if __name__ == "__main__": raise SystemExit(main())
