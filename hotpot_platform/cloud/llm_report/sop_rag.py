"""SOP knowledge base RAG (DEV-303) — keyword retrieval + optional LLM answer."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOP_PATH = PROJECT_ROOT / "demo" / "data" / "sop_checklist.json"


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{2,}", text)
    return parts


def _build_tfidf(chunks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    """Pure-Python TF-IDF vectors per chunk."""
    doc_tokens: List[List[str]] = []
    for ch in chunks:
        tokens = _tokenize(ch.get("text", "") + " " + ch.get("sop_name", ""))
        doc_tokens.append(tokens)

    df: Dict[str, int] = {}
    for tokens in doc_tokens:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    n = max(len(chunks), 1)
    idf = {t: 1.0 + (n / (1 + df[t])) for t in df}

    vectors: List[Dict[str, float]] = []
    for tokens in doc_tokens:
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        vec = {t: (c / max(len(tokens), 1)) * idf.get(t, 1.0) for t, c in tf.items()}
        vectors.append(vec)
    return vectors, idf


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b))
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb + 1e-9)


class SOPKnowledgeBase:
    """TF-IDF RAG over SOP checklist JSON (DEV-303 vector upgrade)."""

    def __init__(self, sop_path: Optional[Path] = None) -> None:
        self.sop_path = sop_path or DEFAULT_SOP_PATH
        self.chunks: List[Dict[str, Any]] = []
        self._vectors: List[Dict[str, float]] = []
        self._load()

    def _load(self) -> None:
        if not self.sop_path.exists():
            return
        data = json.loads(self.sop_path.read_text(encoding="utf-8"))
        for sop in data.get("sops", []):
            text_parts = [
                sop.get("name", ""),
                sop.get("category", ""),
                sop.get("frequency", ""),
                " ".join(cp.get("name", "") for cp in sop.get("checkpoints", [])),
                " ".join(cp.get("fail_message", "") for cp in sop.get("checkpoints", []) if cp.get("fail_message")),
            ]
            self.chunks.append(
                {
                    "sop_id": sop.get("id"),
                    "sop_name": sop.get("name"),
                    "category": sop.get("category"),
                    "severity": sop.get("severity"),
                    "text": " ".join(text_parts),
                    "checkpoints": sop.get("checkpoints", []),
                    "shifts": sop.get("shifts", []),
                }
            )
        self._vectors, _ = _build_tfidf(self.chunks)

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.chunks:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return self.chunks[:top_k]

        # TF-IDF cosine similarity
        q_tf: Dict[str, int] = {}
        for t in q_tokens:
            q_tf[t] = q_tf.get(t, 0) + 1
        q_vec = {t: c / max(len(q_tokens), 1) for t, c in q_tf.items()}

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for vec, chunk in zip(self._vectors, self.chunks):
            score = _cosine(q_vec, vec)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)

        if scored:
            return [c for _, c in scored[:top_k]]

        # keyword fallback: first exact token overlap, then substring overlap for
        # Chinese phrases such as "来料收货" matching an SOP named "来料验收".
        q_set = set(q_tokens)
        for chunk in self.chunks:
            text_tokens = set(_tokenize(chunk["text"]))
            overlap = len(q_set & text_tokens)
            if overlap:
                scored.append((overlap / len(q_set), chunk))
            else:
                text = chunk["text"].lower()
                sub_overlap = sum(1 for token in q_tokens if token in text)
                if sub_overlap:
                    scored.append((sub_overlap / len(q_set), chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def answer_rule(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        hits = self.search(query, top_k)
        if not hits:
            return {
                "query": query,
                "answer": "未在 SOP 知识库中找到相关内容。请尝试关键词：开档、收货、冷库、改刀、打烊。",
                "sources": [],
                "backend": "tfidf",
            }
        lines = [f"关于「{query}」，匹配到以下 SOP：", ""]
        sources = []
        for h in hits:
            lines.append(f"**{h['sop_name']}**（{h['category']} · {h['severity']}）")
            for cp in h.get("checkpoints", [])[:4]:
                lines.append(f"- {cp.get('name')}")
            lines.append("")
            sources.append({"sop_id": h["sop_id"], "sop_name": h["sop_name"]})
        return {"query": query, "answer": "\n".join(lines), "sources": sources, "backend": "tfidf"}


class OpenAISOPAgent(SOPKnowledgeBase):
    """LLM answer grounded on retrieved SOP chunks."""

    def __init__(
        self,
        api_key: str,
        sop_path: Optional[Path] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
    ) -> None:
        super().__init__(sop_path)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback = SOPKnowledgeBase(sop_path)

    def answer(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        hits = self.search(query, top_k)
        if not hits:
            return self.fallback.answer_rule(query, top_k)
        context = json.dumps(
            [{"sop": h["sop_name"], "checkpoints": h.get("checkpoints", [])} for h in hits],
            ensure_ascii=False,
        )
        prompt = (
            "你是冯校长火锅后厨 SOP 专家。仅根据以下 SOP 片段回答店长/厨师长的问题，"
            "回答要简洁、可执行。若知识库无相关信息，明确说明。\n\n"
            f"SOP 片段：{context}\n\n问题：{query}"
        )
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
            answer = data["choices"][0]["message"]["content"]
            return {
                "query": query,
                "answer": answer,
                "sources": [{"sop_id": h["sop_id"], "sop_name": h["sop_name"]} for h in hits],
                "backend": "openai",
            }
        except Exception as exc:
            result = self.fallback.answer_rule(query, top_k)
            result["answer"] += f"\n\n（LLM 不可用: {exc}）"
            return result


def create_sop_agent(backend: str = "rule") -> SOPKnowledgeBase:
    if backend == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            return OpenAISOPAgent(key, base_url=base, model=model)
    kb = SOPKnowledgeBase()
    kb.answer = kb.answer_rule  # type: ignore[method-assign]
    return kb
