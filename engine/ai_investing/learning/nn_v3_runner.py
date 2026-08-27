#!/usr/bin/env python3
"""Train and persist the isolated NNv3 challenger."""
import json, os
import sys
from datetime import datetime, timezone
from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.models import Asset, AssetClass
from ai_investing.backtest.engine import Backtester
from ai_investing.backtest.walkforward import WalkForwardOptimizer
from ai_investing.learning.formula import FormulaModel

def main():
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    provider = get_provider(settings)
    
    # Fetch data with fallback for large requests - try with smaller limits first
    bars = {}
    for a in assets:
        # Try with a smaller limit first to avoid hitting provider limitations
        try:
            # Start with a reasonable limit that works for most assets
            limit = 2000
            bars[a.key] = provider.get_bars(a, limit=limit)
            
            # If we got less than 100 bars, it might be a data issue
            if len(bars[a.key]) < 100:
                # Try with an even smaller limit as a fallback
                bars[a.key] = provider.get_bars(a, limit=1000)
                
            # If still insufficient, try with 500 bars
            if len(bars[a.key]) < 500:
                bars[a.key] = provider.get_bars(a, limit=500)
                
        except Exception as e:
            print(f"Failed to fetch bars for {a.key}: {e}", file=sys.stderr, flush=True)
            bars[a.key] = []
    
    # Filter assets to only include those with sufficient history (at least 2000 bars or reasonable fallback)
    MIN_HISTORY = 1000  # Reduced minimum to account for data provider limitations
    bars = {k: v for k, v in bars.items() if len(v) >= MIN_HISTORY}
    assets = [a for a in assets if a.key in bars]
    
    # Compute aligned data to get exact sample count and shortest history
    bt = Backtester(starting_cash=settings.starting_cash, horizon=settings.learning.horizon)
    aligned, length = bt._aligned(bars)
    
    # Print diagnostics before fitting with unbuffered output
    print("assets:", len(assets), file=sys.stdout, flush=True)
    print("shortest bars:", min(len(v) for v in bars.values()) if bars else 0, file=sys.stdout, flush=True)
    print("aligned length:", length, file=sys.stdout, flush=True)
    
    # Calculate actual NN3 samples using the same aligned dataset as WalkForwardOptimizer
    if length > 0:
        # Use the actual backtester values for warmup and horizon
        warmup = bt.warmup
        horizon = bt.horizon
        
        # The actual samples are (length - warmup - horizon) for each asset
        # But we want to ensure we have at least 3 assets per timestamp
        min_assets_per_timestamp = 3
        min_samples = 1000
        
        # Count how many timestamps we have with at least 3 assets
        timestamps_with_enough_assets = 0
        timestamp_asset_counts = {}
        
        # Count assets per timestamp to determine minimum samples
        for key, bars_list in aligned.items():
            for t in range(warmup, length - horizon):
                timestamp_asset_counts[t] = timestamp_asset_counts.get(t, 0) + 1
        
        # Count timestamps with at least 3 assets
        timestamps_with_enough_assets = sum(1 for count in timestamp_asset_counts.values() if count >= min_assets_per_timestamp)
        
        # Calculate the total number of valid samples
        actual_samples = sum(count for count in timestamp_asset_counts.values() if count >= min_assets_per_timestamp)
        print("estimated NN3 samples:", actual_samples, file=sys.stdout, flush=True)
        
        # Check if we have enough samples and assets
        if actual_samples < min_samples:
            print(f"NNv3: insufficient samples ({actual_samples} < {min_samples})", file=sys.stdout, flush=True)
            return 0
        
        # Also check that we have at least 3 assets per timestamp for valid samples
        if timestamps_with_enough_assets == 0:
            print("NNv3: no timestamps with sufficient assets (minimum 3 per timestamp)", file=sys.stdout, flush=True)
            return 0
    else:
        print("NNv3: no aligned data", file=sys.stdout, flush=True)
        return 0
    
    if not assets:
        print("NNv3: no market data", file=sys.stdout, flush=True)
        return 0
    
    lc = settings.learning
    opt = WalkForwardOptimizer(bt, n_windows=lc.walkforward_windows,
                               search=lc.walkforward_search, embargo=lc.embargo)
    result = opt.optimize(assets, bars, prior_model=FormulaModel(),
                          min_dsr=lc.min_dsr, try_nn3=True,
                          nn3_min_samples=getattr(lc, "nn3_min_samples", 1000))
    model = result.get("nn3_model")
    out = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "nn_v3")
    os.makedirs(out, exist_ok=True)
    if model is None:
        print("NNv3: no model fitted: " + str(result.get("nn3_reason", "insufficient data")), file=sys.stdout, flush=True)
        return 0
    path = os.path.join(out, "formula.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"model_type":"nn3", "model":model.to_dict(),
                   "updated":datetime.now(timezone.utc).isoformat(),
                   "nn3_dsr":result.get("nn3_dsr"),
                   "nn3_windows_fit":result.get("nn3_windows_fit")}, f, indent=2)
    os.replace(tmp, path)
    print("NNv3: saved isolated model to " + path, file=sys.stdout, flush=True)
    return 0
if __name__ == "__main__": raise SystemExit(main())
