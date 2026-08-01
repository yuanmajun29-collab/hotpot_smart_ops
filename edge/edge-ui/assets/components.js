/**
 * 火瞳边缘盒子 · 可复用 UI 组件
 * 
 * 纯原生 JS 实现，无框架依赖
 */
const EdgeUI = (() => {

  // ── Toast 通知 ──
  let _toastContainer = null;

  function ensureToastContainer() {
    if (_toastContainer) return;
    _toastContainer = document.createElement('div');
    _toastContainer.className = 'toast-container';
    document.body.appendChild(_toastContainer);
  }

  /**
   * 显示 Toast
   * @param {string} message - 消息文本
   * @param {'success'|'error'|'warn'|'info'} type - 类型
   * @param {number} duration - 显示时长(ms)
   */
  function toast(message, type = 'info', duration = 3000) {
    ensureToastContainer();
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    
    const icons = { success: '✓', error: '✕', warn: '⚠', info: 'ℹ' };
    el.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
    
    _toastContainer.appendChild(el);
    
    setTimeout(() => {
      el.style.animation = 'slideInRight 0.3s ease reverse forwards';
      setTimeout(() => el.remove(), 300);
    }, duration);
  }

  // ── Modal 弹窗 ──
  
  /**
   * 打开确认弹窗
   * @param {Object} opts
   * @param {string} opts.title - 标题
   * @param {string} opts.message - 内容（支持HTML）
   * @param {string} [opts.confirmText='确定'] - 确认按钮文字
   * @param {string} [opts.cancelText='取消'] - 取消按钮文字
   * @param {'primary'|'danger'} [opts.confirmType='primary'] - 确认按钮类型
   * @returns {Promise<boolean>}
   */
  function confirm(opts) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay active';
      
      overlay.innerHTML = `
        <div class="modal" role="dialog">
          <div class="modal-header">
            <h3 class="modal-title">${escHtml(opts.title || '确认操作')}</h3>
            <button class="modal-close" aria-label="关闭">✕</button>
          </div>
          <div class="modal-body">
            <p style="color:var(--text-secondary);line-height:1.7">${opts.message || ''}</p>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary btn-modal-cancel">${opts.cancelText || '取消'}</button>
            <button class="btn ${opts.confirmType === 'danger' ? 'btn-danger' : 'btn-primary'} btn-modal-confirm">${opts.confirmText || '确定'}</button>
          </div>
        </div>
      `;
      
      document.body.appendChild(overlay);
      
      overlay.querySelector('.modal-close').onclick = () => close(false);
      overlay.querySelector('.btn-modal-cancel').onclick = () => close(false);
      overlay.querySelector('.btn-modal-confirm').onclick = () => close(true);
      overlay.onclick = (e) => { if (e.target === overlay) close(false); };
      
      function close(result) {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 250);
        resolve(result);
      }
    });
  }

  /**
   * 打开表单弹窗
   * @param {Object} opts
   * @param {string} opts.title - 标题
   * @param {string} opts.htmlBody - 表单HTML
   * @param {Function} opts.onConfirm - 确认回调，接收表单数据，返回Promise
   * @param {Object} [opts.initialData={}] - 初始数据
   */
  async function formModal(opts) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    
    overlay.innerHTML = `
      <div class="modal" role="dialog" style="max-width:600px">
        <div class="modal-header">
          <h3 class="modal-title">${escHtml(opts.title)}</h3>
          <button class="modal-close" aria-label="关闭">✕</button>
        </div>
        <form class="modal-body" id="formModalForm" autocomplete="off">
          ${opts.htmlBody}
        </form>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary btn-form-cancel">取消</button>
          <button type="submit" form="formModalForm" class="btn btn-primary btn-form-confirm">保存</button>
        </div>
      </div>
    `;
    
    document.body.appendChild(overlay);
    
    // 填充初始数据
    if (opts.initialData) {
      for (const [k, v] of Object.entries(opts.initialData)) {
        const field = overlay.querySelector(`[name="${k}"]`);
        if (field) {
          if (field.type === 'checkbox') field.checked = !!v;
          else field.value = v ?? '';
        }
      }
    }
    
    return new Promise((resolve) => {
      overlay.querySelector('.modal-close').onclick = () => close(null);
      overlay.querySelector('.btn-form-cancel').onclick = () => close(null);
      
      overlay.querySelector('#formModalForm').onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData.entries());
        
        const confirmBtn = overlay.querySelector('.btn-form-confirm');
        confirmBtn.disabled = true;
        confirmBtn.textContent = '保存中...';
        
        try {
          await opts.onConfirm(data);
          toast('保存成功', 'success');
          close(data);
        } catch (err) {
          toast(err.message, 'error');
          confirmBtn.disabled = false;
          confirmBtn.textContent = '保存';
        }
      };
      
      overlay.onclick = (e) => { if (e.target === overlay) close(null); };
      
      function close(result) {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 250);
        resolve(result);
      }
    });
  }

  // ── Skeleton 加载态 ──
  
  function skeletonCard() {
    return `
      <div class="card">
        <div class="card-header"><div class="skeleton skeleton-text short"></div></div>
        <div class="card-body">
          <div class="skeleton skeleton-heading"></div>
          <div class="skeleton skeleton-text"></div>
          <div class="skeleton skeleton-text short"></div>
        </div>
      </div>`;
  }

  function skeletonStatGrid(count = 4) {
    return Array.from({ length: count }, () => `
      <div class="stat-card">
        <div class="skeleton skeleton-text" style="width:60px;margin-bottom:8px"></div>
        <div class="skeleton skeleton-box" style="height:32px;margin-bottom:8px"></div>
        <div class="skeleton stat-bar"></div>
      </div>
    `).join('');
  }

  // ── 状态轮询 ──
  let _pollers = new Map();

  /**
   * 启动定时刷新
   * @param {string} key - 唯一标识
   * @param {Function} fn - 刷新函数
   * @param {number} intervalMs - 间隔毫秒
   */
  function startPolling(key, fn, intervalMs = 5000) {
    stopPolling(key);
    fn();  // 立即执行一次
    const timer = setInterval(fn, intervalMs);
    _pollers.set(key, timer);
  }

  function stopPolling(key) {
    const timer = _pollers.get(key);
    if (timer) {
      clearInterval(timer);
      _pollers.delete(key);
    }
  }

  function stopAllPolling() {
    _pollers.forEach((timer, key) => clearInterval(timer));
    _pollers.clear();
  }

  // ── 工具函数 ──
  
  /** HTML转义 */
  function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /** 格式化字节大小 */
  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
  }

  /** 格式化运行时间 */
  function formatUptime(seconds) {
    if (!seconds) return '-';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const parts = [];
    if (d > 0) parts.push(`${d}天`);
    if (h > 0) parts.push(`${h}小时`);
    if (m > 0 || parts.length === 0) parts.push(`${m}分钟`);
    return parts.join('');
  }

  /** 格式化时间 */
  function formatTime(isoStr) {
    if (!isoStr) return '-';
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('zh-CN', { 
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
    } catch { return isoStr; }
  }

  /** 获取状态颜色类 */
  function statusClass(status) {
    const map = {
      online: 'success', running: 'success', ok: 'success', pass: 'success',
      offline: 'error', stopped: 'error', fail: 'error',
      idle: 'warn', warning: 'warn', warn: 'warn',
    };
    return map[String(status).toLowerCase()] || 'neutral';
  }

  /** 获取状态显示名 */
  function statusLabel(status) {
    const map = {
      online: '在线', running: '运行中', ok: '正常', pass: '通过',
      offline: '离线', stopped: '已停止', fail: '失败',
      idle: '待机', warning: '警告', warn: '警告',
      error: '异常',
    };
    return map[String(status).toLowerCase()] || status;
  }

  // ── 导出 ──
  return {
    toast,
    confirm,
    formModal,
    skeletonCard,
    skeletonStatGrid,
    startPolling,
    stopPolling,
    stopAllPolling,
    escHtml,
    formatBytes,
    formatUptime,
    formatTime,
    statusClass,
    statusLabel,
  };
})();
