"""The adaptive learning engine: a parametric decision formula whose weights (theta)
are curated offline (walk-forward ridge fit) and matured online (regularized RLS on
realized P&L). See docs/FORMULA.md for the math."""
from ai_investing.learning.features import FEATURE_NAMES, FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.online import RLSLearner
from ai_investing.learning.attribution import OutcomeTracker
from ai_investing.learning.store import ParamStore

__all__ = [
    "FEATURE_NAMES", "FeatureExtractor", "FormulaModel",
    "RLSLearner", "OutcomeTracker", "ParamStore",
]
