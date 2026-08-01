#!/usr/bin/env python3
"""知识库检索包 — 统一入口 (KT01-KT04).

模块:
- models: Pydantic数据模型(KnowledgeItem, KnowledgeQueryResult, DishKnowledgeResult等)
- retriever: KnowledgeRetriever混合检索引擎(BM25+Vector RRF融合)

对应架构设计 v1.1 §1.7 知识库检索层.
"""

from .models import (
    BM25Document,
    BM25IndexEntry,
    DishBasicInfo,
    DishKnowledgeResult,
    KnowledgeCategory,
    KnowledgeItem,
    KnowledgeQueryResult,
    KnowledgeSearchResult,
    KNOWLEDGE_CATEGORIES,
    OperationKnowledgeResult,
    PairingSuggestion,
    PricingRef,
    QualityStandard,
    Recipe,
    RecipeStep,
)
from .retriever import KnowledgeRetriever

__all__ = [
    # 核心类
    "KnowledgeRetriever",
    # 模型
    "KnowledgeItem",
    "KnowledgeQueryResult",
    "KnowledgeSearchResult",
    "DishKnowledgeResult",
    "OperationKnowledgeResult",
    # 子模型
    "DishBasicInfo",
    "Recipe",
    "RecipeStep",
    "PricingRef",
    "PairingSuggestion",
    "QualityStandard",
    # 索引模型
    "BM25Document",
    "BM25IndexEntry",
    # 枚举/常量
    "KnowledgeCategory",
    "KNOWLEDGE_CATEGORIES",
]
