#!/usr/bin/env python3
"""知识库混合检索引擎 (KT01/KT02).

对应架构设计 v1.1 §1.7 KnowledgeRetriever.
检索模式: Hybrid Search (BM25 + Vector) → RRF (Reciprocal Rank Fusion).
"""

from __future__ import annotations

import logging
import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from .models import (
    BM25Document,
    BM25IndexEntry,
    DishKnowledgeResult,
    KnowledgeCategory,
    KnowledgeItem,
    KnowledgeQueryResult,
    KnowledgeSearchResult,
    OperationKnowledgeResult,
    KNOWLEDGE_CATEGORIES,
)

logger = logging.getLogger(__name__)


def _enum_val(val) -> str:
    """安全获取枚举值(兼容字符串和枚举对象)."""
    return val.value if hasattr(val, 'value') else str(val)

# ── 简单中文分词(无需外部依赖) ─────────────────────────────

def simple_tokenize(text: str) -> List[str]:
    """简单分词: 按中文字符/英文单词/数字分割.

    生产环境应替换为 jieba/其他专业分词器.
    """
    # 按非字母数字汉字字符分割，保留2+字符的token
    tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text.lower())
    result: List[str] = []
    for token in tokens:
        if len(token) <= 1:
            continue
        # 中文按单字切分(简化版)
        if re.match(r'^[\u4e00-\u9fff]+$', token):
            # 保留全词 + bigram
            result.append(token)
            for i in range(len(token) - 1):
                result.append(token[i:i + 2])
        else:
            result.append(token)
    return result


# ── 停用词表(简化版) ────────────────────────────────────────

STOP_WORDS: Set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
    "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它",
    "们", "什么", "怎么", "如何", "为什么", "哪", "哪个", "哪些",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "if", "about",
}


class KnowledgeRetriever:
    """知识库混合检索引擎 — 对接 PRD KT01/KT02.

    架构:
    - BM25 倒排索引(关键词精确匹配)
    - 向量相似度(语义匹配, 可接入OpenAI/bge)
    - RRF 融合排序

    无需外部依赖即可运行(BM25模式).
    向量模式需要额外配置 embedding_client.
    """

    def __init__(
        self,
        db_session=None,                  # DB连接(用于持久化)
        embedding_client=None,             # 向量嵌入客户端(可选)
        rrf_k: int = 60,                   # RRF平滑常数
        bm25_k1: float = 1.5,              # BM25 k1参数
        bm25_b: float = 0.75,              # BM25 b参数
    ) -> None:
        self._db = db_session
        self._embedding = embedding_client
        self._rrf_k = rrf_k
        self._bm25_k1 = bm25_k1
        self._bm25_b = bm25_b

        # 内存索引
        self._documents: Dict[str, BM25Document] = {}       # doc_id → document
        self._inverted_index: Dict[str, BM25IndexEntry] = {}  # term → index entry
        self._avg_dl: float = 0.0                           # 平均文档长度
        self._doc_count: int = 0

        # 从DB加载已有数据
        if db_session:
            self._ensure_tables()  # 确保表存在
            self._load_from_db()

    # ── 公开接口: 检索 ─────────────────────────────────────

    def query(
        self,
        query_text: str,
        store_id: Optional[str] = None,
        category: Optional[KnowledgeCategory] = None,
        top_k: int = 5,
        min_score: float = 0.001,       # RRF分数通常很小(0.001~0.05)
        hybrid_weight: float = 0.6,      # 向量权重(0~1), BM25权重=1-hybrid_weight
    ) -> KnowledgeQueryResult:
        """混合检索.

        算法:
        1. BM25 检索 → 得分列表
        2. 向量检索 → 得分列表(如有embedding客户端)
        3. RRF 融合 → 最终排序

        Returns:
            KnowledgeQueryResult 含 results[](按RRF分数降序)
        """
        start_time = time.time()

        query_tokens = [t for t in simple_tokenize(query_text) if t not in STOP_WORDS]

        # 1. BM25 检索
        bm25_results = self._bm25_search(query_tokens, category)

        # 2. 向量检索(可选)
        vector_results: List[tuple] = []
        if self._embedding and query_tokens:
            vector_results = self._vector_search(query_text, category)

        # 3. RRF 融合
        fused = self._rrf_fusion(bm25_results, vector_results, hybrid_weight)

        # 过滤 + 截断
        results = []
        for doc_id, score in fused[:top_k]:
            if score < min_score:
                continue
            doc = self._documents.get(doc_id)
            if not doc or doc.metadata.get("_deleted"):
                continue

            # 找到BM25和向量各自得分
            bm25_s = next((s for d, s in bm25_results if d == doc_id), 0.0)
            vec_s = next((s for d, s in vector_results if d == doc_id), 0.0)

            results.append(KnowledgeSearchResult(
                item_id=doc_id,
                title=doc.title,
                content=self._highlight(doc.content, query_tokens),
                category=doc.category,
                source_doc=doc.metadata.get("source_doc", ""),
                vector_score=round(vec_s, 4),
                bm25_score=round(bm25_s, 4),
                rrf_score=round(score, 4),
                metadata=doc.metadata,
            ))

        elapsed_ms = (time.time() - start_time) * 1000

        return KnowledgeQueryResult(
            query_text=query_text,
            store_id=store_id,
            category=category.value if category else None,
            results=results,
            total_found=len(fused),
            query_ms=round(elapsed_ms, 1),
        )

    def dish_query(
        self,
        dish_name: str,
        intent: str = "general",
        store_id: Optional[str] = None,
    ) -> DishKnowledgeResult:
        """菜品专项检索 (KT01).

        Args:
            dish_name: 菜品名
            intent: general / recipe / pricing / pairing
        """
        # 构建查询
        queries = {
            "general": f"{dish_name} 做法 配方",
            "recipe": f"{dish_name} 菜谱 步骤 烹饪方法",
            "pricing": f"{dish_name} 成本 定价 价格",
            "pairing": f"{dish_name} 搭配 配菜 推荐",
        }
        query_text = queries.get(intent, queries["general"])

        base_result = self.query(
            query_text=query_text,
            store_id=store_id,
            category=KnowledgeCategory.DISH,
            top_k=8,
        )

        # 结构化提取
        from .models import (
            DishBasicInfo, Recipe, RecipeStep, PricingRef,
            PairingSuggestion, QualityStandard,
        )
        basic_info = DishBasicInfo()
        recipes: List[Recipe] = []
        pricing_ref = PricingRef()
        pairings: List[PairingSuggestion] = []
        standards: List[QualityStandard] = []

        for r in base_result.results:
            meta = r.metadata or {}
            if intent in ("general", "recipe") and "recipe" in meta.get("type", ""):
                recipes.append(Recipe(**meta.get("recipe_data", {})))
            elif intent in ("general", "pricing") and "pricing" in meta.get("type", ""):
                pricing_ref = PricingRef(**meta.get("pricing_data", {}))
            elif intent in ("general", "pairing") and "pairing" in meta.get("type", ""):
                pairings.append(PairingSuggestion(**meta.get("pairing_data", {})))
            else:
                # 尝试从内容提取基本信息
                if not basic_info.category and r.content:
                    basic_info.category = r.category

        return DishKnowledgeResult(
            dish_name=dish_name,
            intent=intent,
            basic_info=basic_info,
            recipes=recipes,
            pricing_ref=pricing_ref,
            pairing_suggestions=pairings,
            quality_standards=standards,
            source_items=base_result.results,
        )

    def operation_query(
        self,
        question: str,
        context: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> OperationKnowledgeResult:
        """经营 Know-how 检索 (KT02).

        支持自然语言问题:
        - "毛肚怎么处理才能保持脆度？"
        - "底料配方比例是多少？"
        - "翻台率低怎么改善？"
        """
        # 扩展查询词
        expanded = question
        if context:
            expanded = f"{context} {question}"

        base_result = self.query(
            query_text=expanded,
            store_id=store_id,
            category=KnowledgeCategory.OPERATION,
            top_k=5,
        )

        # 生成摘要回答(简化版: 取第一个结果的内容作为回答)
        answer = ""
        confidence = 0.0
        if base_result.results:
            best = base_result.results[0]
            answer = f"根据知识库[{best.title}]: {best.highlighted_content}"
            confidence = best.rrf_score

        # 生成追问建议
        follow_ups = self._generate_follow_ups(question, base_result.results)

        return OperationKnowledgeResult(
            question=question,
            context=context,
            answer=answer,
            sources=base_result.results,
            confidence=confidence,
            follow_up_questions=follow_ups,
        )

    # ── 公开接口: 知识条目管理 ─────────────────────────────

    def add_item(
        self,
        title: str,
        content: str,
        category: KnowledgeCategory,
        source_doc: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        author: str = "system",
    ) -> KnowledgeItem:
        """新增知识条目(含自动向量化)."""
        # 确保表存在
        if self._db:
            self._ensure_tables()

        item_id = f"KB-{uuid.uuid4().hex[:10].upper()}"
        now = __import__("datetime").datetime.now()

        meta = metadata or {}
        meta["source_doc"] = source_doc

        item = KnowledgeItem(
            item_id=item_id,
            title=title,
            content=content,
            category=category,
            source_doc=source_doc,
            author=author,
            metadata=meta,
            created_at=now,
            updated_at=now,
        )

        # 更新内存索引
        self._add_to_index(item)

        # 持久化到DB
        if self._db:
            self._save_item(item)

        logger.info("Knowledge item added: %s [%s]", item_id, category.value)
        return item

    def delete_item(self, item_id: str, deleted_by: str) -> bool:
        """删除知识条目(软删除)."""
        doc = self._documents.get(item_id)
        if not doc:
            return False

        doc.metadata["_deleted"] = True
        doc.metadata["_deleted_by"] = deleted_by
        doc.metadata["_deleted_at"] = __import__("datetime").datetime.now().isoformat()

        if self._db:
            cursor = self._db.cursor()
            cursor.execute(
                "UPDATE knowledge_base SET is_deleted=1, updated_at=? WHERE item_id=?",
                (__import__("datetime").datetime.now().isoformat(), item_id),
            )
            self._db.commit()

        return True

    def list_items(
        self,
        category: Optional[KnowledgeCategory] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """列出知识条目."""
        items = []
        for doc_id, doc in self._documents.items():
            if doc.metadata.get("_deleted"):
                continue
            if category and doc.category != category.value:
                continue
            items.append({
                "item_id": doc_id,
                "title": doc.title,
                "category": doc.category,
                "source_doc": doc.metadata.get("source_doc", ""),
                "created_at": doc.metadata.get("created_at", ""),
            })

        total = len(items)
        start = (page - 1) * size
        return {"items": items[start:start + size], "total": total, "page": page, "size": size}

    # ── 内部: BM25 检索 ─────────────────────────────────────

    def _bm25_search(
        self,
        query_tokens: List[str],
        category: Optional[KnowledgeCategory],
    ) -> List[tuple]:
        """BM25评分检索. 返回 [(doc_id, score), ...]."""
        scores: Dict[str, float] = {}

        for token in query_tokens:
            entry = self._inverted_index.get(token)
            if not entry or not entry.doc_ids:
                continue

            idf = math.log(
                (self._doc_count - len(entry.doc_ids) + 0.5) / (len(entry.doc_ids) + 0.5) + 1.0
            )

            for doc_id in entry.doc_ids:
                doc = self._documents.get(doc_id)
                if not doc or doc.metadata.get("_deleted"):
                    continue
                if category and doc.category != category.value:
                    continue

                tf = doc.term_freqs.get(token, 0)
                dl = doc.dl or 1
                avg_dl = self._avg_dl or 1

                # BM25 评分公式
                numerator = tf * (self._bm25_k1 + 1)
                denominator = tf + self._bm25_k1 * (
                    1 - self._bm25_b + self._bm25_b * dl / avg_dl
                )
                score = idf * numerator / denominator

                scores[doc_id] = scores.get(doc_id, 0) + score

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # ── 内部: 向量检索 ───────────────────────────────────────

    def _vector_search(
        self,
        query_text: str,
        category: Optional[KnowledgeCategory],
    ) -> List[tuple]:
        """向量相似度检索.

        需要配置 embedding_client 才可用.
        返回 [(doc_id, score), ...].
        """
        if not self._embedding:
            return []

        try:
            query_vector = self._embedding.embed(query_text)
            results: List[tuple] = []

            for doc_id, doc in self._documents.items():
                if doc.metadata.get("_deleted"):
                    continue
                if category and doc.category != category.value:
                    continue
                vec_id = doc.metadata.get("embedding_id")
                if vec_id:
                    sim = self._embedding.similarity(query_vector, vec_id)
                    results.append((doc_id, sim))

            return sorted(results, key=lambda x: x[1], reverse=True)
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
            return []

    # ── 内部: RRF 融合 ──────────────────────────────────────

    @staticmethod
    def _rrf_fusion(
        bm25_results: List[tuple],
        vector_results: List[tuple],
        hybrid_weight: float,
    ) -> List[tuple]:
        """RRF (Reciprocal Rank Fusion) 融合.

        公式: RRF_score(d) = Σ_{r∈R} 1 / (k + rank_r(d))
        """
        k = 60  # RRF 平滑常数
        scores: Dict[str, float] = {}

        for rank, (doc_id, _) in enumerate(bm25_results, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + (1 - hybrid_weight) / (k + rank)

        for rank, (doc_id, _) in enumerate(vector_results, start=1):
            scores[doc_id] = scores.get(doc_id, 0) + hybrid_weight / (k + rank)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # ── 内部: 索引管理 ──────────────────────────────────────

    def _add_to_index(self, item: KnowledgeItem) -> None:
        """将知识条目添加到BM25倒排索引."""
        text = f"{item.title} {item.content}"
        tokens = simple_tokenize(text)
        filtered = [t for t in tokens if t not in STOP_WORDS]

        doc = BM25Document(
            doc_id=item.item_id,
            title=item.title,
            content=text,
            term_freqs={},
            dl=len(filtered),
            category=_enum_val(item.category),
            metadata={**item.metadata, "created_at": item.created_at.isoformat()},
        )

        # 词频统计
        for t in filtered:
            doc.term_freqs[t] = doc.term_freqs.get(t, 0) + 1

        # 更新倒排索引
        for term in set(filtered):
            if term not in self._inverted_index:
                self._inverted_index[term] = BM25IndexEntry(term=term, doc_ids=[], df=0)
            entry = self._inverted_index[term]
            if doc.doc_id not in entry.doc_ids:
                entry.doc_ids.append(doc.doc_id)
                entry.df += 1

        self._documents[doc.doc_id] = doc
        self._doc_count += 1
        self._update_avg_dl()

    def _update_avg_dl(self) -> None:
        """更新平均文档长度."""
        if self._documents:
            total_dl = sum(d.dl for d in self._documents.values())
            self._avg_dl = total_dl / len(self._documents)

    def _load_from_db(self) -> None:
        """从DB加载知识条目到内存索引."""
        try:
            cursor = self._db.cursor()
            cursor.execute(
                "SELECT item_id, title, content, category, source_doc, "
                "author, tags, metadata, created_at, is_deleted "
                "FROM knowledge_base WHERE is_deleted=0 OR is_deleted IS NULL"
            )
            rows = cursor.fetchall()
            loaded = 0
            for row in rows:
                import json
                item = KnowledgeItem(
                    item_id=row[0],
                    title=row[1],
                    content=row[2],
                    category=row[3],
                    source_doc=row[4] or "",
                    author=row[5] or "system",
                    tags=json.loads(row[6]) if row[6] else [],
                    metadata=json.loads(row[7]) if row[7] else {},
                    is_deleted=bool(row[9]),
                )
                if not item.is_deleted:
                    self._add_to_index(item)
                    loaded += 1
            logger.info("Loaded %d knowledge items from DB", loaded)
        except Exception as exc:
            logger.warning("Load from DB failed (may be first run): %s", exc)

    def _save_item(self, item: KnowledgeItem) -> None:
        """保存知识条目到DB."""
        import json
        cursor = self._db.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO knowledge_base (
                item_id, title, content, category, source_doc, author,
                tags, metadata, is_deleted, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.item_id, item.title, item.content, _enum_val(item.category),
            item.source_doc, item.author,
            json.dumps(item.tags, ensure_ascii=False),
            json.dumps(item.metadata, ensure_ascii=False),
            int(item.is_deleted),
            item.created_at.isoformat(),
            item.updated_at.isoformat(),
        ))
        self._db.commit()

        # 创建表(如果不存在)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """创建知识库相关DB表."""
        cursor = self._db.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                item_id     TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                category    TEXT NOT NULL,
                source_doc  TEXT DEFAULT '',
                author      TEXT DEFAULT 'system',
                tags        TEXT DEFAULT '[]',
                metadata    TEXT DEFAULT '{}',
                is_deleted  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category);
            CREATE INDEX IF NOT EXISTS idx_kb_deleted ON knowledge_base(is_deleted);
        """)
        self._db.commit()

    # ── 辅助方法 ────────────────────────────────────────────

    @staticmethod
    def _highlight(content: str, query_tokens: List[str]) -> str:
        """在内容中高亮查询词(简化版: 截取片段)."""
        if len(content) <= 300:
            return content
        # 找到包含最多查询词的位置
        best_start = 0
        best_count = 0
        for i in range(len(content) - 200):
            snippet = content[i:i + 200]
            count = sum(1 for t in query_tokens if t.lower() in snippet.lower())
            if count > best_count:
                best_count = count
                best_start = i
        if best_count > 0:
            return "..." + content[best_start:best_start + 300] + "..."
        return content[:300] + "..."

    @staticmethod
    def _generate_follow_ups(question: str, results: List[KnowledgeSearchResult]) -> List[str]:
        """生成追问建议(基于检索结果的标题)."""
        follow_ups = []
        for r in results[:3]:
            if r.title and r.title != question:
                follow_ups.append(r.title)
        return follow_ups[:3]
