#!/usr/bin/env python3
"""
火瞳 · 手机端审批 UI (移动端友好)
=====================================
轻量级 Flask/FastAPI 审批页面，供门店管理者（如潘总）
在手机浏览器上查看采购建议并执行批准/驳回操作。

使用方式:
    # 启动审批服务 (默认端口 9090)
    python3 demo/approval_ui.py
    
    # 手机访问
    http://172.16.1.60:9090/

功能:
    - 📋 采购建议列表 (来自 Orchestration S1)
    - ✅ 一键批准 / ❌ 驳回 (带备注)
    - 📊 审批历史记录
    - 🔔 WebSocket 实时推送新建议

作者: 火瞳AI团队
日期: 2026-08-05
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

# 确保项目路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── 数据模型 ──

@dataclass
class PurchaseSuggestion:
    """采购建议"""
    id: str
    created_at: str
    sku: str
    sku_name: str
    qty: float
    unit: str = "kg"
    supplier: str = "王总(一级)"
    estimated_amount: float = 0.0
    reason: str = ""
    source: str = "waste_to_purchase_orchestration"
    waste_kg: float = 0.0
    status: str = "pending"  # pending | approved | rejected
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class ApprovalRecord:
    """审批记录"""
    id: str
    suggestion_id: str
    action: str  # approve | reject
    operator: str
    remark: str = ""
    created_at: str = ""


# ── 内存存储 (生产环境应替换为数据库) ──

class ApprovalStore:
    """审批数据存储"""
    
    def __init__(self):
        self.suggestions: Dict[str, PurchaseSuggestion] = {}
        self.records: List[ApprovalRecord] = []
        self._init_demo_data()
    
    def _init_demo_data(self):
        """初始化演示数据"""
        now = datetime.now().isoformat()
        
        # 示例采购建议 (来自 S1 废料→采购闭环)
        demo_suggestions = [
            PurchaseSuggestion(
                id=f"SUGG-{uuid.uuid4().hex[:6].upper()}",
                created_at=now,
                sku="FP-HNRC-001",
                sku_name="牛肉卷 (高频损耗品)",
                qty=78.5,
                supplier="王总(一级)",
                estimated_amount=1962.5,
                reason="基于废料分析(3.01kg) + WMA预测 + 季节性调整",
                source="waste_to_purchase_orchestration",
                waste_kg=3.01,
                status="pending",
                metadata={"confidence": 0.87, "prediction_method": "WMA+seasonal"},
            ),
            PurchaseSuggestion(
                id=f"SUGG-{uuid.uuid4().hex[:6].upper()}",
                created_at=now,
                sku="FP-HNRC-005",
                sku_name="毛肚 (鲜品)",
                qty=25.0,
                supplier="王总(一级)",
                estimated_amount=875.0,
                reason="库存低于安全线(当前8kg, 安全线15kg)",
                source="inventory_alert",
                waste_kg=0,
                status="pending",
                metadata={"current_stock": 8, "safety_stock": 15},
            ),
            ]
        
        for s in demo_suggestions:
            self.suggestions[s.id] = s
    
    def add_suggestion(self, suggestion: PurchaseSuggestion) -> str:
        """添加新建议"""
        self.suggestions[suggestion.id] = suggestion
        return suggestion.id
    
    def get_pending(self) -> List[PurchaseSuggestion]:
        """获取待审批列表"""
        return [s for s in self.suggestions.values() if s.status == "pending"]
    
    def get_all(self) -> List[PurchaseSuggestion]:
        """获取所有建议"""
        return list(self.suggestions.values())
    
    def approve(self, suggestion_id: str, operator: str = "demo", remark: str = "") -> bool:
        """批准建议"""
        if suggestion_id not in self.suggestions:
            return False
        
        s = self.suggestions[suggestion_id]
        s.status = "approved"
        s.approved_by = operator
        s.approved_at = datetime.now().isoformat()
        
        record = ApprovalRecord(
            id=f"APR-{uuid.uuid4().hex[:6].upper()}",
            suggestion_id=suggestion_id,
            action="approve",
            operator=operator,
            remark=remark,
            created_at=datetime.now().isoformat(),
        )
        self.records.append(record)
        return True
    
    def reject(self, suggestion_id: str, reason: str, operator: str = "demo") -> bool:
        """驳回建议"""
        if suggestion_id not in self.suggestions:
            return False
        
        s = self.suggestions[suggestion_id]
        s.status = "rejected"
        s.rejection_reason = reason
        
        record = ApprovalRecord(
            id=f"APR-{uuid.uuid4().hex[:6].upper()}",
            suggestion_id=suggestion_id,
            action="reject",
            operator=operator,
            remark=reason,
            created_at=datetime.now().isoformat(),
        )
        self.records.append(record)
        return True
    
    def get_records(self, limit: int = 20) -> List[ApprovalRecord]:
        """获取审批历史"""
        return sorted(self.records, key=lambda r: r.created_at, reverse=True)[:limit]


# 全局存储实例
store = ApprovalStore()


# ── HTML 页面 (移动端优先) ──

APPROVAL_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>火瞳 · 采购审批</title>
<style>
:root {
  --primary: #e74c3c;
  --primary-dark: #c0392b;
  --success: #27ae60;
  --danger: #e74c3c;
  --warning: #f39c12;
  --bg: #f5f5f5;
  --card-bg: #ffffff;
  --text: #2c3e50;
  --text-secondary: #7f8c8d;
  --border: #e0e0e0;
  --radius: 12px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding-bottom: 80px; }

/* Header */
.header { background: linear-gradient(135deg, #e74c3c, #c0392b); color: white; padding: 20px 16px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.header h1 { font-size: 20px; font-weight: 600; }
.header .subtitle { font-size: 13px; opacity: 0.85; margin-top: 4px; }
.header .stats { display: flex; gap: 16px; margin-top: 16px; }
.stat-item { flex: 1; background: rgba(255,255,255,0.15); border-radius: 8px; padding: 12px; text-align: center; }
.stat-num { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 11px; opacity: 0.85; margin-top: 2px; }

/* Cards */
.container { padding: 16px; max-width: 600px; margin: 0 auto; }
.card { background: var(--card-bg); border-radius: var(--radius); padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-title { font-size: 15px; font-weight: 600; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 500; }
.badge-pending { background: #fff3cd; color: #856404; }
.badge-approved { background: #d4edda; color: #155724; }
.badge-rejected { background: #f8d7da; color: #721c24; }

/* Product Info */
.product-info { display: flex; gap: 12px; margin-bottom: 12px; }
.product-icon { width: 48px; height: 48px; background: linear-gradient(135deg, #e74c3c22, #e74c3c44); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 24px; }
.product-details { flex: 1; }
.product-name { font-size: 15px; font-weight: 500; }
.product-meta { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

/* Amount */
.amount-row { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); margin: 10px 0; }
.amount-label { font-size: 13px; color: var(--text-secondary); }
.amount-value { font-size: 22px; font-weight: 700; color: var(--primary); }

/* Reason */
.reason-box { background: #f8f9fa; border-radius: 8px; padding: 10px 12px; font-size: 13px; line-height: 1.5; color: #555; margin-bottom: 14px; }

/* Actions */
.actions { display: flex; gap: 10px; }
.btn { flex: 1; padding: 14px; border-radius: 10px; font-size: 16px; font-weight: 600; text-align: center; cursor: pointer; border: none; transition: all 0.2s; min-height: 48px; display: flex; align-items: center; justify-content: center; gap: 6px; user-select: none; -webkit-user-select: none; }
.btn:active { transform: scale(0.96); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.btn-approve { background: var(--success); color: white; }
.btn-reject { background: var(--danger); color: white; }
.btn-disabled { background: #ccc; color: #666; cursor: not-allowed; }

/* Loading spinner */
.spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid rgba(255,255,255,.3); border-top-color: white; border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Approve Confirm Modal */
.approve-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 200; display: none; align-items: center; justify-content: center; padding: 20px; }
.approve-overlay.show { display: flex; }
.approve-modal { background: white; border-radius: var(--radius); width: 100%; max-width: 360px; padding: 24px; text-align: center; }
.approve-modal .approve-icon { font-size: 48px; margin-bottom: 12px; }
.approve-modal h3 { font-size: 18px; margin-bottom: 8px; color: var(--text); }
.approve-modal p { font-size: 14px; color: var(--text-secondary); margin-bottom: 6px; line-height: 1.5; }
.approve-modal .approve-detail { background: #f0fff4; border-radius: 8px; padding: 12px; margin: 16px 0; text-align: left; font-size: 13px; }
.approve-modal .approve-detail row { display: flex; justify-content: space-between; padding: 4px 0; }
.approve-modal .approve-detail .label { color: var(--text-secondary); }
.approve-modal .approve-detail .value { font-weight: 600; color: var(--success); }
.approve-actions { display: flex; gap: 10px; margin-top: 20px; }

/* History */
.history-item { display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.history-item:last-child { border-bottom: none; }
.history-icon { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
.icon-approve { background: #d4edda; color: #155724; }
.icon-reject { background: #f8d7da; color: #721c24; }
.history-info { flex: 1; min-width: 0; }
.history-action { font-size: 13px; font-weight: 500; }
.history-time { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

/* Empty State */
.empty-state { text-align: center; padding: 40px 20px; color: var(--text-secondary); }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* Toast */
.toast { position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.8); color: white; padding: 12px 24px; border-radius: 30px; font-size: 14px; z-index: 999; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
.toast.show { opacity: 1; }

/* Tab Bar */
.tab-bar { position: fixed; bottom: 0; left: 0; right: 0; background: white; display: flex; border-top: 1px solid var(--border); z-index: 100; }
.tab-item { flex: 1; padding: 12px 0; text-align: center; cursor: pointer; transition: color 0.2s; }
.tab-item.active { color: var(--primary); }
.tab-icon { font-size: 22px; }
.tab-label { font-size: 11px; margin-top: 2px; }

/* Modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 200; display: none; align-items: center; justify-content: center; padding: 20px; }
.modal-overlay.show { display: flex; }
.modal { background: white; border-radius: var(--radius); width: 100%; max-width: 360px; padding: 20px; }
.modal h3 { font-size: 17px; margin-bottom: 12px; }
.modal textarea { width: 100%; height: 80px; border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 14px; resize: none; margin-bottom: 12px; }
.modal-actions { display: flex; gap: 10px; }
.modal-btn { flex: 1; padding: 10px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; }
.modal-cancel { background: #eee; color: #333; }
.modal-confirm { background: var(--danger); color: white; }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <h1>🔥 火瞳采购审批</h1>
  <div class="subtitle">冯校长火锅 · 椒江店 | AI智能建议</div>
  <div class="stats">
    <div class="stat-item">
      <div class="stat-num" id="pending-count">0</div>
      <div class="stat-label">待审批</div>
    </div>
    <div class="stat-item">
      <div class="stat-num" id="approved-count">0</div>
      <div class="stat-label">已批准</div>
    </div>
    <div class="stat-item">
      <div class="stat-num" id="total-amount">¥0</div>
      <div class="stat-label">待批金额</div>
    </div>
  </div>
</div>

<!-- Content -->
<div class="container" id="content">
  <!-- 动态加载 -->
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<!-- Reject Modal -->
<div class="modal-overlay" id="reject-modal">
  <div class="modal">
    <h3>驳回原因</h3>
    <textarea id="reject-reason" placeholder="请输入驳回原因..."></textarea>
    <div class="modal-actions">
      <button class="modal-btn modal-cancel" onclick="closeModal()">取消</button>
      <button class="modal-btn modal-confirm" id="confirm-reject">确认驳回</button>
    </div>
  </div>
</div>

<!-- Approve Confirm Modal -->
<div class="approve-overlay" id="approve-modal">
  <div class="approve-modal">
    <div class="approve-icon">✅</div>
    <h3>确认批准采购？</h3>
    <p>此操作将生成正式采购订单，请确认以下信息：</p>
    <div class="approve-detail" id="approve-detail">
      <!-- 动态填充 -->
    </div>
    <div class="approve-actions">
      <button class="btn btn-disabled" style="flex:1;padding:12px;font-size:15px;" onclick="closeApproveModal()" id="approve-cancel">取消</button>
      <button class="btn btn-approve" style="flex:1;padding:12px;font-size:15px;" onclick="confirmApprove()" id="approve-confirm-btn">确认批准</button>
    </div>
  </div>
</div>

<!-- Tab Bar -->
<div class="tab-bar">
  <div class="tab-item active" onclick="switchTab('pending')">
    <div class="tab-icon">📋</div>
    <div class="tab-label">待审批</div>
  </div>
  <div class="tab-item" onclick="switchTab('history')">
    <div class="tab-icon">📜</div>
    <div class="tab-label">审批记录</div>
  </div>
</div>

<script>
let currentTab = 'pending';
let currentRejectId = null;
let currentApproveId = null;
let approveDataCache = {}; // 缓存批准数据

// API 基础路径
const API_BASE = '';

// ── Loading 工具 ──
function setButtonLoading(btn, loading) {
  if (loading) {
    btn.dataset.originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> 处理中...';
    btn.disabled = true;
  } else {
    btn.innerHTML = btn.dataset.originalText || btn.innerHTML;
    btn.disabled = false;
  }
}

// 加载待审批列表
async function loadPending() {
  try {
    const res = await fetch(API_BASE + '/api/approval/pending');
    const data = await res.json();
    renderSuggestions(data.suggestions || []);
    updateStats(data.stats || {});
  } catch(e) {
    document.getElementById('content').innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><p>加载失败，请刷新重试</p></div>';
  }
}

// 加载审批历史
async function loadHistory() {
  try {
    const res = await fetch(API_BASE + '/api/approval/records');
    const data = await res.json();
    renderHistory(data.records || []);
  } catch(e) {
    console.error('Failed to load history:', e);
  }
}

// 渲染建议卡片
function renderSuggestions(suggestions) {
  const container = document.getElementById('content');

  if (!suggestions.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">✅</div><p>暂无待审批事项</p><p style="font-size:12px;margin-top:8px;color:#999;">AI建议会自动推送到这里</p></div>';
    return;
  }

  // 缓存数据
  suggestions.forEach(s => { approveDataCache[s.id] = s; });

  container.innerHTML = suggestions.map(s => `
    <div class="card" id="card-${s.id}">
      <div class="card-header">
        <span class="card-title">${s.sku_name}</span>
        <span class="badge badge-pending">待审批</span>
      </div>

      <div class="product-info">
        <div class="product-icon">🥩</div>
        <div class="product-details">
          <div class="product-name">${s.sku_name}</div>
          <div class="product-meta">SKU: ${s.sku} | 数量: ${s.qty} ${s.unit} | 供应商: ${s.supplier}</div>
        </div>
      </div>

      ${s.waste_kg > 0 ? `<div class="reason-box">📊 废料分析: 检测到 ${s.waste_kg}kg 损耗，建议补货 ${s.qty}${s.unit}</div>` : ''}
      ${s.reason ? `<div class="reason-box">💡 ${s.reason}</div>` : ''}

      <div class="amount-row">
        <span class="amount-label">预估金额</span>
        <span class="amount-value">¥${s.estimated_amount.toLocaleString()}</span>
      </div>

      <div class="actions">
        <button class="btn btn-approve" onclick="approve('${s.id}')">✅ 批准</button>
        <button class="btn btn-reject" onclick="showRejectModal('${s.id}')">❌ 驳回</button>
      </div>
    </div>
  `).join('');
}

// 渲染历史记录
function renderHistory(records) {
  const container = document.getElementById('content');
  
  if (!records.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📜</div><p>暂无审批记录</p></div>';
    return;
  }
  
  container.innerHTML = '<h2 style="font-size:16px;margin-bottom:12px;">审批记录</h2>' +
    records.map(r => `
      <div class="card">
        <div class="history-item">
          <div class="history-icon ${r.action === 'approve' ? 'icon-approve' : 'icon-reject'}">
            ${r.action === 'approve' ? '✅' : '❌'}
          </div>
          <div class="history-info">
            <div class="history-action">${r.action === 'approve' ? '已批准' : '已驳回'}</div>
            <div class="history-time">${new Date(r.created_at).toLocaleString()}</div>
            ${r.remark ? `<div style="font-size:12px;color:#666;margin-top:2px;">${r.remark}</div>` : ''}
          </div>
        </div>
      </div>
    `).join('');
}

// 更新统计
function updateStats(stats) {
  document.getElementById('pending-count').textContent = stats.pending || 0;
  document.getElementById('approved-count').textContent = stats.approved || 0;
  document.getElementById('total-amount').textContent = '¥' + (stats.total_amount || 0).toLocaleString();
}

// 批准 - 显示确认弹窗
function approve(id) {
  // 从缓存获取数据
  const s = approveDataCache[id];
  if (!s) return;

  currentApproveId = id;

  // 填充详情
  document.getElementById('approve-detail').innerHTML = `
    <row><span class="label">商品</span><span class="value">${s.sku_name}</span></row>
    <row><span class="label">数量</span><span class="value">${s.qty} ${s.unit}</span></row>
    <row><span class="label">供应商</span><span class="value">${s.supplier}</span></row>
    <row><span class="label">金额</span><span class="value" style="font-size:16px;">¥${s.estimated_amount.toLocaleString()}</span></row>
    <row><span class="label">AI置信度</span><span class="value">${(s.confidence * 100).toFixed(0)}%</span></row>
  `;

  document.getElementById('approve-modal').classList.add('show');
}

// 关闭批准弹窗
function closeApproveModal() {
  document.getElementById('approve-modal').classList.remove('show');
  currentApproveId = null;
}

// 确认批准（真正执行）
async function confirmApprove() {
  if (!currentApproveId) return;

  const btn = document.getElementById('approve-confirm-btn');
  setButtonLoading(btn, true);

  try {
    const res = await fetch(API_BASE + '/api/approval/' + currentApproveId + '/approve', { method: 'POST' });
    const data = await res.json();

    if (data.success) {
      showToast('✅ 已批准! 采购订单已生成');
      closeApproveModal();
      setTimeout(loadPending, 1500);
    } else {
      showToast('❌ 操作失败: ' + (data.error || '未知错误'));
      setButtonLoading(btn, false);
    }
  } catch(e) {
    showToast('❌ 网络错误');
    setButtonLoading(btn, false);
  }
}

// 显示驳回弹窗
function showRejectModal(id) {
  currentRejectId = id;
  document.getElementById('reject-reason').value = '';
  document.getElementById('reject-modal').classList.add('show');
}

// 关闭弹窗
function closeModal() {
  document.getElementById('reject-modal').classList.remove('show');
  currentRejectId = null;
}

// 确认驳回
document.getElementById('confirm-reject').addEventListener('click', async () => {
  const reason = document.getElementById('reject-reason').value.trim();

  if (!reason) {
    showToast('⚠️ 请输入驳回原因');
    return;
  }

  if (!currentRejectId) return;

  const btn = document.getElementById('confirm-reject');
  setButtonLoading(btn, true);

  try {
    const res = await fetch(API_BASE + '/api/approval/' + currentRejectId + '/reject', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason})
    });
    const data = await res.json();

    if (data.success) {
      showToast('❌ 已驳回');
      closeModal();
      setTimeout(loadPending, 1500);
    } else {
      showToast('❌ 操作失败');
      setButtonLoading(btn, false);
    }
  } catch(e) {
    showToast('❌ 网络错误');
    setButtonLoading(btn, false);
  }
});

// 切换Tab
function switchTab(tab) {
  currentTab = tab;
  
  // 更新Tab样式
  document.querySelectorAll('.tab-item').forEach((el, i) => {
    el.classList.toggle('active', (tab === 'pending' && i === 0) || (tab === 'history' && i === 1));
  });
  
  // 加载数据
  if (tab === 'pending') {
    loadPending();
  } else {
    loadHistory();
  }
}

// Toast提示
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

// 初始化
loadPending();

// 自动刷新 (30秒)
setInterval(() => {
  if (currentTab === 'pending') loadPending();
}, 30000);
</script>
</body>
</html>"""


# ── FastAPI/Flask 路由 ──

def create_approval_app():
    """创建审批应用 (Flask 兼容)"""
    try:
        from flask import Flask, request, jsonify, send_file
        HAS_FLASK = True
    except ImportError:
        HAS_FLASK = False
    
    if not HAS_FLASK:
        print("ERROR: 需要安装 flask: pip3 install flask")
        return None
    
    app = Flask(__name__, static_folder=None)
    
    @app.route('/')
    def index():
        """审批首页 (移动端UI)"""
        return APPROVAL_PAGE_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}
    
    @app.route('/api/approval/pending')
    def api_pending():
        """获取待审批列表"""
        suggestions = store.get_pending()
        stats = {
            "pending": len(suggestions),
            "approved": len([s for s in store.get_all() if s.status == "approved"]),
            "total_amount": sum(s.estimated_amount for s in suggestions),
        }
        return jsonify({
            "success": True,
            "suggestions": [asdict(s) for s in suggestions],
            "stats": stats,
        })
    
    @app.route('/api/approval/records')
    def api_records():
        """获取审批历史"""
        records = store.get_records()
        return jsonify({
            "success": True,
            "records": [asdict(r) for r in records],
        })
    
    @app.route('/api/approval/<suggestion_id>/approve', methods=['POST'])
    def api_approve(suggestion_id):
        """批准建议"""
        success = store.approve(suggestion_id, operator="mobile_user")
        return jsonify({"success": success})
    
    @app.route('/api/approval/<suggestion_id>/reject', methods=['POST'])
    def api_reject(suggestion_id):
        """驳回建议"""
        data = request.get_json(force=True) or {}
        reason = data.get("reason", "")
        success = store.reject(suggestion_id, reason=reason, operator="mobile_user")
        return jsonify({"success": success})
    
    @app.route('/health')
    def health():
        """健康检查"""
        return jsonify({"status": "ok", "service": "approval_ui"})
    
    return app


# ── 主程序入口 ──

if __name__ == "__main__":
    app = create_approval_app()
    if app:
        PORT = int(os.environ.get("APPROVAL_PORT", 9090))
        HOST = os.environ.get("APPROVAL_HOST", "0.0.0.0")
        
        print("=" * 50)
        print("火瞳 · 手机端审批 UI")
        print("=" * 50)
        print(f"  地址: http://{HOST}:{PORT}/")
        print(f"  手机访问: http://172.16.1.60:{PORT}/")
        print(f"  API: http://{HOST}:{PORT}/api/")
        print("=" * 50)
        
        app.run(host=HOST, port=PORT, debug=False)
    else:
        sys.exit(1)
