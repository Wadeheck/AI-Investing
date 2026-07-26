"""The Brain — persistent macro & relationship intelligence layer.

Pieces:
  graph.py      knowledge graph: factor/theme/asset/actor nodes, signed influence
                edges, and shock propagation ("a news impulse ripples node to node")
  events.py     structured event extraction from headlines + credibility scoring
                (signal vs noise / manipulation detection)
  regime.py     persistent macro regime state, market emotion, and the brain's own
                mood (confidence/caution from recent performance + stability)
  scenarios.py  pre-registered "if X then Y" hypotheses that fire on triggers
  core.py       orchestrator: headlines -> events -> propagation -> regime/mood ->
                per-asset impacts consumed by MacroLinkageSignal
"""
from ai_investing.brain.core import Brain
from ai_investing.brain.graph import KnowledgeGraph

__all__ = ["Brain", "KnowledgeGraph"]
