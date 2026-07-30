#!/usr/bin/env python3
"""知识库检索层 — Pydantic数据模型 (KT01-KT04).

对应架构设计 v1.1 §1.7 知识库检索层.
覆盖: KnowledgeItem, KnowledgeQueryResult, DishKnowledgeResult, OperationKnowledgeResult 等.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# 枚举类型
# ──────────────────────────────────────────────────────────────


class KnowledgeCategory(str, Enum):
    """知识库分类体系 (对应架构 §1.7 KNOWLEDGE_CATEGORIES)."""

    DISH = "dish"               # 菜品知识: 毛肚处理、底料配方、蘸料配比
    OPERATION = "operation"       # 操作规范: 切配标准、摆盘规范、出餐流程
    SUPPLIER = "supplier"         # 供应商信息: 王总冻品、潘厨品质标准
    SAFETY = "safety"             # 食品安全: 保质期管理、冷链要求、留样规定
    SERVICE = "service"           # 服务标准: 迎宾话术、投诉处理、加汤时机
    FINANCE = "finance"           # 经营数据: 成本结构、定价策略、损耗基准


# ──────────────────────────────────────────────────────────────
# 核心数据模型
# ──────────────────────────────────────────────────────────────


class KnowledgeItem(BaseModel):
    """知识条目."""

    item_id: str = Field(..., description="条目ID")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="正文内容")
    category: KnowledgeCategory = Field(..., description="分类")
    source_doc: str = Field("", description="来源文档名")
    author: str = Field("system", description="作者")
    tags: List[str] = Field(default_factory=list, description="标签")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="自定义元数据")
    embedding_id: Optional[str] = Field(None, description="向量索引ID(外部向量库)")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    is_deleted: bool = Field(False, description="软删除标记")

    class Config:
        use_enum_values = True


class KnowledgeSearchResult(BaseModel):
    """单条检索结果."""

    item_id: str
    title: str
    content: str                    # 正文片段(高亮关键词)
    category: str
    source_doc: str
    vector_score: float = 0.0      # 向量相似度(0~1)
    bm25_score: float = 0.0        # BM25相关性分数
    rrf_score: float = 0.0         # RRF融合分数
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def highlighted_content(self) -> str:
        """返回高亮内容(简化版, 实际应做关键词标记)."""
        return self.content[:200] + ("..." if len(self.content) > 200 else "")


class KnowledgeQueryResult(BaseModel):
    """混合检索结果.

    对应架构 §1.7 KnowledgeRetriever.query() 返回值.
    """

    query_text: str
    store_id: Optional[str] = None
    category: Optional[str] = None
    results: List[KnowledgeSearchResult] = Field(default_factory=list)
    total_found: int = 0
    query_ms: float = 0.0           # 检索耗时(ms)


class DishBasicInfo(BaseModel):
    """菜品基本信息."""

    category: str = ""              # 如 "毛肚类"
    taste_profile: str = ""         # 口感描述
    allergens: List[str] = Field(default_factory=list)  # 过敏原
    shelf_life_days: int = 0        # 保质期(天)
    storage_temp_c: str = ""        # 储存温度


class RecipeStep(BaseModel):
    """烹饪步骤."""

    step_no: int
    instruction: str
    duration_min: Optional[int] = None
    temperature_c: Optional[str] = None
    tips: str = ""


class Recipe(BaseModel):
    """菜谱."""

    name: str
    difficulty: str = ""           # easy / medium / hard
    time_min: int = 0
    steps: List[RecipeStep] = Field(default_factory=list)


class PricingRef(BaseModel):
    """定价参考."""

    cost_range: str = ""           # 如 "15-25"
    suggested_price: float = 0.0
    margin_pct: float = 0.0


class PairingSuggestion(BaseModel):
    """搭配建议."""

    dish_name: str
    reason: str


class QualityStandard(BaseModel):
    """品质标准."""

    spec: str                      # 规格描述
    method: str                    # 检测方法
    threshold: str                 # 阈值/标准值


class DishKnowledgeResult(BaseModel):
    """菜品专项检索结果 (KT01).

    对应架构 §1.7 KnowledgeRetriever.dish_query() 返回值.
    """

    dish_name: str
    intent: str = "general"        # general / recipe / pricing / pairing
    basic_info: DishBasicInfo = Field(default_factory=DishBasicInfo)
    recipes: List[Recipe] = Field(default_factory=list)
    pricing_ref: PricingRef = Field(default_factory=PricingRef)
    pairing_suggestions: List[PairingSuggestion] = Field(default_factory=list)
    quality_standards: List[QualityStandard] = Field(default_factory=list)
    source_items: List[KnowledgeSearchResult] = Field(default_factory=list)


class OperationKnowledgeResult(BaseModel):
    """经营Know-how检索结果 (KT02).

    对应架构 §1.7 KnowledgeRetriever.operation_query() 返回值.
    """

    question: str
    context: Optional[str] = None
    answer: str = ""                # 生成的摘要回答
    sources: List[KnowledgeSearchResult] = Field(default_factory=list)
    confidence: float = 0.0         # 回答置信度(0~1)
    follow_up_questions: List[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# BM25 倒排索引模型
# ──────────────────────────────────────────────────────────────


class BM25IndexEntry(BaseModel):
    """BM25倒排索引条目."""

    term: str                       # 分词后的term
    doc_ids: List[str] = Field(default_factory=list)  # 包含该term的文档ID列表
    df: int = 0                     # 文档频率(多少文档包含此term)


class BM25Document(BaseModel):
    """BM25文档(用于倒排索引)."""

    doc_id: str
    title: str
    content: str                   # 分词后的文本
    term_freqs: Dict[str, int] = Field(default_factory=dict)  # {term: freq}
    dl: int = 0                     # 文档长度(term数)
    category: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────
# 预置知识库分类常量
# ──────────────────────────────────────────────────────────────

KNOWLEDGE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "dish": {
        "name": "菜品知识",
        "examples": ["毛肚处理", "底料配方", "蘸料配比"],
        "prd_ref": "KT01",
    },
    "operation": {
        "name": "操作规范",
        "examples": ["切配标准", "摆盘规范", "出餐流程"],
        "prd_ref": "KT02",
    },
    "supplier": {
        "name": "供应商信息",
        "examples": ["王总冻品", "潘厨品质标准"],
        "prd_ref": "N05",
    },
    "safety": {
        "name": "食品安全",
        "examples": ["保质期管理", "冷链要求", "留样规定"],
        "prd_ref": "SC02",
    },
    "service": {
        "name": "服务标准",
        "examples": ["迎宾话术", "投诉处理", "加汤时机"],
        "prd_ref": "K系列",
    },
    "finance": {
        "name": "经营数据",
        "examples": ["成本结构", "定价策略", "损耗基准"],
        "prd_ref": "N04",
    },
}
