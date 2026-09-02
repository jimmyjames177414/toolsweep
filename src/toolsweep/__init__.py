"""toolsweep - find out which tool-schema decision is costing your agent accuracy.

A controlled, factorial sweep over tool-schema variables. Vary one decision at a time -
the naming scheme, the enum wording, the nesting depth, how many tools you expose -
against a fixed task suite, and attribute the accuracy change to that decision, with a
confidence interval and a control arm.

To score your catalogue as-authored, use mcpgrade. To evolve your descriptions, use GEPA.
Use toolsweep to find out which schema decision is costing you accuracy.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .catalogue import Catalogue, EnumValue, Param, Tool
from .runner import Arm, SweepConfig, SweepResult, build_arms, plan, run
from .score import ItemScore, ToolCall, score_call
from .stats import Effect, compute_effect
from .suite import Item, Suite

__all__ = [
    "Arm",
    "Catalogue",
    "Effect",
    "EnumValue",
    "Item",
    "ItemScore",
    "Param",
    "Suite",
    "SweepConfig",
    "SweepResult",
    "Tool",
    "ToolCall",
    "__version__",
    "build_arms",
    "compute_effect",
    "plan",
    "run",
    "score_call",
]
