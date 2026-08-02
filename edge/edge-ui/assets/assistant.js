/**
 * 火瞳 D2 岗位 AI 助理 - 前端逻辑
 * ==================================
 * 支持: dashboard.html / kitchen-assistant.html / purchase-assistant.html / supplier-portal.html
 */

const API_BASE = '/api/v1/assistant';

// ====== Utility ======

function apiCall(method, url, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  return fetch(url, opts).then(r => r.json()).then(d => {
    if (d.code !== 0) throw new Error(d.msg || 'API error');
    return d.data;
  });
}

function formatTime(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function formatDate(isoStr) {
  if (!isoStr) return '-';
  return isoStr.split('T')[0];
}

// ====== A01 Dashboard ======

function loadDashboard() {
  // Set date
  document.getElementById('dateDisplay').textContent = new Date().toLocaleDateString('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'long'
  });

  apiCall('GET', `${API_BASE}/dashboard`).then(data => {
    renderKPIs(data.kpis || []);
    renderTasks(data.tasks || []);
    renderSuggestions(data.suggestions || []);
    renderTrends(data.trends || {});
  }).catch(err => {
    console.error('Dashboard load error:', err);
    document.getElementById('kpiRow').innerHTML = '<div class="kpi-card" style="grid-column:1/-1"><div class="kpi-label" style="color:#ef4444">加载失败，请先加载Demo数据</div></div>';
  });

  // 加载Gateway审批状态 (P1增强)
  if (document.getElementById('approvalList')) {
    loadApprovalStatus();
  }
}

function renderKPIs(kpis) {
  const row = document.getElementById('kpiRow');
  row.innerHTML = kpis.map(k => `
    <div class="kpi-card ${k.status === 'warning' ? 'warning' : ''} ${k.status === 'critical' ? 'critical' : ''}">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${typeof k.value === 'number' && k.value >= 1000
        ? (k.value >= 10000 ? '\u00a5' + (k.value/10000).toFixed(1) + 'w' : '\u00a5' + k.value.toLocaleString())
        : k.value}<span class="kpi-unit">${k.unit}</span></div>
      <div class="kpi-change ${k.change > 0 ? 'change-up' : k.change < 0 ? 'change-down' : 'change-stable'}">
        ${k.change > 0 ? '\u2191' + k.change + '%' : k.change < 0 ? '\u2193' + Math.abs(k.change) + '%' : '-'}
        ${k.target ? '<span style="margin-left:6px;color:#9ca3af;font-weight:400">目标\u2264' + k.target + '</span>' : ''}
      </div>
    </div>
  `).join('');
}

function renderTasks(tasks) {
  const list = document.getElementById('taskList');
  const countEl = document.getElementById('taskCount');
  countEl.textContent = `(${tasks.length})`;

  if (!tasks.length) {
    list.innerHTML = '<li class="empty-state"><div class="icon">&#9989;</div>暂无待办事项</div>';
    return;
  }

  list.innerHTML = tasks.map(t => `
    <li class="task-item">
      <span class="priority-dot p-${t.priority}"></span>
      <div class="task-body">
        <div class="task-title">${t.title}</div>
        <div class="task-desc">${t.description || t.source_module}</div>
      </div>
      <div class="task-action">
        <a class="btn-task ${t.priority === 'urgent' ? 'urgent' : ''}" href="${t.action_url || '#'}"
           onclick="handleTaskAction('${t.id}', '${t.action_url}')">${t.action_text || '处理'}</a>
      </div>
    </li>
  `).join('');
}

function handleTaskAction(taskId, url) {
  // Mark as completed when clicking action
  apiCall('PUT', `${API_BASE}/tasks/${taskId}/complete`).then(() => {
    window.location.href = url;
  }).catch(console.error);
}

function renderSuggestions(suggestions) {
  const container = document.getElementById('sugList');
  if (!suggestions.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">&#129302;</div>暂无AI建议</div>';
    return;
  }

  container.innerHTML = suggestions.map(s => `
    <div class="sug-card">
      <div class="sug-header">
        <span class="sug-title">${s.title}</span>
        <span class="sug-confidence">${Math.round((s.confidence || 0) * 100)}%置信</span>
      </div>
      <div class="sug-content">${s.content}</div>
      <div class="sug-actions">
        <button class="btn-sug btn-accept" onclick="acceptSuggestion('${s.id}')">&#10003; 采纳</button>
        <button class="btn-sug btn-reject" onclick="rejectSuggestion('${s.id}')">&#10007; 忽略</button>
        <button class="btn-sug btn-detail" onclick="alert('${(s.source_analysis || '').replace(/'/g, "\\'")}')">&#128196; 分析依据</button>
      </div>
    </div>
  `).join('');
}

function acceptSuggestion(id) {
  apiCall('PUT', `${API_BASE}/suggestions/${id}/accept`).then(() => {
    alert('已采纳！系统将根据此建议优化后续推荐。');
    loadDashboard();
  });
}

function rejectSuggestion(id) {
  apiCall('PUT', `${API_BASE}/suggestions/${id}/reject`).then(() => {
    loadDashboard();
  });
}

function renderTrends(trends) {
  const row = document.getElementById('trendRow');
  if (!row) return;

  const items = [
    { label: '损耗率 (%)', data: trends.waste_rate || [], max: 10, color: 'bar-orange', unit: '%', good: true },
    { label: '合格率 (%)', data: trends.pass_rate || [], max: 100, color: 'bar-green', unit: '%', good: true },
    { label: '采购单数', data: trends.po_count || [], max: 10, color: 'bar-blue', unit: '', good: false },
  ];

  row.innerHTML = items.map(item => {
    const latest = item.data[item.data.length - 1] || 0;
    const pct = Math.min((latest / item.max) * 100, 100);
    return `
      <div class="trend-item">
        <div class="trend-label"><span>${item.label}</span><span>${latest}${item.unit}</span></div>
        <div class="trend-bar-bg">
          <div class="trend-bar ${item.color}" style="width:${pct}%">${latest}${item.unit}</div>
        </div>
      </div>`;
  }).join('');
}

function switchRole(role) {
  switch(role) {
    case 'chef_head': location.href = 'kitchen-assistant.html'; break;
    case 'purchaser': location.href = 'purchase-assistant.html'; break;
    case 'supplier': location.href = 'supplier-portal.html'; break;
    default: /* stay on dashboard */
  }
}


// ====== A02 Kitchen Assistant ======

function loadKitchenPanel() {
  apiCall('GET', `${API_BASE}/kitchen`).then(data => {
    renderIoT(data.iot_status || {});
    renderAlerts(data.alerts || [], data.summary?.alert_count || 0);
    renderPrepList(data.prep_list || [], data.summary || {});
    renderWasteEvents(data.waste_events || []);
    renderSOPAlerts(data.alerts || []);
  }).catch(err => {
    console.error('Kitchen panel error:', err);
  });
}

function renderIoT(iot) {
  const grid = document.getElementById('iotGrid');
  if (!grid) return;

  grid.innerHTML = Object.entries(iot).map(([key, val]) => {
    const isOk = val.status === 'normal';
    const tempClass = isOk ? 'normal' : (val.temp > (val.threshold || 0) ? 'critical' : 'warning');
    return `
      <div class="iot-item ${tempClass}">
        <div class="iot-name">${val.name}</div>
        <div class="iot-value">${val.temp}\u2103</div>
        <div class="iot-status ${isOk ? 'status-ok' : 'status-warn'}">${isOk ? '\u2705 正常' : '\u26a0\ufe0f 异常'}</div>
      </div>`;
  }).join('');
}

function renderAlerts(alerts, count) {
  const list = document.getElementById('alertList');
  const countEl = document.getElementById('alertCount');
  if (countEl) countEl.textContent = `(${count})`;
  if (!list) return;

  if (!alerts.length) {
    list.innerHTML = '<li style="padding:12px;text-align:center;color:#10b981;">&#9989; 今日无告警</li>';
    return;
  }

  const iconMap = { info: '\u2139\ufe0f', warn: '\u26a0\ufe0f', err: '\u274c' };
  list.innerHTML = alerts.map(a => `
    <li class="alert-item">
      <span class="alert-icon alert-level-${a.level}">${iconMap[a.level] || '&#128172;'}</span>
      <span>${a.message}</span>
    </li>`).join('');
}

function renderPrepList(prepList, summary) {
  const tbody = document.querySelector('#prepTable tbody');
  const summaryEl = document.getElementById('prepSummary');
  if (!tbody) return;

  if (summaryEl) {
    summaryEl.textContent = `(已完成${summary.completed}/${summary.total_items}, ${summary.pending}项待备)`;
  }

  tbody.innerHTML = prepList.map(p => {
    const pct = Math.round(p.prepped / p.target * 100);
    const statusClass = p.status === 'done' ? 'done' : p.status === 'partial' ? 'partial' : 'todo';
    const fillClass = statusClass === 'done' ? 'fill-done' : statusClass === 'partial' ? 'fill-partial' : 'fill-todo';
    const statusText = { done: '\u2705 已完成', partial: '\ud83d\udfe7 进行中', todo: '\u2b55 未开始' };
    return `<tr>
      <td>${p.product_name}</td>
      <td>${p.prepped}/${p.target} ${p.unit}</td>
      <td><div class="progress-bar"><div class="progress-fill ${fillClass}" style="width:${pct}%"></div></div></td>
      <td><span class="prep-status status-${statusClass}">${statusText[p.status]}</span>${p.warning ? ' &#9888;' : ''}</td>
    </tr>`;
  }).join('');
}

function renderWasteEvents(events) {
  const container = document.getElementById('wasteTimeline');
  if (!container) return;

  if (!events.length) {
    container.innerHTML = '<div class="empty-state"><div style="color:#d1d5db;">暂无废料记录</div></div>';
    return;
  }

  container.innerHTML = events.map(e => `
    <div class="waste-event">
      <div class="waste-time">${e.time}</div>
      <div class="waste-desc">废弃 ${e.item} ${e.qty}${e.qty > 1 ? e.qty === 3 ? '盘' : '份' : ''}</div>
      <div class="waste-reason">原因: ${e.reason}</div>
    </div>`).join('');
}

function renderSOPAlerts(alerts) {
  const container = document.getElementById('sopAlerts');
  if (!container) return;

  if (!alerts.length) {
    container.innerHTML = '<div style="color:#10b981;padding:12px;">&#9989; SOP执行正常，无异常提醒</div>';
    return;
  }

  container.innerHTML = alerts.map(a => `
    <div style="display:flex;gap:8px;padding:10px;border-radius:8px;margin-bottom:8px;
      background:${a.level === 'warning' ? '#fffbeb' : '#eff6ff'};border:1px solid ${a.level === 'warning' ? '#fde68a' : '#bfdbfe'};">
      <span style="font-size:16px;flex-shrink:0;">${a.level === 'warning' ? '\u26a0\ufe0f' : '\u2139\ufe0f'}</span>
      <span style="font-size:13px;color:${a.level === 'warning' ? '#92400e' : '#1e40af'};">${a.message}</span>
    </div>`).join('');
}


// ====== A03 Purchase Assistant ======

function loadPurchasePanel() {
  Promise.all([
    apiCall('GET', `${API_BASE}/purchase`),
    apiCall('GET', `${API_BASE}/suggestions?role=purchaser`),
  ]).then(([data, suggestions]) => {
    renderPurchaseKPIs(data.kpis || []);
    renderPOSuggestions(suggestions || []);
    renderPOTracking(data.po_tracking || []);
    renderSupplierComparison(data.supplier_comparison || []);
  }).catch(err => {
    console.error('Purchase panel error:', err);
  });
}

function renderPurchaseKPIs(kpis) {
  const row = document.getElementById('kpiRow');
  if (!row) return;
  row.innerHTML = kpis.map(k => `
    <div class="kpi-card ${k.status === 'warning' ? 'warning' : ''}">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${typeof k.value === 'number' && k.value >= 1000
        ? '\u00a5' + (k.value/10000).toFixed(1) + 'w' : k.value}<span class="kpi-unit">${k.unit}</span></div>
      ${k.usage_pct ? `<div class="kpi-change change-stable">预算 ${k.usage_pct}%</div>` : ''}
      ${k.change ? `<div class="kpi-change ${k.change > 0 ? 'change-up' : 'change-down'}">\u2193${Math.abs(k.change)}</div>` : ''}
    </div>`).join('');
}

function renderPOSuggestions(suggestions) {
  const container = document.getElementById('poSuggestions');
  if (!container) return;

  if (!suggestions.length) {
    container.innerHTML = '<div class="empty-state"><div style="color:#d1d5db;">暂无采购建议</div></div>';
    return;
  }

  container.innerHTML = suggestions.map(s => `
    <div class="po-sug-card">
      <div class="po-sug-title">
        <span>&#128230; ${s.title}</span>
        <span style="font-size:11px;background:#3b82f6;color:#fff;padding:2px 8px;border-radius:10px;">
          ${(s.confidence || 0)*100}%置信</span>
      </div>
      <div class="po-sug-body">${s.content}</div>
      <div class="po-sug-actions">
        <button class="btn-po btn-create" onclick="location.href='purchase-order.html'">&#128230; 创建PO</button>
        <button class="btn-po btn-compare" onclick="location.href='supplier.html'">&#128101; 比价</button>
      </div>
    </div>`).join('');
}

function renderPOTracking(tracking) {
  const container = document.getElementById('poTracking');
  if (!container) return;

  if (!tracking.length) {
    container.innerHTML = '<div class="empty-state"><div style="color:#d1d5db;">暂无订单</div></div>';
    return;
  }

  const statusMap = { received: 'st-received', partial: 'st-partial', confirmed: 'st-confirmed', submitted: 'st-pending' };

  container.innerHTML = tracking.map(po => {
    const cls = statusMap[po.status] || 'st-pending';
    return `
      <div class="po-track-item">
        <span class="po-status-dot ${cls}"></span>
        <div class="po-info">
          <div class="po-no">${po.order_no}</div>
          <div class="po-detail">${po.supplier_name} · ${po.items_summary} · \u00a5${po.total_amount?.toLocaleString()}</div>
        </div>
        <div class="pct-bar"><div class="pct-fill" style="width:${po.received_pct || 0}%"></div></div>
      </div>`;
  }).join('');
}

function renderSupplierComparison(comparison) {
  const tbody = document.querySelector('#compTable tbody');
  if (!tbody) return;

  tbody.innerHTML = comparison.map(s => `
    <tr>
      <td style="font-weight:600">${s.name}</td>
      <td>\u00a5${s.avg_price || '-'}</td>
      <td><span class="grade-badge g-${s.grade}">${s.grade}级</span></td>
      <td>${s.lead_time}</td>
      <td>${s.on_time_rate}%</td>
      <td>${s.quality_score || '-'}</td>
      <td>${s.recommended ? '<span class="rec-tag">\u2705 推荐</span>' : s.grade === 'C' ? '<span class="warn-tag">\u26a0\ufe0f 慎用</span>' : ''}</td>
    </tr>`).join('');
}


// ====== A04 Supplier Portal ======

function loadSupplierPortal() {
  // Use first active supplier as demo default
  apiCall('GET', `${API_BASE}/supplier-portal`).then(data => {
    if (data.suppliers && data.suppliers.length > 0) {
      const sid = data.suppliers[0].id;
      return apiCall('GET', `${API_BASE}/supplier-portal?supplier_id=${sid}`);
    }
    return {};
  }).then(data => {
    renderSupplierKPIs(data.kpis || []);
    renderPendingOrders(data.pending_orders || []);
    renderQualitySummary(data.quality_summary || {});
    renderScoreHistory(data.score_history || []);
  }).catch(err => {
    console.error('Supplier portal error:', err);
  });
}

function renderSupplierKPIs(kpis) {
  const grid = document.getElementById('spKpiGrid');
  if (!grid) return;

  grid.innerHTML = kpis.map(k => `
    <div class="sp-card">
      <div class="sp-card-value">${typeof k.value === 'number' ? k.value : k.value}</div>
      <div class="sp-card-label">${k.label}${k.unit ? k.unit : ''}</div>
      ${k.change !== undefined ? `<div class="sp-card-change ${k.change > 0 ? 'change-pos' : 'change-neg'}">
        ${k.change > 0 ? '\u2191' : k.change < 0 ? '\u2193' : ''}${Math.abs(k.change)}</div>` : ''}
      ${k.grade ? `<div style="margin-top:4px;"><span class="grade-badge g-${k.grade}">${k.grade}级</span></div>` : ''}
    </div>`).join('');
}

function renderPendingOrders(orders) {
  const container = document.getElementById('pendingOrders');
  if (!container) return;

  if (!orders.length) {
    container.innerHTML = '<div style="text-align:center;padding:20px;color:#10b981;">&#9989; 无待确认订单</div>';
    return;
  }

  container.innerHTML = orders.map(o => `
    <div class="pending-order">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>${o.order_no}</strong> <span class="po-new-tag">NEW</span>
      </div>
      <div class="po-items">${o.items ? o.items.map(i => `\u2022 ${i.name} ${i.qty}${i.unit}`).join('<br>') : ''}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px;">
        金额: \u00a5${o.total_amount?.toLocaleString()} | 期望到货: ${o.expected_date || '待定'}
      </div>
      <div class="po-actions">
        <button class="btn-sp btn-confirm" onclick="alert('\u2705 已确认接单！')">&#10004; 确认接单</button>
        <button class="btn-sp btn-negotiate" onclick="alert('\U0001f4ac 协商功能开发中...')">&#128269; 协商修改</button>
      </div>
    </div>`).join('');
}

function renderQualitySummary(qs) {
  const container = document.getElementById('qualitySummary');
  if (!container || !qs.total_receivings) {
    if (container) container.innerHTML = '<div style="padding:20px;text-align:center;color:#9ca3af;">暂无品质数据</div>';
    return;
  }

  const pct = qs.pass_rate || 0;
  container.innerHTML = `
    <div class="qs-row"><span>近30日收货</span><strong>${qs.total_receivings} 批</strong></div>
    <div class="qs-row"><span>合格批次</span><strong>${qs.passed} 批 (${pct}%)</strong></div>
    <div class="qs-bar"><div class="qs-fill" style="width:${pct}%">${pct}% 合格</div></div>
    ${qs.issues && qs.issues.length ? `
      <ul class="issue-list">
        ${qs.issues.map(i => `<li class="issue-item">&#9888; ${i}</li>`).join('')}
      </ul>` : '<div style="margin-top:8px;color:#10b981;font-size:13px;">&#9989; 品质表现良好</div>'}
  `;
}

function renderScoreHistory(scores) {
  const container = document.getElementById('scoreHistory');
  if (!container) return;

  if (!scores.length) {
    container.innerHTML = '<div class="empty-state"><div style="color:#d1d5db;">暂无评分历史</div></div>';
    return;
  }

  container.innerHTML = scores.slice(-8).reverse().map(s => `
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f3f4f6;font-size:13px;">
      <span>${formatDate(s.calc_at)}</span>
      <span style="font-weight:600;">${s.overall}分
        <span class="grade-badge g-${s.grade}" style="margin-left:6px;">${s.grade}</span></span>
    </div>`).join('');
}


// ====== Demo Data Loader ======

function loadDemoData() {
  apiCall('POST', `${API_BASE}/seed-demo`).then(result => {
    alert(`Demo 数据加载完成!\n待办: ${result.tasks_count || '?'} 条\nAI建议: 若干条\n\n请刷新页面查看效果。`);
    // Reload current page data
    initCurrentPage();
  });
}

// ====== Gateway Approval Status (P1增强) ======

function loadApprovalStatus() {
  // 检查Gateway状态
  fetch(`${API_BASE}/gateway/status`)
    .then(r => r.json())
    .then(d => {
      const badge = document.getElementById('gatewayStatus');
      if (d.data && d.data.gateway_enabled) {
        badge.className = 'gateway-badge gw-active';
        badge.textContent = '✓ Gateway在线';
        // 加载审批列表
        loadApprovalList();
      } else {
        badge.className = 'gateway-badge gw-inactive';
        badge.textContent = '✗ Gateway离线';
        document.getElementById('approvalList').innerHTML =
          '<div class="empty-state"><div class="icon">&#128276;</div>Gateway未启用，审批功能不可用</div>';
        document.getElementById('approvalCount').textContent = '';
      }
    })
    .catch(err => {
      console.warn('Gateway status check failed:', err);
      document.getElementById('gatewayStatus').className = 'gateway-badge gw-inactive';
      document.getElementById('gatewayStatus').textContent = '? 未知';
    });
}

function loadApprovalList() {
  // 获取待审批任务列表 (从Dashboard数据中提取)
  fetch(`${API_BASE}/dashboard/full`, { credentials: 'include' })
    .then(r => r.json())
    .then(d => {
      const container = document.getElementById('approvalList');
      const countEl = document.getElementById('approvalCount');

      if (!d.data || !d.data.pending_approvals) {
        // 如果没有pending_approvals字段，显示模拟数据或空状态
        container.innerHTML = `
          <div class="approval-card">
            <div class="approval-header">
              <span class="approval-title">暂无待审批任务</span>
              <span class="approval-badge">0</span>
            </div>
            <div style="font-size:13px;color:#9ca3af;padding:8px 0;">
              所有采购任务已处理完毕 ✓
            </div>
          </div>`;
        countEl.textContent = '(0)';
        return;
      }

      const approvals = d.data.pending_approvals;
      countEl.textContent = `(${approvals.length})`;

      if (approvals.length === 0) {
        container.innerHTML = `
          <div class="approval-card">
            <div class="approval-header">
              <span class="approval-title">暂无待审批任务</span>
              <span class="approval-badge">0</span>
            </div>
            <div style="font-size:13px;color:#9ca3af;padding:8px 0;">
              所有采购任务已处理完毕 ✓
            </div>
          </div>`;
        return;
      }

      // 渲染审批列表
      container.innerHTML = approvals.map(item => `
        <div class="approval-card">
          <div class="approval-header">
            <span class="approval-title">${item.title || '采购审批'}</span>
            <span class="approval-badge">${getPriorityLabel(item.priority)}</span>
          </div>
          <div class="approval-item">
            <div class="approval-icon icon-po">&#128722;</div>
            <div class="approval-info">
              <div class="approval-sku">${item.sku || item.description || '商品采购'}</div>
              <div class="approval-meta">
                数量: ${item.qty || '?'} | 申请人: ${item.requester || '系统AI'}
                | ${formatTime(item.created_at)}
              </div>
            </div>
            <div class="approval-action">
              <button class="btn-approve-sm" onclick="handleApprove('${item.task_id || item.id}')">审批</button>
            </div>
          </div>
        </div>
      `).join('');
    })
    .catch(err => {
      console.error('Approval list load error:', err);
      document.getElementById('approvalList').innerHTML =
        '<div class="empty-state"><div class="icon">&#9888;</div>加载失败</div>';
    });
}

function getPriorityLabel(priority) {
  const map = { high: '紧急', medium: '普通', low: '低' };
  return map[priority] || priority || '普通';
}

function handleApprove(taskId) {
  if (!confirm('确认审批此采购任务？\n\n这将创建正式采购订单。')) return;

  fetch(`${API_BASE}/tasks/${taskId}/approve-purchase`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ approved_by: 'store_manager', comment: '店长审批通过' })
  })
  .then(r => r.json())
  .then(d => {
    if (d.code === 0 || d.data) {
      alert('✅ 审批成功！采购订单已创建。');
      loadApprovalList(); // 刷新列表
      loadDashboard(); // 刷新Dashboard
    } else {
      alert('❌ 审批失败: ' + (d.detail || d.msg || '未知错误'));
    }
  })
  .catch(err => {
    alert('❌ 请求失败: ' + err.message);
  });
}

function initCurrentPage() {
  const path = window.location.pathname;
  if (path.includes('dashboard')) loadDashboard();
  else if (path.includes('kitchen')) loadKitchenPanel();
  else if (path.includes('purchase-assistant')) loadPurchasePanel();
  else if (path.includes('supplier-portal')) loadSupplierPortal();
}

// ====== Init ======

document.addEventListener('DOMContentLoaded', () => {
  initCurrentPage();
});
