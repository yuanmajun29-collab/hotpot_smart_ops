/**
 * 火瞳边缘盒子 · 初始化向导逻辑
 * 
 * 4步向导：门店绑定 → 摄像头检测 → Hub配置 → 完成
 */
const SetupWizard = (() => {
  const API = (typeof EdgeAPI !== 'undefined') ? EdgeAPI : null;
  
  // ── 状态 ──
  let currentStep = 1;
  const totalSteps = 4;
  let storeData = {};
  let cameraData = [];
  let hubData = {};

  // ── 步骤配置 ──
  const steps = [
    { id: 1, title: '门店绑定', icon: '🏪', path: '#step-store' },
    { id: 2, title: '摄像头检测', icon: '📷', path: '#step-camera' },
    { id: 3, title: '平台连接', icon: '☁️', path: '#step-hub' },
    { id: 4, title: '初始化完成', icon: '✅', path: '#step-done' },
  ];

  // ── DOM 工具 ─
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  /**
   * 初始化向导
   */
  function init() {
    renderSteps();
    bindEvents();
    showStep(1);
    
    // 预填设备信息（如果已有）
    loadDeviceInfo();
  }

  /**
   * 渲染步骤指示器
   */
  function renderSteps() {
    const container = $('#stepIndicator');
    if (!container) return;

    container.innerHTML = steps.map((s, i) => `
      <div class="step-item ${i + 1 === currentStep ? 'active' : ''} ${i + 1 < currentStep ? 'done' : ''}" data-step="${s.id}">
        <div class="step-num">${i + 1 < currentStep ? '✓' : s.id}</div>
        <div class="step-label">${s.title}</div>
      </div>
    `).join('');
  }

  /**
   * 显示指定步骤
   */
  function showStep(step) {
    currentStep = step;
    
    // 更新步骤指示器
    renderSteps();

    // 切换内容面板
    $$('[data-step-panel]').forEach(panel => {
      panel.classList.toggle('active', parseInt(panel.dataset.stepPanel) === step);
    });

    // 更新按钮状态
    const prevBtn = $('#btnPrev');
    const nextBtn = $('#btnNext');
    if (prevBtn) prevBtn.style.display = step > 1 ? '' : 'none';
    if (nextBtn) {
      nextBtn.textContent = step === totalSteps ? '开始使用' : '下一步';
      nextBtn.disabled = false;
    }

    // 步骤特定初始化
    switch (step) {
      case 2: detectCameras(); break;
      case 3: testHubConnection(); break;
      case 4: showSummary(); break;
    }
  }

  /**
   * 绑定事件
   */
  function bindEvents() {
    $('#btnPrev')?.addEventListener('click', () => {
      if (currentStep > 1) showStep(currentStep - 1);
    });

    $('#btnNext')?.addEventListener('click', async () => {
      if (await validateStep(currentStep)) {
        if (currentStep < totalSteps) {
          showStep(currentStep + 1);
        } else {
          await completeSetup();
        }
      }
    });

    // 门店表单自动填充
    $('#inputStoreName')?.addEventListener('input', (e) => {
      storeData.store_name = e.target.value;
    });
  }

  /**
   * 加载设备信息预填
   */
  async function loadDeviceInfo() {
    if (!API) return;
    try {
      const info = await API.system.info();
      if ($('#inputDeviceId')) $('#inputDeviceId').value = info.device_id || '';
      if ($('#inputDeviceName')) $('#inputDeviceName').value = info.device_name || '';
    } catch (e) {
      console.warn('加载设备信息失败:', e.message);
    }
  }

  /**
   * 验证当前步骤
   */
  async function validateStep(step) {
    switch (step) {
      case 1:
        storeData.store_name = $('#inputStoreName')?.value?.trim();
        storeData.region = $('#inputRegion')?.value || '台州';
        if (!storeData.store_name) {
          showToast('请输入门店名称', 'warning');
          return false;
        }
        return true;

      case 2:
        if (cameraData.length === 0) {
          showToast('请至少添加一个摄像头', 'warning');
          return false;
        }
        return true;

      case 3:
        hubData.hub_url = $('#inputHubUrl')?.value?.trim();
        if (!hubData.hub_url) {
          showToast('请输入平台地址', 'warning');
          return false;
        }
        return true;

      default:
        return true;
    }
  }

  /**
   * 检测摄像头（扫描局域网）
   */
  async function detectCameras() {
    const listEl = $('#cameraDetectList');
    if (!listEl) return;

    listEl.innerHTML = '<div class="text-muted">正在扫描局域网摄像头...</div>';

    try {
      // 调用后端摄像头列表接口
      const cameras = API ? await API.cameras.list() : [];
      
      if (cameras.length > 0) {
        cameraData = cameras;
        renderCameraList(cameras);
      } else {
        listEl.innerHTML = `
          <div class="text-center py-md">
            <p class="text-muted mb-sm">未检测到摄像头</p>
            <button class="btn btn-primary btn-sm" onclick="SetupWizard.manualAddCamera()">手动添加</button>
          </div>
        `;
      }
    } catch (e) {
      listEl.innerHTML = `<div class="text-danger">检测失败: ${e.message}</div>`;
    }
  }

  /**
   * 渲染摄像头列表
   */
  function renderCameraList(cameras) {
    const listEl = $('#cameraDetectList');
    if (!listEl) return;

    listEl.innerHTML = cameras.map((c, i) => `
      <div class="card card-compact mb-sm" style="border-left: 3px solid var(--primary);">
        <div class="card-body" style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <strong>${c.name || `摄像头 ${i + 1}`}</strong>
            <div class="text-muted text-sm">${c.ip || '-'} · ${c.vendor || '-'}</div>
          </div>
          <span class="badge badge-success">已检测</span>
        </div>
      </div>
    `).join('');
  }

  /**
   * 手动添加摄像头
   */
  function manualAddCamera() {
    // 触发模态框或展开表单
    const modal = document.getElementById('cameraModal');
    if (modal && typeof EdgeUI !== 'undefined' && EdgeUI.showModal) {
      EdgeUI.showModal('addCameraModal');
    }
  }

  /**
   * 测试平台连接
   */
  async function testHubConnection() {
    const statusEl = $('#hubTestStatus');
    if (!statusEl) return;

    const url = $('#inputHubUrl')?.value?.trim();
    if (!url) {
      statusEl.innerHTML = '<span class="text-muted">请先输入平台地址</span>';
      return;
    }

    statusEl.innerHTML = '<span class="text-muted">测试连接中...</span>';

    try {
      // 这里只是前端验证URL格式，实际连接由后端处理
      new URL(url);
      statusEl.innerHTML = '<span class="text-success">✓ 地址格式正确</span>';
      hubData.hub_url = url;
    } catch (e) {
      statusEl.innerHTML = '<span class="text-danger">✗ 地址格式无效</span>';
    }
  }

  /**
   * 显示最终确认
   */
  function showSummary() {
    const el = $('#setupSummary');
    if (!el) return;

    el.innerHTML = `
      <div class="space-y-md">
        <div class="card card-compact">
          <div class="card-body">
            <h4>🏪 门店信息</h4>
            <p>名称: <strong>${storeData.store_name || '-'}</strong></p>
            <p>区域: ${storeData.region || '-'}</p>
          </div>
        </div>
        <div class="card card-compact">
          <div class="card-body">
            <h4>📷 摄像头 (${cameraData.length}个)</h4>
            ${cameraData.map(c => `<p>· ${c.name || c.ip}</p>`).join('')}
          </div>
        </div>
        <div class="card card-compact">
          <div class="card-body">
            <h4>☁️ 平台连接</h4>
            <p>地址: <code>${hubData.hub_url || '-'}</code></p>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * 完成初始化
   */
  async function completeSetup() {
    const btn = $('#btnNext');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '正在保存...';
    }

    try {
      // 调用后端初始化接口
      if (API && API.setup?.initialize) {
        await API.setup.initialize({
          store: storeData,
          cameras: cameraData,
          hub: hubData,
        });
      }

      // 显示成功页面
      $('#stepDoneContent').innerHTML = `
        <div class="text-center py-lg">
          <svg width="64" height="64" class="mb-md"><use href="assets/icons.svg#icon-success"/></svg>
          <h2>🎉 初始化完成！</h2>
          <p class="text-muted mt-sm">火瞳边缘盒子已准备就绪</p>
          <a href="/" class="btn btn-primary mt-md">进入控制台</a>
        </div>
      `;
    } catch (e) {
      showToast('保存失败: ' + e.message, 'error');
      if (btn) {
        btn.disabled = false;
        btn.textContent = '重试';
      }
    }
  }

  // Toast提示（复用全局或本地实现）
  function showToast(msg, type = 'info') {
    if (typeof EdgeUI !== 'undefined' && EdgeUI.showToast) {
      EdgeUI.showToast(msg, type);
    } else {
      alert(msg); // 降级
    }
  }

  // ── 公开接口 ──
  return {
    init,
    showStep,
    manualAddCamera,
    detectCameras,
    get currentStep() { return currentStep; },
    get storeData() { return storeData; },
    get cameraData() { return cameraData; },
    get hubData() { return hubData; },
  };
})();

// 自动初始化（如果页面包含向导）
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('setupWizard')) {
    SetupWizard.init();
  }
});
