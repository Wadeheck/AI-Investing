"""NNv5 residual challenger.

NNv5 is deliberately not a replacement formula.  It learns the part of the
forward return left unexplained by the linear brain and adds that residual to
the brain's prediction.  This makes the research question precise:
"does the nonlinear model add value to the incumbent?"

The model is dependency-light at inference time.  Training uses PyTorch when
available; the persisted artifact contains ordinary JSON lists.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from ai_investing.learning.features import FEATURE_NAMES
from ai_investing.learning.formula import FormulaModel


NN5_FEATURE_NAMES = list(FEATURE_NAMES)
DEFAULT_HIDDEN = 16
DEFAULT_EPOCHS = 300
DEFAULT_MIN_SAMPLES = 3000


@dataclass
class NN5ResidualModel:
    """Linear incumbent plus a gated nonlinear residual."""

    feature_names: list[str] = field(default_factory=lambda: list(NN5_FEATURE_NAMES))
    hidden: int = DEFAULT_HIDDEN
    W1: list[list[float]] = field(default_factory=list)
    b1: list[float] = field(default_factory=list)
    W2: list[float] = field(default_factory=list)
    b2: float = 0.0
    feature_mean: Optional[list[float]] = None
    feature_std: Optional[list[float]] = None
    baseline: dict = field(default_factory=dict)
    residual_scale: float = 1.0
    gate: float = 0.5
    version: int = 5
    fitted: bool = False
    val_loss: Optional[float] = None
    baseline_val_loss: Optional[float] = None

    def _baseline(self) -> FormulaModel:
        return FormulaModel.from_dict(self.baseline or {})

    def _vector(self, feats: dict[str, float]) -> list[float]:
        base = self._baseline()
        raw = base.raw(feats)
        conv = base.conviction(feats)
        target = base.target_from_conviction(conv)
        x = [float(feats.get(n, 0.0) or 0.0) for n in self.feature_names]
        # These three values make the residual conditional on the incumbent's
        # current opinion without giving the NN access to future information.
        x.extend((raw, conv, target))
        if self.feature_mean and self.feature_std:
            x = [(v - m) / s if s > 1e-9 else 0.0
                 for v, m, s in zip(x, self.feature_mean, self.feature_std)]
        return x

    def residual(self, feats: dict[str, float]) -> float:
        if not self.W1 or len(self.W2) != len(self.W1):
            return 0.0
        x = self._vector(feats)
        h = [math.tanh(sum(w * v for w, v in zip(row, x)) + b)
             for row, b in zip(self.W1, self.b1)]
        raw = sum(w * v for w, v in zip(self.W2, h)) + self.b2
        # The final layer is trained in return units. Clip only at inference
        # to keep an outlier residual from overpowering the incumbent.
        return max(-self.residual_scale, min(self.residual_scale, raw))

    def raw(self, feats: dict[str, float]) -> float:
        base = self._baseline()
        # The gate is intentionally bounded.  When the residual is uncertain,
        # NNv5 falls back continuously to the linear champion.
        return base.raw(feats) + self.gate * self.residual(feats)

    def conviction(self, feats: dict[str, float]) -> float:
        return math.tanh(self._baseline().gain * self.raw(feats))

    def target_from_conviction(self, conviction: float) -> float:
        return self._baseline().target_from_conviction(conviction)

    def target_weight(self, feats: dict[str, float]) -> float:
        return self.target_from_conviction(self.conviction(feats))

    def weight_of(self, name: str) -> float:
        return self._baseline().weight_of(name)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "feature_names", "hidden", "W1", "b1", "W2", "b2",
            "feature_mean", "feature_std", "baseline", "residual_scale",
            "gate", "version", "fitted", "val_loss", "baseline_val_loss")}

    @classmethod
    def from_dict(cls, data: dict) -> "NN5ResidualModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def n_params(self) -> int:
        return sum(map(len, self.W1)) + len(self.b1) + len(self.W2) + 1


def build_nn5_samples(backtester, assets, bars_by_key, baseline: FormulaModel):
    """Build point-in-time residual samples from the existing bar universe.

    The target is the same forward-return convention used by the linear
    backtester minus the incumbent's prediction at that timestamp.  No future
    value is used to form features or the baseline prediction.
    """
    from ai_investing.learning.features import FeatureExtractor

    aligned, length = backtester._aligned(bars_by_key)
    asset_by_key = {a.key: a for a in assets}; extractor = FeatureExtractor()
    rows = []
    for key, bars in aligned.items():
        asset = asset_by_key.get(key)
        if asset is None:
            continue
        for t in range(backtester.warmup, length - backtester.horizon):
            results = [s.evaluate(asset, bars[:t + 1], {}) for s in backtester.signals]
            feats = extractor.build(results, bars[:t + 1])
            fwd = ((bars[t + backtester.horizon].close - bars[t].close) / bars[t].close
                   if bars[t].close else 0.0)
            rows.append(([feats.get(n, 0.0) for n in NN5_FEATURE_NAMES],
                         fwd - baseline.raw(feats), t))
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def _normalise(X):
    n, d = len(X), len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    std = [(sum((row[j] - mean[j]) ** 2 for row in X) / max(1, n - 1)) ** 0.5
           for j in range(d)]
    return [[(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(row, mean, std)
             ] for row in X], mean, std


def fit_nn5(X, y, baseline: FormulaModel, *, hidden=DEFAULT_HIDDEN,
            epochs=DEFAULT_EPOCHS, min_samples=DEFAULT_MIN_SAMPLES,
            seed=7, t_index=None, purge=5, device=None):
    """Fit a purged, time-split residual net and return (model, reason)."""
    if not X or len(X) != len(y) or len(X) < min_samples:
        return None, "insufficient data for NN5 residual challenger"
    times = sorted(set(t_index or range(len(X))))
    cut = times[max(0, int(len(times) * 0.8) - 1)]
    train = [i for i, t in enumerate(t_index or range(len(X))) if t <= cut - purge]
    val = [i for i, t in enumerate(t_index or range(len(X))) if t > cut]
    minimum_split = max(20, min(50, min_samples // 4))
    if len(train) < minimum_split or len(val) < minimum_split:
        return None, "insufficient purged train/validation data for NN5"
    Xn, mean, std = _normalise([X[i] for i in train])
    Xv = [[(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(X[i], mean, std)] for i in val]
    try:
        import torch
        import torch.nn as nn
        torch.manual_seed(seed)
        selected = device or os.environ.get("NN5_DEVICE", "auto")
        if selected == "auto": selected = "cuda" if torch.cuda.is_available() else "cpu"
        dev = torch.device(selected)
        net = nn.Sequential(nn.Linear(len(Xn[0]) + 3, hidden), nn.Tanh(), nn.Linear(hidden, 1)).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=0.01, weight_decay=1e-3)
        raw_x = []
        for i in train:
            f = dict(zip(NN5_FEATURE_NAMES, X[i])); raw_x.append(X[i] + [baseline.raw(f), baseline.conviction(f), baseline.target_weight(f)])
        raw_v = []
        for i in val:
            f = dict(zip(NN5_FEATURE_NAMES, X[i])); raw_v.append(X[i] + [baseline.raw(f), baseline.conviction(f), baseline.target_weight(f)])
        tx = torch.tensor(raw_x, dtype=torch.float32, device=dev)
        vx = torch.tensor(raw_v, dtype=torch.float32, device=dev)
        ty = torch.tensor([y[i] for i in train], dtype=torch.float32, device=dev).reshape(-1, 1)
        vy = torch.tensor([y[i] for i in val], dtype=torch.float32, device=dev).reshape(-1, 1)
        best, state, bad = float("inf"), None, 0
        for _ in range(epochs):
            opt.zero_grad(set_to_none=True); loss = nn.functional.huber_loss(net(tx), ty)
            loss.backward(); opt.step()
            with torch.no_grad(): vl = float(nn.functional.huber_loss(net(vx), vy).cpu())
            if vl < best - 1e-8:
                best, bad, state = vl, 0, {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= 25: break
        if state is None: return None, "NN5 training did not converge"
        # The incumbent is the zero-residual model.  A lower training loss is
        # irrelevant if the residual net cannot beat that baseline on the
        # purged validation slice it never trained on.
        def huber(v): return 0.5 * v * v if abs(v) <= 1.0 else abs(v) - 0.5
        baseline_loss = sum(huber(y[i]) for i in val) / len(val)
        if best >= baseline_loss - 1e-10:
            return None, (f"NN5 residual did not beat incumbent validation loss "
                          f"({best:.8g} >= {baseline_loss:.8g})")
        net.load_state_dict(state); first, last = net[0], net[2]
        return NN5ResidualModel(
            hidden=hidden, W1=first.weight.detach().cpu().tolist(),
            b1=first.bias.detach().cpu().tolist(), W2=last.weight.detach().cpu().reshape(-1).tolist(),
            b2=float(last.bias.detach().cpu().item()), feature_mean=None, feature_std=None,
            baseline=baseline.to_dict(), residual_scale=max(0.005, min(0.10, (sum(abs(v) for v in y) / len(y)) * 2.0)),
            fitted=True, val_loss=best, baseline_val_loss=baseline_loss), ""
    except (ImportError, RuntimeError, ValueError) as exc:
        # The ProDesk is intentionally inference-first and has no CUDA stack.
        # Reuse the project's deterministic pure-Python MLP trainer there so
        # daily retraining remains possible when the RTX host is offline.
        if isinstance(exc, ImportError):
            from ai_investing.learning.nn_formula import fit_nn
            extended = []
            for row in X:
                f = dict(zip(NN5_FEATURE_NAMES, row))
                extended.append(row + [baseline.raw(f), baseline.conviction(f), baseline.target_weight(f)])
            fallback, reason = fit_nn(extended, y, hidden=hidden, epochs=epochs,
                                      min_samples=min_samples, t_index=t_index, purge=purge)
            if fallback is None:
                return None, "NN5 CPU fallback: " + reason
            zero = sum((y[i] * y[i]) / 2.0 for i in val) / len(val)
            if fallback.val_loss is None or fallback.val_loss >= zero - 1e-10:
                return None, "NN5 CPU residual did not beat incumbent validation loss"
            scale = max(0.005, min(0.10, (sum(abs(v) for v in y) / len(y)) * 2.0))
            return NN5ResidualModel(hidden=hidden, W1=fallback.W1, b1=fallback.b1,
                                    W2=fallback.W2, b2=fallback.b2,
                                    feature_mean=fallback.feature_mean,
                                    feature_std=fallback.feature_std,
                                    baseline=baseline.to_dict(), residual_scale=scale,
                                    fitted=True, val_loss=fallback.val_loss,
                                    baseline_val_loss=zero), ""
        return None, f"NN5 training backend failed: {exc}"
