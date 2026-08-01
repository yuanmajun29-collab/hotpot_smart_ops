/**
 * 火瞳 · Edge UI — 收货质检前端逻辑 (D1-S02)
 *
 * 功能:
 *  - 收货记录列表/搜索/分页
 *  - 新建收货单（含品项动态编辑）
 *  - 收货详情展示
 *  - VLM质检触发
 *  - 潘厨审批操作（通过/部分通过/拒收/退回）
 *  - Demo数据加载
 */

// ============================================================
// 全局状态
// ============================================================
const API_BASE = '/api/v1';
let currentPage = 1;
let pageSize = 20;
let currentRecordId = null; // 当前查看的收货单ID

// ============================================================
// API 调用封装
// ============================================================

async function apiCall(method, path, data = null) {
    const options = {
        method: method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }
    try {
        const resp = await fetch(API_BASE + path, options);
        const result = await resp.json();
        if (!result.success) {
            throw new Error(result.detail || '请求失败');
        }
        return result.data;
    } catch (err) {
        console.error('API Error:', err);
        showToast(err.message || '网络错误', 'error');
        throw err;
    }
}

function showToast(message, type = 'info') {
    // 简单提示（可后续替换为toast组件）
    alert(`[${type.toUpperCase()}] ${message}`);
}

// ============================================================
// 列表页功能
// ============================================================

async function loadStats() {
    try {
        const stats = await apiCall('GET', '/receiving/stats');
        document.getElementById('stat-today').textContent = stats.today?.total_records || 0;
        document.getElementById('stat-passed').textContent = stats.today?.passed || 0;
        document.getElementById('stat-partial').textContent = stats.today?.partial || 0;
        document.getElementById('stat-rejected').textContent = stats.today?.rejected || 0;
        const rate = stats.today?.pass_rate ? (stats.today.pass_rate * 100).toFixed(0) : 0;
        document.getElementById('stat-rate').textContent = rate + '%';
    } catch (e) { /* 静默失败 */ }
}

async function loadRecords() {
    try {
        const status = document.getElementById('filter-status').value;
        const keyword = document.getElementById('search-input')?.value || '';
        const params = new URLSearchParams({
            page: currentPage,
            page_size: pageSize,
            ...(status ? { status } : {}),
            ...(keyword ? { supplier_name: keyword } : {}),
        });
        const data = await apiCall('GET', `/receiving/records?${params}`);
        renderTable(data.items || []);
        renderPagination(data.total || 0, data.page || 1, data.page_size || 20);
    } catch (e) { /* 已在apiCall中处理 */ }
}

function renderTable(records) {
    const tbody = document.getElementById('records-tbody');
    if (!records.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state"><div class="icon">📦</div>暂无收货记录<br><button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="showCreateModal()">新建收货单</button></td></tr>`;
        return;
    }

    tbody.innerHTML = records.map(r => {
        const statusClass = `status-${r.status}`;
        const timeStr = r.received_at ? formatTime(r.received_at) : '-';
        // 计算最高等级
        let gradeHtml = '-';
        if (r.quality_results && r.quality_results.length > 0) {
            const grades = r.quality_results.map(q => q.grade);
            const worstGrade = grades.includes('D') ? 'D' : grades.includes('C') ? 'C' : grades.includes('B') ? 'B' : 'A';
            gradeHtml = `<span class="grade-badge grade-${worstGrade}">${worstGrade}</span>`;
        }

        return `<tr>
            <td><span class="record-id" onclick="goDetail('${r.record_id}')">${r.record_id}</span></td>
            <td><span class="supplier-name">${r.supplier_name}</span></td>
            <td>${r.receiver || '-'}</td>
            <td><span class="item-count">${r.items?.length || 0} 项</span></td>
            <td><span class="status-badge ${statusClass}">${formatStatus(r.status)}</span></td>
            <td>${gradeHtml}</td>
            <td><span class="time-ago">${timeStr}</span></td>
            <td>
                <button class="btn btn-secondary btn-sm" onclick="goDetail('${r.record_id}')">查看</button>
                ${r.status === 'draft' ? `<button class="btn btn-primary btn-sm" onclick="submitInspection('${r.record_id}')">提交质检</button>` : ''}
                ${r.status === 'pending_approval' ? `<button class="btn btn-warning btn-sm" onclick="goDetail('${r.record_id}')">审批</button>` : ''}
            </td>
        </tr>`;
    }).join('');
}

function renderPagination(total, page, size) {
    const totalPages = Math.ceil(total / size);
    document.getElementById('pagination-info').textContent = `共 ${total} 条记录，第 ${page}/${totalPages} 页`;

    let html = '';
    html += `<button class="page-btn" onclick="goPage(${page-1})" ${page <= 1 ? 'disabled' : ''}>上一页</button>`;
    for (let i = Math.max(1, page-2); i <= Math.min(totalPages, page+2); i++) {
        html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
    }
    html += `<button class="page-btn" onclick="goPage(${page+1})" ${page >= totalPages ? 'disabled' : ''}>下一页</button>`;
    document.getElementById('pagination-btns').innerHTML = html;
}

function goPage(page) { currentPage = page; loadRecords(); }
function onSearch() { currentPage = 1; loadRecords(); }
function goDetail(id) { window.location.href = `/receiving-detail.html?id=${id}`; }

async function submitInspection(recordId) {
    if (!confirm('确认提交此收货单进入质检流程？')) return;
    try {
        await apiCall('POST', `/receiving/records/${recordId}/submit`);
        showToast('已提交质检', 'success');
        loadRecords();
    } catch (e) { /* 已处理 */ }
}

// ============================================================
// 新建收货弹窗
// ============================================================

let itemRowCount = 0;

function showCreateModal() {
    document.getElementById('create-modal').classList.add('show');
    document.getElementById('create-form').reset();
    document.getElementById('items-container').innerHTML = '';
    itemRowCount = 0;
    addItemRow(); // 默认添加一行
}

function hideCreateModal() {
    document.getElementById('create-modal').classList.remove('show');
}

function addItemRow() {
    itemRowCount++;
    const container = document.getElementById('items-container');
    const row = document.createElement('div');
    row.className = 'item-row';
    row.id = `item-row-${itemRowCount}`;
    row.innerHTML = `
        <input type="text" placeholder="SKU编码" data-field="sku" list="sku-list" required title="输入SKU编码，如 FP-MW-001">
        <input type="text" placeholder="品名(自动)" data-field="sku_name" readonly style="background:#f5f5f5;">
        <input type="number" placeholder="订单量" data-field="ordered_qty" step="0.1" min="0" required>
        <input type="number" placeholder="实收量" data-field="received_qty" step="0.1" min="0" required>
        <select data-field="unit">
            <option value="kg">kg</option><option value="件">件</option><option value="盒">盒</option><option value="份">份</option>
        </select>
        <button type="button" class="remove-item-btn" onclick="removeItemRow(${itemRowCount})">×</button>
    `;
    container.appendChild(row);

    // SKU输入时自动填充品名
    row.querySelector('[data-field="sku"]').addEventListener('change', async function() {
        const sku = this.value.trim().toUpperCase();
        if (sku) {
            try {
                const data = await apiCall('GET', `/products/${sku}`);
                row.querySelector('[data-field="sku_name"]').value = data.name || '';
            } catch (e) {
                row.querySelector('[data-field="sku_name"]').value = '(未找到)';
            }
        }
    });
}

function removeItemRow(id) {
    const row = document.getElementById(`item-row-${id}`);
    if (row) row.remove();
}

async function submitReceiving() {
    const supplier = document.getElementById('frm-supplier').value.trim();
    const receiver = document.getElementById('frm-receiver').value.trim();
    if (!supplier || !receiver) { showToast('请填写必填项', 'error'); return; }

    // 收集品项数据
    const items = [];
    const rows = document.querySelectorAll('#items-container .item-row');
    for (const row of rows) {
        const sku = row.querySelector('[data-field="sku"]').value.trim().toUpperCase();
        const orderedQty = parseFloat(row.querySelector('[data-field="ordered_qty"]').value) || 0;
        const receivedQty = parseFloat(row.querySelector('[data-field="received_qty"]').value) || 0;
        const unit = row.querySelector('[data-field="unit"]').value;
        if (!sku || receivedQty <= 0) continue;
        items.push({ sku, ordered_qty: orderedQty, received_qty: receivedQty, unit });
    }

    if (items.length === 0) { showToast('请至少添加一个有效品项', 'error'); return; }

    try {
        const result = await apiCall('POST', '/receiving/records', {
            supplier_name: supplier,
            po_number: document.getElementById('frm-po').value.trim() || null,
            receiver: receiver,
            notes: document.getElementById('frm-notes').value.trim() || null,
            items: items,
        });

        showToast(`收货单创建成功: ${result.record?.record_id}`, 'success');
        hideCreateModal();
        loadRecords();
        loadStats();

        // 可选：自动跳转到详情页
        // goDetail(result.record?.record_id);
    } catch (e) { /* 已处理 */ }
}

// ============================================================
// 详情页功能
// ============================================================

async function loadDetail(recordId) {
    currentRecordId = recordId;
    try {
        const detail = await apiCall('GET', `/receiving/records/${recordId}`);
        renderDetail(detail);
    } catch (e) {
        document.querySelector('.detail-container').innerHTML =
            `<p style="text-align:center;padding:40px;color:#dc3545;">❌ 加载失败: ${e.message}<br><a href="/receiving.html">返回列表</a></p>`;
    }
}

function renderDetail(d) {
    // 头部信息
    document.getElementById('detail-record-id').textContent = d.record_id || '-';
    document.getElementById('detail-supplier').textContent = d.supplier_name || '-';
    document.getElementById('detail-receiver').textContent = d.receiver || '-';
    document.getElementById('detail-po').textContent = d.po_number || '(无)';
    document.getElementById('detail-time').textContent = d.received_at ? formatTime(d.received_at) : '-';

    // 状态徽章
    const statusEl = document.getElementById('detail-status');
    statusEl.textContent = formatStatus(d.status);
    statusEl.className = `status-badge status-${d.status}`;

    // 品项表格
    const itemsTbody = document.getElementById('items-tbody');
    if (d.items && d.items.length > 0) {
        itemsTbody.innerHTML = d.items.map(item => {
            const variance = item.ordered_qty > 0 ?
                ((item.ordered_qty - item.received_qty) / item.ordered_qty * 100).toFixed(1) : 0;
            const varianceClass = Math.abs(variance) > 15 ? 'variance-danger' :
                                   Math.abs(variance) > 7 ? 'variance-warning' : 'variance-normal';
            const varianceSign = variance >= 0 ? '' : '+';

            return `<tr>
                <td><span class="sku-code">${item.sku}</span></td>
                <td>${item.sku_name || '-'}</td>
                <td>${item.ordered_qty} ${item.unit}</td>
                <td>${item.received_qty} ${item.unit}</td>
                <td class="${varianceClass}">${varianceSign}${variance}%</td>
                <td>${item.temperature_on_arrival !== null && item.temperature_on_arrival !== undefined ? item.temperature_on_arrival + '°C' : '-'}</td>
            </tr>`;
        }).join('');
    } else {
        itemsTbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#999;">暂无品项</td></tr>';
    }

    // 照片
    const photosSection = document.getElementById('photos-section');
    const photosGrid = document.getElementById('photos-grid');
    if (d.photos && d.photos.length > 0) {
        photosSection.style.display = 'block';
        photosGrid.innerHTML = d.photos.map((photo, idx) => {
            const [type, url] = photo.split(':');
            const typeLabels = { overview: '全景', item_detail: '特写', weight_scale: '称重', defect: '缺陷', package_label: '标签' };
            return `<div class="photo-thumb" onclick="previewPhoto('${url}')">
                <div class="photo-placeholder">📷</div>
                <span class="photo-type-tag">${typeLabels[type] || type}</span>
            </div>`;
        }).join('');
    } else {
        photosSection.style.display = 'none';
    }

    // VLM质检结果
    const qualitySection = document.getElementById('quality-section');
    const qualityResults = document.getElementById('quality-results');
    if (d.quality_results && d.quality_results.length > 0) {
        qualitySection.style.display = 'block';
        qualityResults.innerHTML = d.quality_results.map(qr => {
            const defectsHtml = qr.visual_defects && qr.visual_defects.length > 0 ?
                `<ul class="defect-list">${qr.visual_defects.map(d => `<li>${d}</li>`).join('')}</ul>` : '';

            return `<div class="vlm-result-card grade-${qr.grade}">
                <div class="result-header">
                    <span class="result-sku">${qr.sku} ${qr.sku !== (d.items.find(i=>i.sku===qr.sku)?.sku_name) ? '' : '(' + (d.items.find(i=>i.sku===qr.sku)?.sku_name) + ')' : ''}</span>
                    <span class="grade-badge grade-${qr.grade}">${qr.grade}</span>
                </div>
                <div style="font-size:13px;color:#555;">
                    ${qr.passed ? '✅ 通过' : '❌ 未通过'}
                    ${qr.weight_variance_pct !== null ? ` | 短重: ${qr.weight_variance_pct}%` : ''}
                    ${qr.temperature_ok === false ? ' | 🌡️ 温度异常' : qr.temperature_ok === true ? ' | 🌡️ 温度正常' : ''}
                    ${qr.vlm_analysis?.mock ? ' | 🤖 Mock模式' : ' | 🤖 VLM分析'}
                    ${qr.confidence ? ` | 置信度: ${(qr.vlm_analysis?.confidence || 0)*100}%` : ''}
                </div>
                ${defectsHtml}
                ${qr.rejection_reason ? `<p style="color:#dc3545;font-size:13px;margin-top:8px;"><strong>拒收原因:</strong> ${qr.rejection_reason}</p>` : ''}
            </div>`;
        }).join('');
    } else {
        qualitySection.style.display = 'none';
    }

    // 审批区域 / 已完成信息
    const approvalSection = document.getElementById('approval-section');
    const completedSection = document.getElementById('completed-section');

    if (d.status === 'pending_approval') {
        approvalSection.style.display = 'block';
        completedSection.style.display = 'none';
    } else if (['approved', 'partial', 'rejected'].includes(d.status)) {
        approvalSection.style.display = 'none';
        completedSection.style.display = 'block';
        completedSection.innerHTML = `
            <h3 class="section-title">📋 审批记录</h3>
            <p><strong>审批结果:</strong> <span class="status-badge status-${d.status}">${formatStatus(d.status)}</span></p>
            <p><strong>审批人:</strong> ${d.approved_by || '-'}</p>
            <p><strong>审批时间:</strong> ${d.approved_at ? formatTime(d.approved_at) : '-'}</p>
            ${d.notes ? `<p><strong>备注:</strong> ${d.notes.replace(/\[.*?\]\s*/g, '')}</p>` : ''}
        `;
    } else {
        approvalSection.style.display = 'none';
        completedSection.style.display = 'none';
    }
}

// ============================================================
// 审批操作
// ============================================================

async function doApprove() {
    if (!currentRecordId) return;
    const notes = document.getElementById('approval-notes').value.trim();
    try {
        await apiCall('POST', `/receiving/records/${currentRecordId}/approve`, { notes: notes || null });
        showToast('✅ 已审批通过', 'success');
        loadDetail(currentRecordId);
    } catch (e) { /* 已处理 */ }
}

async function doPartial() {
    if (!currentRecordId) return;
    const notes = document.getElementById('approval-notes').value.trim() || '部分品项存在品质问题，已关注';
    try {
        await apiCall('POST', `/receiving/records/${currentRecordId}/partial`, { notes });
        showToast('⚠️ 已标记为部分通过', 'success');
        loadDetail(currentRecordId);
    } catch (e) { /* 已处理 */ }
}

function showRejectConfirm() {
    document.getElementById('reject-modal').classList.add('show');
    document.getElementById('reject-reason').value = '';
    document.getElementById('reject-reason').focus();
}

function hideRejectModal() {
    document.getElementById('reject-modal').classList.remove('show');
}

async function doReject() {
    if (!currentRecordId) return;
    const reason = document.getElementById('reject-reason').value.trim();
    if (!reason) { showToast('请填写拒收原因', 'error'); return; }
    hideRejectModal();
    try {
        await apiCall('POST', `/receiving/records/${currentRecordId}/reject`, { reason });
        showToast('❌ 已整批拒收', 'success');
        loadDetail(currentRecordId);
    } catch (e) { /* 已处理 */ }
}

async function doReturn() {
    if (!currentRecordId) return;
    const reason = prompt('请输入退回修改原因：');
    if (!reason) return;
    try {
        await apiCall('POST', `/receiving/records/${currentRecordId}/return`, { reason });
        showToast('🔙 已退回修改', 'success');
        loadDetail(currentRecordId);
    } catch (e) { /* 已处理 */ }
}

// 触发VLM质检（从详情页调用）
async function triggerInspection() {
    if (!currentRecordId) return;
    if (!confirm('确认执行VLM视觉质检？\n(MVP阶段使用Mock模式)')) return;
    try {
        showToast('正在执行VLM分析...', 'info');
        const result = await apiCall('POST', `/receiving/records/${currentRecordId}/inspect`);
        showToast(`质检完成: ${result.quality_count}项，整体${result.total_passed ? '通过' : '存在问题'}`, result.total_passed ? 'success' : 'warning');
        loadDetail(currentRecordId);
    } catch (e) { /* 已处理 */ }
}

// ============================================================
// 工具函数
// ============================================================

function formatStatus(status) {
    const map = {
        draft: '草稿',
        pending: '待质检',
        inspecting: '🔄 质检中',
        pending_approval: '⏳ 待审批',
        approved: '✅ 已通过',
        partial: '⚠️ 部分通过',
        rejected: '❌ 已拒收',
    };
    return map[status] || status;
}

function formatTime(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function previewPhoto(url) {
    window.open(url, '_blank');
}

// ============================================================
// Demo 数据
// ============================================================

async function loadDemoData() {
    if (!confirm('确定要加载展会Demo收货数据吗？\n包含3种典型场景：正常/部分通过/拒收')) return;
    try {
        const result = await apiCall('POST', '/receiving/seed-demo');
        showToast(result.message || 'Demo数据加载完成', 'success');
        loadRecords();
        loadStats();
    } catch (e) { /* 已处理 */ }
}

// ============================================================
// 页面初始化
// ============================================================

// 仅列表页需要初始化
if (document.getElementById('stats-row')) {
    document.addEventListener('DOMContentLoaded', function() {
        loadStats();
        loadRecords();
    });
}
