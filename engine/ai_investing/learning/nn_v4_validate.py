"""Historical walk-forward validation report for NNv4; never writes live state."""
import json, math, os
from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.models import Asset, AssetClass
from ai_investing.backtest.engine import Backtester
from ai_investing.learning.nn_v4 import NN4FormulaModel, build_nn4_samples, fit_nn4


def corr(a, b):
    if len(a) < 2: return 0.0
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    da = sum((x-ma)**2 for x in a); db = sum((x-mb)**2 for x in b)
    return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / math.sqrt(max(1e-12, da*db))


def main():
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    provider = get_provider(settings); bars = {}
    for a in assets:
        try:
            data = provider.get_bars(a, limit=2000)
            if len(data) >= 1000: bars[a.key] = data
        except Exception: pass
    assets = [a for a in assets if a.key in bars]
    bt = Backtester(starting_cash=settings.starting_cash, horizon=settings.learning.horizon)
    X, yr, yp, yk, ti = build_nn4_samples(bt, assets, bars)
    dates = sorted(set(ti)); folds = []; n = len(dates)
    for cut in (int(n*.55), int(n*.70), int(n*.85)):
        train_dates, test_dates = set(dates[:cut]), set(dates[cut:min(n, cut + max(20, n//10))])
        tr = [i for i,t in enumerate(ti) if t in train_dates]
        te = [i for i,t in enumerate(ti) if t in test_dates]
        model, reason = fit_nn4([X[i] for i in tr], [yr[i] for i in tr], [yp[i] for i in tr], [yk[i] for i in tr], min_samples=2000, t_index=[ti[i] for i in tr], purge=bt.horizon)
        if model is None: folds.append({"train":len(tr),"test":len(te),"reason":reason}); continue
        pred = [model.score({name: value for name,value in zip(model.feature_names, X[i])}) for i in te]
        momentum = [X[i][model.feature_names.index("return_20d")] for i in te]
        wins = sum(1 for p,y in zip(pred,[yr[i] for i in te]) if p*y > 0)
        folds.append({"train":len(tr),"test":len(te),"corr":round(corr(pred,[yr[i] for i in te]),4),"direction_hit_rate":round(wins/max(1,len(te)),4),"momentum_corr":round(corr(momentum,[yr[i] for i in te]),4),"ood_mean":round(sum(model.outputs({name:value for name,value in zip(model.feature_names,X[i])})["ood_multiplier"] for i in te)/max(1,len(te)),4)})
    out = {"updated":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),"assets":len(assets),"samples":len(X),"dates":len(dates),"folds":folds}
    path=os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),"nn_v4","validation.json"); os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w") as f: json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
