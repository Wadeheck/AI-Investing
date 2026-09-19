#!/usr/bin/env python3
"""Train the isolated NNv5 residual challenger on the training host."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from datetime import datetime as dt

from ai_investing.backtest.engine import Backtester
from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.nn_v5 import build_nn5_samples, fit_nn5
from ai_investing.models import Asset, AssetClass, Bar
from ai_investing.learning import ParamStore


def main() -> int:
    cache_path = os.environ.get("NN5_BARS_CACHE")
    if cache_path:
        payload = json.load(open(cache_path))
        assets, bars = [], {}
        for key, entry in (payload.get("symbols") or {}).items():
            symbol = key.split(":", 1)[-1]
            rows = []
            for row in entry.get("bars", []):
                try:
                    rows.append(Bar(dt.fromisoformat(row[0]), *map(float, row[1:6])))
                except (TypeError, ValueError):
                    continue
            if len(rows) >= 100:
                asset = Asset(symbol, AssetClass.STOCK); assets.append(asset); bars[asset.key] = rows
        print(f"NNv5 cache={cache_path} symbols={len(assets)}", flush=True)
    else:
        assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
                  + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                     for s in settings.crypto_watchlist])
        provider = get_provider(settings); bars = {}
        for asset in assets:
            try:
                data = provider.get_bars(asset, limit=4000)
                if len(data) >= 1000: bars[asset.key] = data
            except Exception as exc:
                print(f"NNv5 data failure {asset.key}: {exc}", flush=True)
        assets = [a for a in assets if a.key in bars]
    baseline, _ = ParamStore(settings.params_path).load()
    if not isinstance(baseline, FormulaModel):
        print("NNv5: incumbent is not the linear brain; refusing residual fit", flush=True)
        return 0
    bt = Backtester(starting_cash=settings.starting_cash, horizon=settings.learning.horizon)
    X, y, t = build_nn5_samples(bt, assets, bars, baseline)
    print(f"NNv5 assets={len(assets)} samples={len(X)} dates={len(set(t))}", flush=True)
    model, reason = fit_nn5(
        X, y, baseline, min_samples=int(os.environ.get("NN5_MIN_SAMPLES", "3000")),
        hidden=int(os.environ.get("NN5_HIDDEN", "16")), t_index=t, purge=bt.horizon,
        device=os.environ.get("NN5_DEVICE", "auto"))
    if model is None:
        print("NNv5: " + reason, flush=True); return 0
    out = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "nn_v5")
    os.makedirs(out, exist_ok=True); path = os.path.join(out, "formula.json")
    candidate = path + ".candidate"
    payload = {"model_type": "nn5", "model": model.to_dict(),
               "updated": datetime.now(timezone.utc).isoformat(),
               "assets": len(assets), "samples": len(X), "dates": len(set(t)),
               "training_device": os.environ.get("NN5_DEVICE", "auto"),
               "data_source": cache_path or settings.data_provider}
    with open(candidate, "w") as handle: json.dump(payload, handle, indent=2)
    prior = None
    try:
        with open(path) as handle: prior = json.load(handle)
    except (OSError, json.JSONDecodeError): pass
    old_loss = ((prior or {}).get("model") or {}).get("val_loss")
    if old_loss is None or float(model.val_loss) < float(old_loss):
        os.replace(candidate, path)
        print(f"NNv5: promoted residual artifact val_loss={model.val_loss}", flush=True)
    else:
        os.unlink(candidate)
        print(f"NNv5: rejected candidate val_loss={model.val_loss} >= incumbent={old_loss}", flush=True)
    return 0


if __name__ == "__main__": raise SystemExit(main())
