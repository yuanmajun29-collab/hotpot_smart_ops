/**
 * 火瞳 · 采购订单管理 - 前端逻辑 (D1-S03)
 *
 * 覆盖页面:
 *   purchase-order.html       — 列表页
 *   purchase-order-detail.html — 详情/操作页
 */

// ============================================================
// 工具函数
// ============================================================

const API_BASE = '/api/v1';

async function apiCall(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, opts);
  const data = await res.json();
  if (!res.ok && data.detail) throw new Error(data.detail);
  return data;
}

function formatStatus(status) {
  const map = {
    draft: ['草稿', 'badge-draft'],
    submitted: ['待确认', 'badge-submitted'],
    confirmed: ['已确认待收货', 'badge-confirmed'],
    partial: ['部分收货', 'badge-partial'],
    received: ['已收货', 'badge-received'],
    cancelled: ['已取消', 'badge-cancelled'],
  };
  const [label, cls] = map[status] || [status, ''];
  return `<span class="badge ${cls}">${label}</span>`;
}

function formatTime(dt) {
  if (!dt) return '-';
  const d = new Date(dt);
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function formatAmount(n) {
  return '¥' + (n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 });
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ============================================================
// 列表页逻辑 (purchase-order.html)
// ============================================================

let currentPage = 1;
const PAGE_SIZE = 20;

async function loadStats() {
  try {
    const res = await apiCall('GET', '/purchase-orders/stats');
    const d = res.data;
    document.getElementById('statToday').textContent = d.today_orders;
    document.getElementById('statWeek').textContent = d.week_orders;
    document.getElementById('statPending').textContent = d.pending_receive;
    document.getElementById('statTodayAmt').textContent = formatAmount(d.total_amount_today);
    document.getElementById('statWeekAmt').textContent = formatAmount(d.total_amount_week);

    // 完成率
    const total = (d.status_breakdown.received || 0) + (d.status_breakdown.partial || 0) +
                  (d.status_breakdown.confirmed || 0) + (d.status_breakdown.submitted || 0);
    const done = (d.status_breakdown.received || 0) + (d.status_breakdown.partial || 0);
    const rate = total > 0 ? Math.round(done / total * 100) : 100;
    document.getElementById('statReceiveRate').textContent = rate + '%';
  } catch (e) {
    console.error('加载统计失败:', e);
  }
}

async function loadRecords() {
  try {
    const status = document.getElementById('filterStatus').value;
    const search = document.getElementById('searchInput').value;

    let url = `/purchase-orders?page=${currentPage}&page_size=${PAGE_SIZE}`;
    if (status) url += `&status=${status}`;
    // supplier筛选复用search字段(模糊匹配供应商名)
    if (search) url += `&supplier=${encodeURIComponent(search)}`;

    const res = await apiCall('GET', url);
    renderTable(res.data.items);
    renderPagination(res.data.total, res.data.page_size, res.data.page);
  } catch (e) {
    console.error('加载订单列表失败:', e);
    document.getElementById('tableBody').innerHTML =
      `<tr><td colspan="7" style="text-align:center;color:#999;padding:30px;">加载失败: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderTable(items) {
  const tbody = document.getElementById('tableBody');
  if (!items || items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999;padding:30px;">暂无订单数据</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(o => `
    <tr>
      <td><a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" style="color:#4a6cf7;font-weight:600;text-decoration:none;">${escapeHtml(o.po_number)}</a></td>
      <td>${escapeHtml(o.supplier || '-')}</td>
      <td style="font-weight:600;">${formatAmount(o.total_amount)}</td>
      <td>${formatStatus(o.status)}</td>
      <td>${escapeHtml(o.ordered_by || '-')}</td>
      <td style="color:#888;font-size:12px;">${formatTime(o.ordered_at)}</td>
      <td class="action-btns">${renderRowActions(o)}</td>
    </tr>
  `).join('');
}

function renderRowActions(o) {
  let html = '';
  switch (o.status) {
    case 'draft':
      html += `<a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" class="btn-info">详情</a> `;
      break;
    case 'submitted':
      html += `<a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" class="btn-primary">确认</a> `;
      break;
    case 'confirmed':
      html += `<a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" class="btn-success">标记收货</a> `;
      break;
    case 'partial':
    case 'received':
      html += `<a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" class="btn-info">详情</a> `;
      break;
    default:
      html += `<a href="purchase-order-detail.html?po_number=${encodeURIComponent(o.po_number)}" class="btn-secondary">详情</a> `;
  }
  return html;
}

function renderPagination(total, pageSize, page) {
  const container = document.getElementById('pagination');
  const totalPages = Math.ceil(total / pageSize) || 1;
  let html = '';
  html += `<button ${page <= 1 ? 'disabled' : ''} onclick="goPage(${page-1})">‹</button>`;
  for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
    html += `<button ${i === page ? 'disabled' : ''} onclick="goPage(${i})">${i}</button>`;
  }
  html += `<button ${page >= totalPages ? 'disabled' : ''} onclick="goPage(${page+1})">›</button>`;
  html += `<span> 共 ${total} 条 / ${totalPages} 页</span>`;
  container.innerHTML = html;
}

function goPage(p) {
  currentPage = p;
  loadRecords();
}

// ── 新建弹窗 ──

let itemRowCount = 0;

function showCreateModal() {
  document.getElementById('createModal').classList.add('active');
  document.getElementById('itemRows').innerHTML = '';
  addItemRow();
  updateTotal();
}

function hideCreateModal() {
  document.getElementById('createModal').classList.remove('active');
}

function addItemRow() {
  itemRowCount++;
  const div = document.createElement('div');
  div.className = 'item-row';
  div.id = `itemRow${itemRowCount}`;
  div.innerHTML = `
    <select onchange="onSkuSelect(this, ${itemRowCount})">
      <option value="">-- 选择SKU --</option>
    </select>
    <input type="number" placeholder="数量" min="0.1" step="0.5" value="1" onchange="updateTotal()">
    <input type="number" placeholder="单价" min="0" step="0.01" readonly id="price${itemRowCount}" style="background:#f8f9fa;">
    <span id="subtotal${itemRowCount}" style="font-weight:600;font-size:13px;">¥0.00</span>
    <button onclick="removeItemRow(${itemRowCount})" style="padding:4px 8px;border:1px solid #ddd;border-radius:4px;background:#fff;cursor:pointer;font-size:16px;color:#dc3545;" title="删除">×</button>
  `;
  document.getElementById('itemRows').appendChild(div);
  loadSKUs(div.querySelector('select'));
}

function removeItemRow(id) {
  const el = document.getElementById(`itemRow${id}`);
  if (el) { el.remove(); updateTotal(); }
}

/** 加载SKU下拉选项 */
async function loadSKUs(selectEl) {
  try {
    const res = await apiCall('GET', '/products?page=1&page_size=200');
    const products = res.data?.items || [];
    selectEl.innerHTML = '<option value="">-- 选择SKU --</option>' +
      products.map(p => `<option value="${p.sku_code}" data-name="${escapeHtml(p.name)}" data-price="${p.unit_price}" data-unit="${p.unit}">
        ${escapeHtml(p.sku_code)} | ${escapeHtml(p.name)} (${formatAmount(p.unit_price)})
      </option>`).join('');
  } catch (e) {
    console.error('加载SKU失败:', e);
  }
}

function onSkuSelect(selectEl, rowId) {
  const opt = selectEl.selectedOptions[0];
  if (!opt || !opt.value) return;
  const price = parseFloat(opt.dataset.price) || 0;
  document.getElementById(`price${rowId}`).value = price.toFixed(2);
  updateTotal();
}

function updateTotal() {
  let total = 0;
  document.querySelectorAll('.item-row').forEach(row => {
    const qty = parseFloat(row.querySelector('input[type="number"]')?.value) || 0;
    const priceInput = row.querySelectorAll('input[type="number"]')[1];
    const price = parseFloat(priceInput?.value) || 0;
    const subtotal = qty * price;
    total += subtotal;
    const subEl = row.id ? document.getElementById(`subtotal${row.id.replace('itemRow','')}`) : null;
    if (subEl) subEl.textContent = formatAmount(subtotal);
  });
  document.getElementById('totalAmountDisplay').textContent = '合计: ' + formatAmount(total);
}

async function submitPO() {
  const supplier = document.getElementById('poSupplier').value.trim();
  if (!supplier) { alert('请填写供应商'); return; }

  const items = [];
  let hasItem = false;
  document.querySelectorAll('.item-row').forEach(row => {
    const sel = row.querySelector('select');
    if (sel && sel.value) {
      hasItem = true;
      items.push({
        sku: sel.value,
        quantity: parseFloat(row.querySelector('input[type="number"]').value) || 0,
        unit_price: parseFloat(row.querySelectorAll('input[type="number"]')[1]?.value),
      });
    }
  });

  if (!hasItem) { alert('请至少添加一个行项目'); return; }

  try {
    const res = await apiCall('POST', '/purchase-orders', {
      supplier,
      delivery_address: document.getElementById('poAddress').value.trim(),
      expected_date: document.getElementById('poExpectedDate').value || null,
      notes: document.getElementById('poNotes').value.trim() || null,
      items,
    });
    alert('✅ 订单创建成功: ' + res.data.po_number);
    hideCreateModal();
    loadRecords();
    loadStats();
  } catch (e) {
    alert('❌ 创建失败: ' + e.message);
  }
}

async function loadDemoData() {
  if (!confirm('确定要加载Demo数据吗？将创建4条示例订单。')) return;
  try {
    const res = await apiCall('POST', '/purchase-orders/seed-demo');
    alert(res.message);
    loadRecords();
    loadStats();
  } catch (e) {
    alert('加载失败: ' + e.message);
  }
}

// 列表页初始化
if (document.getElementById('statsGrid')) {
  loadStats();
  loadRecords();
}


// ============================================================
// 详情页逻辑 (purchase-order-detail.html)
// ============================================================

let currentPO = null;

async function loadDetail(poNumber) {
  try {
    const res = await apiCall('GET', `/purchase-orders/${poNumber}`);
    currentPO = res.data;
    renderDetail(currentPO);
    loadReceivingLinks(poNumber);
  } catch (e) {
    document.getElementById('poNumber').textContent = '加载失败: ' + e.message;
  }
}

function renderDetail(po) {
  // 头部
  document.getElementById('poNumber').textContent = po.po_number;
  const sb = document.getElementById('statusBadge');
  sb.textContent = '';
  sb.outerHTML = formatStatus(po.status); // replace with badge HTML

  const fields = [
    ['供应商', po.supplier || '-'],
    ['下单人', po.ordered_by || '-'],
    ['下单时间', formatTime(po.ordered_at)],
    ['送货地址', po.delivery_address || '-'],
    ['期望到货', po.expected_date || '-'],
    ['确认人', po.confirmed_by || (po.status === 'submitted' ? '待确认' : '-')],
    ['确认时间', formatTime(po.confirmed_at)],
    ['收货完成', formatTime(po.received_at)],
    ['备注', po.notes || '-'],
  ];
  document.getElementById('ohGrid').innerHTML = fields.map(([label, val]) =>
    `<div class="oh-field"><span class="label">${label}</span><span class="value">${escapeHtml(String(val))}</span></div>`
  ).join('');

  // 行项目表格
  const tbody = document.getElementById('itemsBody');
  tbody.innerHTML = (po.items || []).map(item => {
    const pct = item.quantity > 0 ? Math.min(100, (item.received_qty / item.quantity * 100)) : 0;
    const isFull = item.received_qty >= item.quantity;
    const hasRecv = item.received_qty > 0;
    const progressCls = isFull ? 'full' : hasRecv ? 'partial' : 'none';
    return `<tr>
      <td style="font-family:monospace;font-size:12px;">${escapeHtml(item.sku)}</td>
      <td>${escapeHtml(item.sku_name || '-')}</td>
      <td>${item.quantity} ${escapeHtml(item.unit || '')}</td>
      <td style="font-weight:600;${isFull ? 'color:#28a745;' : hasRecv ? 'color:#ffc107;' : ''}">${item.received_qty} ${escapeHtml(item.unit || '')}</td>
      <td>${formatAmount(item.unit_price)}</td>
      <td style="font-weight:600;">${formatAmount(item.amount)}</td>
      <td>
        <div class="progress-bar">
          <div class="progress-fill ${progressCls}" style="width:${pct}%"></div>
          <span class="progress-text">${Math.round(pct)}%</span>
        </div>
      </td>
    </tr>`;
  }).join('');

  // 操作按钮
  renderActions(po);
}

function renderActions(po) {
  const zone = document.getElementById('actionZone');
  const btns = document.getElementById('actionBtns');

  const terminalStates = ['received', 'cancelled'];

  if (terminalStates.includes(po.status)) {
    zone.style.background = po.status === 'received'
      ? 'linear-gradient(135deg, #28a745 0%, #20c997 100%)'
      : 'linear-gradient(135deg, #6c757d 0%, #adb5bd 100%)';
    btns.innerHTML = `<div class="terminal-state">
      <div class="terminal-icon">${po.status === 'received' ? '✅' : '🚫'}</div>
      <div>${po.status === 'received' ? '订单已完成全部收货流程' : '订单已取消'}</div>
    </div>`;
    return;
  }

  zone.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
  let html = '';

  switch (po.status) {
    case 'draft':
      html += `<button class="btn-submit" onclick="doSubmit()">提交确认</button> `;
      html += `<button class="btn-delete" onclick="showCancelModal()">删除</button> `;
      break;
    case 'submitted':
      html += `<button class="btn-confirm" onclick="doConfirm()">审批通过</button> `;
      html += `<button class="btn-return" onclick="doReturnDraft()">退回草稿</button> `;
      html += `<button class="btn-cancel-po" onclick="showCancelModal()">取消订单</button> `;
      break;
    case 'confirmed':
      html += `<button class="btn-receive" onclick="doMarkReceived()">标记已收货</button> `;
      html += `<button class="btn-cancel-po" onclick="showCancelModal()">取消订单</button> `;
      break;
    case 'partial':
      html += `<button class="btn-receive" onclick="doMarkReceived()">标记收齐</button> `;
      break;
  }

  btns.innerHTML = html;
}

// ── 操作函数 ──

async function doSubmit() {
  if (!currentPO) return;
  try {
    const res = await apiCall('POST', `/purchase-orders/${currentPO.po_number}/submit`);
    currentPO = res.data;
    renderDetail(currentPO);
    alert('✅ 已提交，等待确认');
  } catch (e) { alert('❌ ' + e.message); }
}

async function doConfirm() {
  if (!currentPO) return;
  try {
    const res = await apiCall('POST', `/purchase-orders/${currentPO.po_number}/confirm`, { notes: '' });
    currentPO = res.data;
    renderDetail(currentPO);
    alert('✅ 审批通过，订单已确认');
  } catch (e) { alert('❌ ' + e.message); }
}

async function doReturnDraft() {
  if (!currentPO) return;
  if (!confirm('确定退回草稿状态吗？')) return;
  try {
    const res = await apiCall('POST', `/purchase-orders/${currentPO.po_number}/return-draft`);
    currentPO = res.data;
    renderDetail(currentPO);
    alert('✅ 已退回草稿');
  } catch (e) { alert('❌ ' + e.message); }
}

async function doMarkReceived() {
  if (!currentPO) return;
  if (!confirm('确定标记此订单为已全部收货吗？')) return;
  try {
    const res = await apiCall('POST', `/purchase-orders/${currentPO.po_number}/mark-received`);
    currentPO = res.data;
    renderDetail(currentPO);
    alert('✅ 已标记为收货完成');
  } catch (e) { alert('❌ ' + e.message); }
}

function showCancelModal() {
  document.getElementById('cancelReason').value = '';
  document.getElementById('cancelModal').classList.add('active');
}

function hideCancelModal() {
  document.getElementById('cancelModal').classList.remove('active');
}

async function doCancel() {
  if (!currentPO) return;
  const reason = document.getElementById('cancelReason').value.trim();
  if (!reason) { alert('请输入取消原因'); return; }

  try {
    const res = await apiCall('POST', `/purchase-orders/${currentPO.po_number}/cancel`, { reason });
    hideCancelModal();
    currentPO = res.data;
    renderDetail(currentPO);
    alert('✅ 订单已取消');
  } catch (e) { alert('❌ ' + e.message); }
}

// ── 关联收货记录 ──

async function loadReceivingLinks(poNumber) {
  try {
    const res = await apiCall('GET', `/purchase-orders/${poNumber}/receiving`);
    const section = document.getElementById('receivingSection');
    const list = document.getElementById('receivingList');

    if (res.data && res.data.length > 0) {
      section.style.display = 'block';
      list.innerHTML = res.data.map(r => {
        let statusClass = 'rl-passed';
        let statusText = '✅ 通过';
        if (r.status === 'partial') { statusClass = 'rl-partial'; statusText = '⚠️ 部分通过'; }
        else if (r.status === 'rejected') { statusClass = 'rl-rejected'; statusText = '❌ 已拒收'; }
        return `<a class="receiving-link" href="receiving-detail.html?record_id=${r.record_id}">
          <strong>${escapeHtml(r.record_id)}</strong>
          <span class="rl-status ${statusClass}">${statusText}</span>
          <div style="font-size:11px;color:#888;margin-top:3px;">
            收货人: ${escapeHtml(r.receiver)} | 时间: ${formatTime(r.received_at)}
            ${(r.items||[]).length}项品项
          </div>
        </a>`;
      }).join('');
    } else {
      section.style.display = 'none';
    }
  } catch (e) {
    console.error('加载关联收货记录失败:', e);
  }
}
