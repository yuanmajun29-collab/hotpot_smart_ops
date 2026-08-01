/**
 * D1-S04 供应商协同与评分 — 前端交互逻辑
 *
 * 覆盖页面:
 *   supplier.html        — 列表页（统计+表格+新建）
 *   supplier-detail.html — 详情页（评分+趋势+操作区）
 */

const API_BASE = '/api/v1';

// ============================================================
// 工具函数
// ============================================================

function apiCall(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    return fetch(`${API_BASE}${path}`, opts)
        .then(r => r.json())
        .then(data => {
            if (data.code !== 0) throw new Error(data.detail || '请求失败');
            return data.data;
        });
}

function formatStatus(status) {
    const map = {
        active: { text: '活跃合作', cls: 'status-active', color: '#22c55e' },
        probation: { text: '观察期', cls: 'status-probation', color: '#f59e0b' },
        suspended: { text: '已停用', cls: 'status-suspended', color: '#f97316' },
        blacklisted: { text: '黑名单', cls: 'status-blacklisted', color: '#1f2937' },
        pending: { text: '待审核', cls: 'status-pending', color: '#9ca3af' },
    };
    const s = map[status] || { text: status, cls: '', color: '#6b7280' };
    return `<span class="status-dot ${s.cls}"></span>${s.text}`;
}

function formatGrade(grade) {
    if (!grade || grade === '-') return '<span style="color:#9ca3af">--</span>';
    const colors = { A: '#16a34a', B: '#4ade80', C: '#f59e0b', D: '#ef4444' };
    const c = colors[grade] || '#6b7280';
    return `<span class="grade-badge grade-${grade}">${grade}</span>`;
}

function formatScore(score) {
    if (score === null || score === undefined) return '--';
    const s = parseFloat(score);
    const cls = s >= 80 ? 'score-high' : s >= 60 ? 'score-mid' : 'score-low';
    const pct = Math.min(100, s);
    return `
        <span style="font-weight:600">${s.toFixed(1)}</span>
        <div class="score-bar" style="display:inline-block;vertical-align:middle;margin-left:6px">
            <div class="score-bar-fill ${cls}" style="width:${pct}%"></div>
        </div>`;
}

function formatTime(isoStr) {
    if (!isoStr) return '--';
    try {
        const d = new Date(isoStr);
        return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    } catch { return isoStr; }
}

function getQueryParam(key) {
    return new URLSearchParams(window.location.search).get(key);
}


// ============================================================
// 列表页 (supplier.html)
// ============================================================

let currentPage = 1;
const PAGE_SIZE = 15;

function loadStats() {
    apiCall('GET', '/suppliers/stats').then(stats => {
        document.getElementById('stat-total').querySelector('.stat-number').textContent = stats.total;
        document.getElementById('stat-active').querySelector('.stat-number').textContent = stats.active;
        document.getElementById('stat-probation').querySelector('.stat-number').textContent = stats.probation;
        document.getElementById('stat-suspended').querySelector('.stat-number').textContent = stats.suspended;
        document.getElementById('stat-blacklisted').querySelector('.stat-number').textContent = stats.blacklisted;
    }).catch(err => console.error('加载统计失败:', err));
}

function loadRecords() {
    const keyword = document.getElementById('search-input')?.value || '';
    const status = document.getElementById('filter-status')?.value || '';
    const grade = document.getElementById('filter-grade')?.value || '';

    const params = new URLSearchParams({
        page: currentPage, page_size: PAGE_SIZE,
        ...(keyword && { keyword }),
        ...(status && { status }),
        ...(grade && { grade }),
        sort_by: '-score_overall',
    });

    apiCall('GET', `/suppliers?${params}`).then(data => {
        renderTable(data.items, data.total);
        renderPagination(data.total, data.page, data.page_size);
    }).catch(err => console.error('加载列表失败:', err));
}

function renderTable(items, total) {
    const tbody = document.getElementById('supplier-tbody');
    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:#9ca3af;padding:40px">
            暂无供应商数据 <button class="btn btn-sm btn-primary" onclick="showCreateModal()" style="margin-left:10px">创建第一个</button></td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(s => {
        const scoreHtml = formatScore(s.score_overall);
        const gradeHtml = formatGrade(s.score_grade);
        const statusHtml = formatStatus(s.status);

        let actionBtn = '';
        if (s.status === 'pending') {
            actionBtn = `<a href="supplier-detail.html?id=${s.supplier_id}" class="btn btn-sm btn-success">激活</a>`;
        } else if (s.status === 'active' || s.status === 'probation') {
            actionBtn = `<a href="supplier-detail.html?id=${s.supplier_id}" class="btn btn-sm btn-primary">详情</a>`;
        } else if (s.status === 'suspended') {
            actionBtn = `<button class="btn btn-sm btn-outline" onclick="restoreSupplier('${s.supplier_id}')">恢复</button>`;
        } else {
            actionBtn = `<span style="color:#9ca3af;font-size:12px">--</span>`;
        }

        return `<tr>
            <td><strong>${s.name}</strong><br><small style="color:#9ca3af">${s.address || '--'}</small></td>
            <td>${s.contact_person || '--'}<br><small style="color:#9ca3af">${s.phone || ''}</small></td>
            <td>${statusHtml}</td>
            <td>${scoreHtml}</td>
            <td>${gradeHtml}</td>
            <td>${s.total_orders || 0}</td>
            <td>${s.on_time_rate != null ? s.on_time_rate.toFixed(1) + '%' : '--'}</td>
            <td style="${(s.reject_rate||0) > 10 ? 'color:#ef4444;font-weight:600' : ''}">
                ${s.reject_rate != null ? s.reject_rate.toFixed(1) + '%' : '--'}
            </td>
            <td>${actionBtn}</td>
        </tr>`;
    }).join('');
}

function renderPagination(total, page, pageSize) {
    const container = document.getElementById('pagination');
    const totalPages = Math.ceil(total / pageSize);
    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = `<button class="page-btn" ${page<=1?'disabled':''} onclick="goPage(${page-1})">上一页</button>`;
    for (let i=1; i<=totalPages; i++) {
        html += `<button class="page-btn ${i===page?'active':''}" onclick="goPage(${i})">${i}</button>`;
    }
    html += `<button class="page-btn" ${page>=totalPages?'disabled':''} onclick="goPage(${page+1})">下一页</button>`;
    container.innerHTML = html;
}

function goPage(p) { currentPage = p; loadRecords(); }

// 新建弹窗
function showCreateModal() {
    document.getElementById('create-modal').style.display = 'flex';
}
function closeCreateModal() {
    document.getElementById('create-modal').style.display = 'none';
    document.getElementById('create-form').reset();
}

async function submitSupplier(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    // 处理SKU文本
    if (data.supplied_skus_text) {
        data.supplied_skus = data.supplied_skus_text.split(',').map(s => s.trim()).filter(Boolean);
    }
    delete data.supplied_skus_text;

    // 日期转换
    if (data.contract_start === '') delete data.contract_start;
    if (data.contract_end === '') delete data.contract_end;

    try {
        await apiCall('POST', '/suppliers', data);
        closeCreateModal();
        loadRecords();
        loadStats();
        alert('✅ 供应商创建成功！初始状态为【待审核】，请点击"激活"后开始使用');
    } catch (err) {
        alert('❌ 创建失败: ' + err.message);
    }
}

async function loadDemoData() {
    if (!confirm('将加载5个Demo供应商数据（覆盖全部状态和等级），是否继续？')) return;
    try {
        const result = await apiCall('POST', '/suppliers/seed-demo');
        alert(`✅ ${result.message}`);
        loadRecords();
        loadStats();
    } catch (err) {
        alert('❌ 加载失败: ' + err.message);
    }
}

async function restoreSupplier(id) {
    if (!confirm('确认恢复该供应商？')) return;
    try {
        await apiCall('POST', `/suppliers/${id}/restore`);
        loadRecords();
        loadStats();
    } catch (err) {
        alert('操作失败: ' + err.message);
    }
}


// ============================================================
// 详情页 (supplier-detail.html)
// ============================================================

let currentSupplierId = null;
let currentSupplierData = null;

function loadDetail() {
    currentSupplierId = getQueryParam('id');
    if (!currentSupplierId) {
        document.querySelector('.app-container').innerHTML =
            '<p style="text-align:center;padding:60px;color:#9ca3af">缺少供应商ID参数</p>';
        return;
    }

    Promise.all([
        apiCall('GET', `/suppliers/${currentSupplierId}`),
        apiCall('GET', `/suppliers/${currentSupplierId}/score`),
        apiCall('GET', `/suppliers/${currentSupplierId}/orders`),
    ]).then(([supplier, score, orders]) => {
        currentSupplierData = supplier;
        renderDetail(supplier, score, orders);
    }).catch(err => {
        console.error('加载详情失败:', err);
        document.querySelector('.app-container').innerHTML =
            `<p style="text-align:center;padding:60px;color:#ef4444">加载失败: ${err.message}</p>`;
    });
}

function renderDetail(supplier, score, orders) {
    // 页面标题
    document.getElementById('page-title').textContent =
        `📦 ${supplier.name}`;

    // 基本信息
    document.getElementById('info-content').innerHTML = `
        <div class="info-row"><span class="info-label">供应商ID</span><span class="info-value">${supplier.supplier_id}</span></div>
        <div class="info-row"><span class="info-label">名称</span><span class="info-value"><strong>${supplier.name}</strong></span></div>
        <div class="info-row"><span class="info-label">联系人</span><span class="info-value">${supplier.contact_person || '--'}</span></div>
        <div class="info-row"><span class="info-label">电话</span><span class="info-value">${supplier.phone || '--'}</span></div>
        <div class="info-row"><span class="info-label">地址</span><span class="info-value">${supplier.address || '--'}</span></div>
        <div class="info-row"><span class="info-label">许可证号</span><span class="info-value">${supplier.license_no || '--'}</span></div>
        <div class="info-row"><span class="info-label">状态</span><span class="info-value">${formatStatus(supplier.status)}</span></div>
        <div class="info-row"><span class="info-label">合作期限</span><span class="info-value">
            ${(supplier.contract_start||'--')} ~ ${(supplier.contract_end||'--')}</span></div>
        <div class="info-row"><span class="info-label">供应SKU数</span><span class="info-value">
            ${(supplier.supplied_skus||[]).length} 个</span></div>
        <div class="info-row"><span class="info-label">累计订单</span><span class="info-value">${supplier.total_orders||0} 笔</span></div>
        <div class="info-row"><span class="info-label">备注</span><span class="info-value">${supplier.notes||'--'}</span></div>
    `;

    // 评分概览
    const cur = score.current;
    const hasScore = cur.overall !== null && cur.overall !== undefined;
    document.getElementById('score-content').innerHTML = hasScore ? `
        <div class="radar-placeholder">
            <div class="radar-center-text">
                <div class="radar-score-big">${cur.overall.toFixed(1)}</div>
                <div class="radar-grade-badge grade-${cur.grade}">${cur.grade}级</div>
                <small style="color:#9ca3af;margin-top:4px;display:block">综合评分</small>
            </div>
        </div>
        <div style="margin-top:14px">
            ${renderDimMiniBar('质量', cur.quality_score, 'dim-quality')}
            ${renderDimMiniBar('交付', cur.delivery_score, 'dim-delivery')}
            ${renderDimMiniBar('价格', cur.price_score, 'dim-price')}
            ${renderDimMiniBar('服务', cur.service_score, 'dim-service')}
        </div>
    ` : '<p style="text-align:center;color:#9ca3af;padding:30px">该供应商尚未激活，暂无评分数据</p>';

    // 维度明细
    if (hasScore) {
        document.getElementById('dimension-content').innerHTML = `
            <table style="width:100%;border-collapse:collapse">
                <thead><tr style="font-size:13px;color:#6b7280;text-align:left">
                    <th>维度</th><th>得分</th><th>权重</th><th>说明</th>
                </tr></thead>
                <tbody>
                    ${renderDimRow('质量 ★', cur.quality_score, '40%', '基于S02质检数据计算')}
                    ${renderDimRow('交付', cur.delivery_score, '25%', '基于S03订单准时率计算')}
                    ${renderDimRow('价格', cur.price_score, '20%', 'MVP阶段默认中性分80')}
                    ${renderDimRow('服务', cur.service_score, '15%', 'MVP阶段默认75分')}
                </tbody>
            </table>
            ${(score.adjustments||[]).length > 0 ? `
                <h4 style="margin:14px 0 8px;font-size:13px;color:#374151">📝 人工调整记录</h4>
                ${score.adjustments.map(a => `
                    <div style="padding:8px;background:#f9fafb;border-radius:6px;margin-bottom:6px;font-size:13px">
                        <strong>${a.adjustment > 0 ? '+' : ''}${a.adjustment}分</strong>
                        — ${a.reason}<br>
                        <small style="color:#9ca3af">操作人: ${a.adjusted_by || '--'} | ${formatTime(a.adjusted_at)}</small>
                    </div>`).join('')}
            ` : ''}
        `;
    } else {
        document.getElementById('dimension-content').innerHTML = '<p style="color:#9ca3af;padding:20px;text-align:center">暂无评分数据</p>';
    }

    // 趋势图
    if ((score.trend||[]).length > 0) {
        document.getElementById('trend-content').innerHTML = renderTrendChart(score.trend);
    }

    // 关联订单
    if (orders && orders.length > 0) {
        document.getElementById('related-section').style.display = 'grid';
        document.getElementById('orders-content').innerHTML = orders.slice(0, 8).map(o =>
            `<div class="related-item">
                <span>${o.po_number || o.poNumber || '--'}</span>
                <span style="color:${o.status==='received'?'#22c55e':o.status==='cancelled'?'#ef4444':'#f59e0b'}">
                    ${o.status || '--'} · ¥${(o.total_amount||0).toLocaleString()}</span>
            </div>`
        ).join('');
    }

    // 操作区
    renderActionZone(supplier);
}

function renderDimMiniBar(label, score, cls) {
    if (score === null || score === undefined) return '';
    const pct = Math.min(100, Math.max(0, score));
    return `<div class="dim-item">
        <div class="dim-header"><span class="dim-name">${label}</span><span class="dim-score">${score.toFixed(1)}</span></div>
        <div class="dim-bar"><div class="dim-fill ${cls}" style="width:${pct}%"></div></div>
    </div>`;
}

function renderDimRow(label, weight, desc) {
    const scoreVal = label.includes('★') ?
        (document.querySelector('.radar-score-big')?.textContent || '--') :
        '--';
    // 从实际数据取值
    const dims = currentSupplierData ? {} : {};
    return `<tr style="font-size:13px">
        <td style="font-weight:500">${label}</td>
        <td style="font-weight:600;color:#1f2937">${scoreVal}</td>
        <td style="color:#6b7280">${weight}</td>
        <td style="color:#6b7280">${desc}</td>
    </tr>`;
}

function renderTrendChart(trend) {
    if (!trend || trend.length === 0) return '';

    const maxScore = 100;
    const minScore = Math.min(...trend.map(t => t.overall), 50);
    const range = maxScore - minScore || 1;
    const w = 280; h = 120; padL = 30; padB = 24; padT = 10;

    const points = trend.map((t, i) => {
        const x = padL + (i / Math.max(trend.length-1, 1)) * (w - padL);
        const y = h - padB - ((t.overall - minScore) / range) * (h - padT - padB);
        return { x, y, ...t };
    });

    const pathD = points.map((p, i) => `${i===0?'M':'L'}${p.x},${p.y}`).join(' ');
    const areaD = `${pathD} L${points[points.length-1].x},${h-padB} L${points[0].x},${h-padB} Z`;

    return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <defs>
            <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.2"/>
                <stop offset="100%" stop-color="#3b82f6" stop-opacity="0"/>
            </linearGradient>
        </defs>
        <!-- 网格线 -->
        ${[25,50,75].map(v => {
            const y = h-padB-((v-minScore)/range)*(h-padT-padB);
            return `<line x1="${padL}" y1="${y}" x2="${w}" y2="${y}" stroke="#f3f4f6"/>`;
        }).join('')}
        <!-- 面积 -->
        <path d="${areaD}" fill="url(#trendGrad)" />
        <!-- 折线 -->
        <path d="${pathD}" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round"/>
        <!-- 数据点 -->
        ${points.map(p => `
            <circle cx="${p.x}" cy="${p.y}" r="4" fill="#fff" stroke="#3b82f6" stroke-width="2">
                <title>${p.period}: ${p.overall} (${p.grade})</title>
            </circle>
        `).join('')}
        <!-- X轴标签 -->
        ${points.map(p => `
            <text x="${p.x}" y="${h-4}" font-size="10" fill="#9ca3af"
                  text-anchor="middle">${p.period.substring(5)}</text>
        `).join('')}
    </svg>`;
}

function renderActionZone(supplier) {
    const st = supplier.status;
    let actions = [];
    let statusText = '', statusDesc = '';

    switch (st) {
        case 'pending':
            statusText = '⏳ 待审核';
            statusDesc = '该供应商已创建但尚未通过资质审核';
            actions.push({ label: '✅ 激活', cls: 'success', action: () => doAction('activate', '确认激活该供应商？') });
            actions.push({ label: '🗑 删除', cls: 'danger', action: () => doAction('delete', '确认删除？仅待审核状态可删除') });
            break;
        case 'active':
            statusText = '🟢 活跃合作';
            statusDesc = `当前综合评分: ${supplier.score_overall || '--'} (${supplier.score_grade || '--'}级)`;
            actions.push({ label: '⏸ 停用合作', cls: '', action: () => doAction('suspend', '确认停用该供应商？请填写停用原因', true) });
            actions.push({ label: '🚫 加入黑名单', cls: 'danger', action: () => doAction('blacklist', '⚠️ 确认拉黑？需先停用该供应商', true) });
            actions.push({ label: '📝 调整评分 ±', cls: '', action: () => openAdjustModal() });
            break;
        case 'probation':
            statusText = '🟡 观察期';
            statusDesc = '该供应商评分降至C级或出现重大问题，正在观察中';
            actions.push({ label: '⏸ 停用合作', cls: '', action: () => doAction('suspend', '确认停用？观察期内违规将直接停用', true) });
            actions.push({ label: '📝 调整评分 ±', cls: '', action: () => openAdjustModal() });
            break;
        case 'suspended':
            statusText = '🔴 已停用';
            statusDesc = '该供应商已暂停合作';
            actions.push({ label: '♻️ 恢复合作', cls: 'success', action: () => doAction('restore', '确认恢复该供应商为活跃状态？') });
            actions.push({ label: '🚫 加入黑名单', cls: 'danger', action: () => doAction('blacklist', '⚠️ 确认拉黑？此操作不可逆', true) });
            break;
        case 'blacklisted':
            statusText = '⚫ 已拉黑';
            statusDesc = '该供应商已被列入黑名单，不允许创建新采购订单';
            actions.push({ label: '♻️ 解除黑名单并恢复', cls: 'success', action: () => doAction('restore', '⚠️ 确认解除黑名单？需要重新全流程审核') });
            break;
    }

    document.getElementById('action-content').innerHTML = `
        <div class="status-title">${statusText}</div>
        <div class="status-desc">${statusDesc}</div>
        <div class="action-btns">
            ${actions.map(a => `<button class="action-btn ${a.cls||''}" onclick="(${a.action.toString()})()">${a.label}</button>`).join('')}
        </div>
    `;
}

// 操作执行
function doAction(action, confirmMsg, needReason=false) {
    if (confirmMsg && !confirm(confirmMsg)) return;

    if (needReason) {
        const reason = prompt('请输入原因:');
        if (!reason) return;
        executeAction(action, reason);
    } else {
        executeAction(action);
    }
}

async function executeAction(action, reason='') {
    const id = currentSupplierId;
    const endpoints = {
        activate: `/suppliers/${id}/activate`,
        suspend: `/suppliers/${id}/suspend`,
        blacklist: `/suppliers/${id}/blacklist`,
        restore: `/suppliers/${id}/restore`,
        delete: `/suppliers/${id}`,
    };

    const methods = { activate:'POST', suspend:'POST', blacklist:'POST', restore:'POST', delete:'DELETE' };
    const body = reason ? { reason } : null;

    try {
        if (action === 'delete') {
            await apiCall('DELETE', endpoints[action]);
        } else {
            await apiCall(methods[action], endpoints[action], body);
        }
        alert('✅ 操作成功');
        loadDetail(); // 刷新详情
    } catch (err) {
        alert('❌ 操作失败: ' + err.message);
    }
}

// 调整评分
function openAdjustModal() {
    document.getElementById('adjust-modal').style.display = 'flex';
}
function closeAdjustModal() {
    document.getElementById('adjust-modal').style.display = 'none';
}
async function doAdjust(e) {
    e.preventDefault();
    const value = parseFloat(document.getElementById('adjust-value').value);
    const reason = document.getElementById('adjust-reason').value.trim();

    try {
        await apiCall('POST', `/suppliers/${currentSupplierId}/adjust-score`, {
            adjustment: value, reason,
        });
        closeAdjustModal();
        alert(`✅ 评分调整成功 (+${value > 0?'':''}${value})`);
        loadDetail(); // 刷新
    } catch (err) {
        alert('❌ 调整失败: ' + err.message);
    }
}

function editSupplier() {
    alert('编辑功能：可扩展为编辑弹窗，当前版本请在列表页了解基础信息后联系管理员');
}


// ============================================================
// 页面初始化
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    const isDetail = window.location.pathname.includes('detail');

    if (isDetail) {
        loadDetail();
    } else {
        loadStats();
        loadRecords();

        // 绑定搜索/筛选事件
        const searchInput = document.getElementById('search-input');
        const filterStatus = document.getElementById('filter-status');
        const filterGrade = document.getElementById('filter-grade');

        if (searchInput) {
            let timer;
            searchInput.addEventListener('input', () => {
                clearTimeout(timer);
                timer = setTimeout(() => { currentPage = 1; loadRecords(); }, 300);
            });
        }
        if (filterStatus) filterStatus.addEventListener('change', () => { currentPage = 1; loadRecords(); });
        if (filterGrade) filterGrade.addEventListener('change', () => { currentPage = 1; loadRecords(); });
    }
});
