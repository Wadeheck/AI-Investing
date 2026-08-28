"""NNv4 research challenger: calibrated ranking, not unconstrained position sizing.

NNv4 is deliberately isolated from the live formula and NNv3.  It consumes a
point-in-time feature vector and predicts three related quantities:

* forward excess return;
* probability that excess return is positive; and
* expected adverse movement (risk).

The portfolio score is ``return * probability / risk``.  Position sizing remains
outside the network and is bounded by ``target_weight``.  Training uses a small
shared MLP and a CUDA-capable PyTorch backend when available, while persistence
uses ordinary JSON lists so inference does not require PyTorch.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from ai_investing.indicators import pct_returns, stdev
from ai_investing.learning.features import FeatureExtractor


NN4_FEATURE_NAMES = [
    "bias", "momentum", "mean_reversion", "sentiment", "political_hype",
    "macro_linkage", "trend_zscore", "consensus", "mom_lowvol",
    "regime_persistence", "return_1d", "return_5d", "return_20d",
    "return_60d", "realized_vol", "vol_change", "drawdown_60d", "relative_strength",
]

DEFAULT_HIDDEN_1 = 12
DEFAULT_HIDDEN_2 = 6
DEFAULT_EPOCHS = 300
DEFAULT_MIN_SAMPLES = 2000


def build_nn4_features(asset, bars, signals, context=None):
    """Create the live feature vector using only bars available at decision time."""
    extractor = FeatureExtractor()
    results = [s.evaluate(asset, bars, context or {}) for s in signals]
    f = extractor.build(results, bars); closes = [b.close for b in bars]
    def ret(n):
        return closes[-1] / closes[-1 - n] - 1.0 if len(closes) > n and closes[-1 - n] else 0.0
    vol = stdev(pct_returns(closes[-21:])) if closes else 0.0
    high = max(closes[-60:]) if closes else 0.0
    f.update({"return_1d": ret(1), "return_5d": ret(5), "return_20d": ret(20),
              "return_60d": ret(60), "realized_vol": vol,
              "vol_change": stdev(pct_returns(closes[-11:])) - vol if len(closes) > 11 else 0.0,
              "drawdown_60d": closes[-1] / high - 1.0 if high else 0.0,
              "relative_strength": ret(20)})
    return f, results


def build_nn4_samples(backtester, assets, bars_by_key: dict):
    """Build point-in-time cross-sectional samples from the existing bar universe.

    Every feature uses bars through ``t`` only. The target is the asset's forward
    return relative to the cross-sectional median at ``t``; risk is the maximum
    adverse excursion over the same horizon. This keeps NNv4 focused on ranking
    assets rather than predicting the market's common direction.
    """
    aligned, length = backtester._aligned(bars_by_key)
    asset_by_key = {a.key: a for a in assets}; extractor = FeatureExtractor()
    rows = []; raw_targets = {}; horizon = backtester.horizon
    for key, bars in aligned.items():
        asset = asset_by_key.get(key)
        if asset is None: continue
        for t in range(backtester.warmup, length - horizon):
            results = [signal.evaluate(asset, bars[:t + 1], {}) for signal in backtester.signals]
            f = extractor.build(results, bars[:t + 1]); closes = [b.close for b in bars[:t + 1]]
            def ret(n):
                return closes[-1] / closes[-1 - n] - 1.0 if len(closes) > n and closes[-1 - n] else 0.0
            rets = pct_returns(closes[-21:]); vol = stdev(rets) * (horizon ** 0.5) if rets else 0.01
            high = max(closes[-60:]) if closes else closes[-1]
            f.update({"return_1d": ret(1), "return_5d": ret(5), "return_20d": ret(20),
                      "return_60d": ret(60), "realized_vol": vol,
                      "vol_change": (stdev(pct_returns(closes[-11:])) - vol) if len(closes) > 11 else 0.0,
                      "drawdown_60d": closes[-1] / high - 1.0 if high else 0.0,
                      "relative_strength": ret(20)})
            future = [b.close for b in bars[t:t + horizon + 1]]
            fr = future[-1] / future[0] - 1.0 if future and future[0] else 0.0
            mae = min((v / future[0] - 1.0 for v in future), default=0.0) if future and future[0] else 0.0
            vector = [f.get(name, 0.0) for name in NN4_FEATURE_NAMES]
            rows.append((vector, fr, max(0.0, -mae), t))
    by_time = {}
    for i, row in enumerate(rows): by_time.setdefault(row[3], []).append(i)
    X = [r[0] for r in rows]; returns = [r[1] for r in rows]; risks = [r[2] for r in rows]
    positive = [1.0 if r > 0 else 0.0 for r in returns]
    for ids in by_time.values():
        med = sorted(returns[i] for i in ids)[len(ids) // 2]
        for i in ids: returns[i] -= med
    return X, returns, positive, risks, [r[3] for r in rows]


@dataclass
class NN4FormulaModel:
    feature_names: list[str] = field(default_factory=lambda: list(NN4_FEATURE_NAMES))
    hidden_1: int = DEFAULT_HIDDEN_1
    hidden_2: int = DEFAULT_HIDDEN_2
    W1: list[list[float]] = field(default_factory=list)
    b1: list[float] = field(default_factory=list)
    W2: list[list[float]] = field(default_factory=list)
    b2: list[float] = field(default_factory=list)
    # Three output heads: excess return, positive-return logit, adverse risk.
    heads: list[list[float]] = field(default_factory=list)
    head_bias: list[float] = field(default_factory=list)
    feature_mean: Optional[list[float]] = None
    feature_std: Optional[list[float]] = None
    gain: float = 1.0
    entry_threshold: float = 0.10
    size_scale: float = 1.0
    version: int = 4
    fitted: bool = False
    val_loss: Optional[float] = None
    ood_z_limit: float = 4.0
    calibration_slope: float = 1.0
    calibration_intercept: float = 0.0

    def _x(self, feats: dict[str, float]) -> list[float]:
        x = [float(feats.get(n, 0.0) or 0.0) for n in self.feature_names]
        if self.feature_mean and self.feature_std:
            x = [(v - m) / s if s > 1e-9 else 0.0
                 for v, m, s in zip(x, self.feature_mean, self.feature_std)]
        return x

    @staticmethod
    def _tanh_layer(weights, biases, x):
        return [math.tanh(sum(w * v for w, v in zip(row, x)) + b)
                for row, b in zip(weights, biases)]

    def outputs(self, feats: dict[str, float]) -> dict[str, float]:
        if not self.W1 or len(self.heads) != 3:
            return {"expected_return": 0.0, "probability": 0.5, "risk": 1.0,
                    "ood_multiplier": 0.0, "ood_z": 0.0}
        xn = self._x(feats)
        h1 = self._tanh_layer(self.W1, self.b1, xn)
        h2 = self._tanh_layer(self.W2, self.b2, h1)
        raw = [sum(w * v for w, v in zip(row, h2)) + b
               for row, b in zip(self.heads, self.head_bias)]
        z = max((abs(v) for v in xn), default=0.0)
        # _x is already normalized when statistics exist; its largest absolute
        # value is therefore the OOD distance in standard-deviation units.
        ood = max(0.0, min(1.0, (self.ood_z_limit - z) / max(self.ood_z_limit, 1e-9)))
        logit = self.calibration_slope * raw[1] + self.calibration_intercept
        probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))
        return {"expected_return": raw[0], "probability": probability,
                "risk": max(1e-4, abs(raw[2])), "ood_multiplier": ood, "ood_z": z}

    def score(self, feats: dict[str, float]) -> float:
        out = self.outputs(feats)
        return out["expected_return"] * out["probability"] / out["risk"] * out["ood_multiplier"]

    def target_weight(self, feats: dict[str, float]) -> float:
        conviction = math.tanh(self.gain * self.score(feats))
        if abs(conviction) <= self.entry_threshold:
            return 0.0
        sign = 1.0 if conviction >= 0 else -1.0
        magnitude = (abs(conviction) - self.entry_threshold) / (1.0 - self.entry_threshold)
        return max(-1.0, min(1.0, sign * magnitude * self.size_scale))

    def raw(self, feats: dict[str, float]) -> float:
        return self.outputs(feats)["expected_return"]

    def conviction(self, feats: dict[str, float]) -> float:
        return math.tanh(self.gain * self.score(feats))

    def weight_of(self, name: str) -> float:
        return 0.0  # nonlinear model; attribution is intentionally not fabricated

    @property
    def n_params(self) -> int:
        return (sum(map(len, self.W1)) + len(self.b1) + sum(map(len, self.W2)) + len(self.b2)
                + sum(map(len, self.heads)) + len(self.head_bias))

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "feature_names", "hidden_1", "hidden_2", "W1", "b1", "W2", "b2",
            "heads", "head_bias", "feature_mean", "feature_std", "gain",
            "entry_threshold", "size_scale", "version", "fitted", "val_loss",
            "ood_z_limit", "calibration_slope", "calibration_intercept")}

    @classmethod
    def from_dict(cls, data: dict) -> "NN4FormulaModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _normalise(X):
    n, d = len(X), len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    std = [(sum((row[j] - mean[j]) ** 2 for row in X) / max(1, n - 1)) ** 0.5
           for j in range(d)]
    return [[(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(row, mean, std)
             ] for row in X], mean, std


def _platt_calibration(logits, labels):
    """Fit a tiny regularized logistic calibration on held-out logits."""
    a, b = 1.0, 0.0
    for _ in range(25):
        g1 = g2 = h11 = h12 = h22 = 0.0
        for x, y in zip(logits, labels):
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, a * x + b))))
            w = max(1e-6, p * (1.0 - p)); e = p - y
            g1 += e * x; g2 += e; h11 += w * x * x; h12 += w * x; h22 += w
        det = h11 * h22 - h12 * h12
        if det <= 1e-9: break
        da = (h22 * g1 - h12 * g2) / det; db = (-h12 * g1 + h11 * g2) / det
        a = max(0.05, min(5.0, a - da)); b = max(-5.0, min(5.0, b - db))
    return a, b


def fit_nn4(X: list[list[float]], y_return: list[float], y_positive: list[float],
            y_risk: list[float], *, epochs: int = DEFAULT_EPOCHS,
            min_samples: int = DEFAULT_MIN_SAMPLES, seed: int = 7,
            t_index: Optional[list[int]] = None, purge: int = 5,
            device: Optional[str] = None) -> tuple[Optional[NN4FormulaModel], str]:
    """Fit NNv4 with a purged time split and optional CUDA device."""
    if not X or len(X) < min_samples or not (len(X) == len(y_return) == len(y_positive) == len(y_risk)):
        return None, "insufficient data for NN4 challenger"
    if t_index is None or len(t_index) != len(X):
        cut = int(len(X) * 0.8)
        tr, va = list(range(max(1, cut - purge))), list(range(cut, len(X)))
    else:
        times = sorted(set(t_index)); cut = times[max(0, int(len(times) * 0.8) - 1)]
        tr = [i for i, t in enumerate(t_index) if t <= cut - purge]
        va = [i for i, t in enumerate(t_index) if t > cut]
    if len(tr) < 20 or len(va) < 20:
        return None, "insufficient data for NN4 challenger"
    Xn, mean, std = _normalise([X[i] for i in tr])
    Xv = [[(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(X[i], mean, std)] for i in va]
    try:
        import torch
        import torch.nn as nn
        torch.manual_seed(seed)
        selected = device or os.environ.get("NN4_DEVICE", "auto")
        if selected == "auto": selected = "cuda" if torch.cuda.is_available() else "cpu"
        dev = torch.device(selected)
        net = nn.Sequential(nn.Linear(len(Xn[0]), 12), nn.Tanh(), nn.Linear(12, 6), nn.Tanh(), nn.Linear(6, 3)).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=0.01, weight_decay=1e-3)
        tx = torch.tensor(Xn, dtype=torch.float32, device=dev); vx = torch.tensor(Xv, dtype=torch.float32, device=dev)
        yr = torch.tensor([y_return[i] for i in tr], dtype=torch.float32, device=dev)
        yp = torch.tensor([y_positive[i] for i in tr], dtype=torch.float32, device=dev)
        yk = torch.tensor([max(1e-4, y_risk[i]) for i in tr], dtype=torch.float32, device=dev)
        vr = torch.tensor([y_return[i] for i in va], dtype=torch.float32, device=dev)
        vp = torch.tensor([y_positive[i] for i in va], dtype=torch.float32, device=dev)
        vk = torch.tensor([max(1e-4, y_risk[i]) for i in va], dtype=torch.float32, device=dev)
        best, state, bad = float("inf"), None, 0
        for _ in range(epochs):
            opt.zero_grad(set_to_none=True); out = net(tx)
            loss = nn.functional.huber_loss(out[:, 0], yr) + nn.functional.binary_cross_entropy_with_logits(out[:, 1], yp) + nn.functional.huber_loss(out[:, 2].abs(), yk)
            if not torch.isfinite(loss): break
            loss.backward(); opt.step()
            with torch.no_grad():
                vo = net(vx); vl = float((nn.functional.huber_loss(vo[:, 0], vr) + nn.functional.binary_cross_entropy_with_logits(vo[:, 1], vp) + nn.functional.huber_loss(vo[:, 2].abs(), vk)).cpu())
            if vl < best - 1e-7:
                best, bad, state = vl, 0, {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= 25: break
        if state is None: return None, "NN4 training did not converge"
        net.load_state_dict(state); a, b, c = net[0], net[2], net[4]
        pred = net(tx).detach().cpu()[:, 0].tolist(); sd = (sum((v - sum(pred)/len(pred))**2 for v in pred) / max(1, len(pred)-1)) ** 0.5
        val_logits = net(vx).detach().cpu()[:, 1].tolist()
        cal_a, cal_b = _platt_calibration(val_logits, [y_positive[i] for i in va])
        model = NN4FormulaModel(W1=a.weight.tolist(), b1=a.bias.tolist(), W2=b.weight.tolist(), b2=b.bias.tolist(), heads=c.weight.tolist(), head_bias=c.bias.tolist(), feature_mean=mean, feature_std=std, gain=1.0/max(sd, 1e-3), calibration_slope=cal_a, calibration_intercept=cal_b, fitted=True, val_loss=best)
        return model, ""
    except (ImportError, RuntimeError, ValueError) as exc:
        return None, f"NN4 training backend failed: {exc}"
