/**
 * 火瞳 · 货品主数据管理 — 前端逻辑
 *
 * 功能:
 *   - 货品列表 (分页/搜索/筛选)
 *   - 新建/编辑/删除货品
 *   - 锁定/解锁操作
 *   - 种子数据初始化
 *   - 统计概览
 */

(function () {
    'use strict';

    // ── 状态 ──
    let currentPage = 1;
    const pageSize = 15;
    let categories = [];

    // ── API 基础 ──
    const API = {
        baseUrl: '/api/v1',

        async request(method, path, data) {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
            };
            if (data && method !== 'GET') {
                options.body = JSON.stringify(data);
            }
            const resp = await fetch(this.baseUrl + path, options);
            if (resp.status === 401) {
                window.location.href = '/login.html';
                throw new Error('未认证，跳转登录');
            }
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            return resp.json();
        },

        get(path, params) {
            const qs = new URLSearchParams(params).toString();
            return this.request('GET', path + (qs ? '?' + qs : ''));
        },
        post(path, data) { return this.request('POST', path, data); },
        put(path, data) { return this.request('PUT', path, data); },
        delete(path) { return this.request('DELETE', path); },
    };

    // ── 初始化 ──
    async function init() {
        try {
            await Promise.all([loadCategories(), loadStats(), loadProducts()]);
        } catch (e) {
            console.error('初始化失败:', e);
            showToast('加载失败: ' + e.message, 'error');
        }
    }

    // ── 分类加载 ──
    async function loadCategories() {
        try {
            categories = await API.get('/categories');
            renderCategoryOptions();
        } catch (e) {
            console.warn('分类加载失败:', e);
            // 使用默认分类
            categories = [
                { category_code: 'FROZEN_MEAT', category_name: '冻品荤菜' },
                { category_code: 'HOTPOT_BASE', category_name: '锅底/汤底' },
                { category_code: 'VEGETABLE', category_name: '素菜' },
                { category_code: 'STAPLE', category_name: '主食/小吃' },
                { category_code: 'DRINK', category_name: '酒水饮料' },
                { category_code: 'SEASONING', category_name: '调料蘸料' },
            ];
            renderCategoryOptions();
        }
    }

    function renderCategoryOptions() {
        const selects = ['filterCategory', 'formCategory'];
        selects.forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            const isFilter = id === 'filterCategory';
            const currentVal = el.value;

            // 清空选项（保留第一个"全部"或默认）
            while (el.options.length > (isFilter ? 1 : 0)) {
                el.remove(isFilter ? 1 : 0);
            }

            categories.forEach(cat => {
                const opt = document.createElement('option');
                opt.value = cat.category_code;
                opt.textContent = cat.category_name;
                el.appendChild(opt);
            });

            if (currentVal) el.value = currentVal;
        });
    }

    // ── 统计 ──
    async function loadStats() {
        try {
            const stats = await API.get('/products/stats');
            document.getElementById('statTotal').textContent = stats.total_products;
            document.getElementById('statActive').textContent = stats.active_products;
            document.getElementById('statLocked').textContent = stats.locked_products;
            document.getElementById('statDraft').textContent = stats.draft_products;
        } catch (e) {
            console.warn('统计加载失败:', e);
        }
    }

    // ── 货品列表 ──
    let searchTimer = null;
    window.debounceSearch = function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadProducts, 400);
    };

    async function loadProducts() {
        const tbody = document.getElementById('productTableBody');
        tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><div class="icon">⏳</div>加载中...</div></td></tr>';

        try {
            const params = {
                page: currentPage,
                page_size: pageSize,
                keyword: document.getElementById('searchInput').value.trim(),
                category: document.getElementById('filterCategory').value,
                status: document.getElementById('filterStatus').value,
            };
            const result = await API.get('/products', params);

            renderTable(result.items);
            renderPagination(result.total, result.page, result.page_size);

            // 更新分类列表(如果API返回了)
            if (result.categories && result.categories.length > categories.length) {
                categories = result.categories;
                renderCategoryOptions();
            }
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="icon">❌</div>加载失败: ${e.message}</div></td></tr>`;
        }
    }

    function renderTable(items) {
        const tbody = document.getElementById('productTableBody');
        if (!items || items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="icon">📦</div>暂无货品数据<br><button class="btn btn-primary btn-sm" onclick="initSeedData()" style="margin-top:12px;">🌱 初始化种子数据</button></div></td></tr>`;
            return;
        }

        tbody.innerHTML = items.map(p => `
            <tr>
                <td><span class="sku-code">${escHtml(p.sku_code)}</span></td>
                <td><strong>${escHtml(p.name)}</strong>${p.tags.map(t => `<span class="tag">${escHtml(t)}</span>`).join('')}</td>
                <td>${escHtml(p.brand)}</td>
                <td>${escHtml(p.specification)}</td>
                <td><span class="price">¥${p.unit_price.toFixed(2)}</span> / ${escHtml(p.unit)}</td>
                <td>${getCategoryName(p.category)}</td>
                <td>
                    <span class="status-badge status-${p.status}">${getStatusText(p.status)}</span>
                    ${p.locked ? '<span class="locked-badge">🔒 已锁定</span>' : ''}
                </td>
                <td style="white-space:nowrap;">
                    <button class="btn btn-sm btn-secondary" onclick="viewProduct('${p.sku_code}')">详情</button>
                    ${!p.locked ? `<button class="btn btn-sm btn-primary" onclick="editProduct('${p.sku_code}')">编辑</button>` : ''}
                    ${p.locked ? `<button class="btn btn-sm btn-success" onclick="unlockProduct('${p.sku_code}')">解锁</button>` : ''}
                    ${!p.locked && p.status !== 'active' ? `<button class="btn btn-sm btn-primary" onclick="lockProduct('${p.sku_code}')" title="锁定标准">🔒锁定</button>` : ''}
                    ${p.status === 'draft' ? `<button class="btn btn-sm btn-danger" onclick="deleteProduct('${p.sku_code}')">删除</button>` : ''}
                </td>
            </tr>
        `).join('');
    }

    function renderPagination(total, page, size) {
        const totalPages = Math.ceil(total / size) || 1;
        document.getElementById('paginationInfo').textContent =
            `共 ${total} 条记录，第 ${page}/${totalPages} 页`;

        const btns = document.getElementById('paginationBtns');
        let html = '';
        html += `<button class="page-btn" ${page <= 1 ? 'disabled' : ''} onclick="goPage(${page - 1})">上一页</button>`;
        for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
            html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
        }
        html += `<button class="page-btn" ${page >= totalPages ? 'disabled' : ''} onclick="goPage(${page + 1})">下一页</button>`;
        btns.innerHTML = html;
    }

    window.goPage = function (p) {
        currentPage = p;
        loadProducts();
    };

    // ── CRUD 操作 ──

    window.showCreateModal = function () {
        document.getElementById('modalTitle').textContent = '新建货品';
        document.getElementById('editSkuCode').value = '';
        document.getElementById('productForm').reset();
        document.getElementById('formSkuCode').disabled = false;
        document.getElementById('productModal').classList.add('show');
    };

    window.hideModal = function () {
        document.getElementById('productModal').classList.remove('show');
    };

    window.viewProduct = function (skuCode) {
        editProduct(skuCode, true);
    };

    window.editProduct = function (skuCode, readOnly = false) {
        API.get('/products/' + skuCode).then(p => {
            document.getElementById('modalTitle').textContent = readOnly ? '货品详情' : '编辑货品';
            document.getElementById('editSkuCode').value = p.sku_code;
            document.getElementById('formSkuCode').value = p.sku_code;
            document.getElementById('formSkuCode').disabled = true;  // SKU不可改
            document.getElementById('formName').value = p.name;
            document.getElementById('formBrand').value = p.brand;
            document.getElementById('formSpec').value = p.specification;
            document.getElementById('formPrice').value = p.unit_price;
            document.getElementById('formUnit').value = p.unit;
            document.getElementById('formCategory').value = p.category;
            document.getElementById('formSupplier').value = p.supplier_name || '';
            document.getElementById('formStorageArea').value = p.storage_area || '';
            document.getElementById('formShelfLife').value = p.shelf_life_days || '';
            document.getElementById('formTags').value = (p.tags || []).join(', ');

            // 只读模式禁用表单
            const formEls = document.querySelectorAll('#productForm input, #productForm select');
            formEls.forEach(el => el.disabled = readOnly);

            document.getElementById('productModal').classList.add('show');
        }).catch(e => showToast('获取详情失败: ' + e.message, 'error'));
    };

    window.saveProduct = function (event) {
        event.preventDefault();

        const isEdit = !!document.getElementById('editSkuCode').value;
        const skuCode = document.getElementById('formSkuCode').value.trim().toUpperCase();
        const data = {
            sku_code: skuCode,
            name: document.getElementById('formName').value.trim(),
            brand: document.getElementById('formBrand').value.trim(),
            specification: document.getElementById('formSpec').value.trim(),
            unit_price: parseFloat(document.getElementById('formPrice').value),
            unit: document.getElementById('formUnit').value,
            category: document.getElementById('formCategory').value,
            supplier_name: document.getElementById('formSupplier').value.trim(),
            storage_area: document.getElementById('formStorageArea').value || null,
            shelf_life_days: parseInt(document.getElementById('formShelfLife').value) || null,
            tags: document.getElementById('formTags').value.split(',').map(t => t.trim()).filter(Boolean),
        };

        const promise = isEdit
            ? API.put('/products/' + skuCode, data)
            : API.post('/products', data);

        promise.then(() => {
            hideModal();
            showToast(isEdit ? '✅ 货品更新成功' : '✅ 货品创建成功');
            loadProducts();
            loadStats();
        }).catch(e => showToast('保存失败: ' + e.message, 'error'));
    };

    window.lockProduct = function (skuCode) {
        if (!confirm('确定锁定此货品？\n\n锁定后名称/规格/品牌/价格四项关键字段将不可直接修改，需通过变更申请流程修改。')) return;

        API.post('/products/' + skuCode + '/lock').then(() => {
            showToast('🔒 货品已锁定');
            loadProducts();
            loadStats();
        }).catch(e => showToast('锁定失败: ' + e.message, 'error'));
    };

    window.unlockProduct = function (skuCode) {
        API.post('/products/' + skuCode + '/unlock?reason=管理员操作').then(() => {
            showToast('🔓 货品已解锁');
            loadProducts();
            loadStats();
        }).catch(e => showToast('解锁失败: ' + e.message, 'error'));
    };

    window.deleteProduct = function (skuCode) {
        if (!confirm(`确定删除货品 ${skuCode}？\n\n此操作不可撤销！`)) return;

        API.delete('/products/' + skuCode).then(() => {
            showToast('🗑️ 货品已删除');
            loadProducts();
            loadStats();
        }).catch(e => showToast('删除失败: ' + e.message, 'error'));
    };

    // ── 种子数据 ──
    window.initSeedData = async function () {
        if (!confirm('确定初始化种子数据？\n\n将加载 20+ 火锅常用冻品 SKU 用于展会演示。\n已有数据不受影响。')) return;

        try {
            const result = await API.post('/products/init');
            showToast(`🌱 种子数据加载完成！共 ${result.count} 个货品`);
            loadProducts();
            loadStats();
        } catch (e) {
            showToast('种子数据加载失败: ' + e.message, 'error');
        }
    };

    // ── 工具函数 ──
    function escHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function getCategoryName(code) {
        const cat = categories.find(c => c.category_code === code);
        return cat ? cat.category_name : code;
    }

    function getStatusText(status) {
        const map = { draft: '草稿', active: '激活', discontinued: '停用', pending_approval: '待审批' };
        return map[status] || status;
    }

    function showToast(msg, type = 'info') {
        // 简单的 toast 提示
        const existing = document.getElementById('toastMsg');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.id = 'toastMsg';
        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; padding: 12px 20px;
            border-radius: 8px; color: #fff; font-size: 14px; z-index: 9999;
            background: ${type === 'error' ? '#dc3545' : type === 'warning' ? '#ffc107' : '#28a745'};
            box-shadow: 0 4px 12px rgba(0,0,0,0.15); animation: fadeIn 0.3s ease;
        `;
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // 添加动画样式
    const style = document.createElement('style');
    style.textContent = '@keyframes fadeIn { from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }';
    document.head.appendChild(style);

    // ── 启动 ──
    init();
})();
