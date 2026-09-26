"""Three-stage pipeline data models and stage exports."""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class SkillPatch:
    """Stage 2 产出：一个原子技能补丁（聚合材料）。"""
    source_pr_id: str
    confidence_score: float = 0.0
    # 2D Tags（含 [CANDIDATE] 标记的原始标签）
    tags: Dict[str, List[str]] = field(default_factory=lambda: {
        "domain": [], "problem_pattern": []
    })
    # Pattern Recognition / Root Cause / Solution Strategy
    content: str = ""
    # 溯源
    dimension_label: str = ""
    action_indices: List[int] = field(default_factory=list)
    root_cause: str = ""
    # 验证状态
    validated: bool = False
    validation_note: str = ""
    # Embedding（用于语义聚类，持久化存储）
    embedding: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillPatch":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


from .decompose import DecomposeStage
from .patch_gen import PatchGenStage
from .consolidate import ConsolidateStage

__all__ = [
    "SkillPatch",
    "DecomposeStage",
    "PatchGenStage",
    "ConsolidateStage",
]
