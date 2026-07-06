"""Tests for SOP RAG (DEV-303)."""

from platform.cloud.llm_report.sop_rag import SOPKnowledgeBase


def test_sop_search_receiving():
    kb = SOPKnowledgeBase()
    hits = kb.search("来料收货 RFID")
    assert hits
    assert any("收货" in h["sop_name"] for h in hits)


def test_sop_answer_rule():
    kb = SOPKnowledgeBase()
    result = kb.answer_rule("冷库温度怎么检查")
    assert result["query"]
    assert "answer" in result
    assert result["backend"] == "tfidf"


def test_sop_unknown_query():
    kb = SOPKnowledgeBase()
    result = kb.answer_rule("xyz_unknown_query_123")
    assert "未在 SOP" in result["answer"] or result["sources"] == []
