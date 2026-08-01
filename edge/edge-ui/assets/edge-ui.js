/**
 * 火瞳边缘盒子 · 主逻辑
 * 
 * 导航、侧边栏、页面通用功能
 */
(function() {
  'use strict';

  // ── 当前页面标识 ──
  const currentPage = document.body.dataset.page || 'index';

  // ── 侧边栏导航配置 ──
  const navItems = [
    { id: 'index', icon: '📊', label: '首页仪表', href: 'index.html' },
    { id: 'setup', icon: '📍', label: '初始化向导', href: 'setup.html' },
    { type: 'separator' },
    { id: 'cameras', icon: '📷', label: '视觉设备', href: 'cameras.html' },
    { id: 'iot-sensors', icon: '🌡️', label: 'IoT传感器', href: 'iot-sensors.html' },
    { type: 'separator' },
    { id: 'system-network', icon: '🌐', label: '网络配置', href: 'system/network.html' },
    { id: 'system-hub', icon: '☁️', label: 'Hub设置', href: 'system/hub-settings.html' },
    { id: 'system-models', icon: '🧠', label: '模型管理', href: 'system/models.html' },
    { id: 'system-ota', icon: '⬆️', label: 'OTA升级', href: 'system/ota.html' },
    { type: 'separator' },
    { id: 'diagnostics', icon: '🔍', label: '诊断工具', href: 'diagnostics.html' },
    { id: 'logs', icon: '📋', label: '操作日志', href: 'logs.html' },
    { type: 'separator' },
    { id: 'about', icon: 'ℹ️', label: '关于/帮助', href: '#about' },
  ];

  // ── 初始化侧边栏 ──
  function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    let html = `
      <div class="sidebar-header">
        <div class="sidebar-logo">馮</div>
        <div>
          <div class="sidebar-title" id="sidebarDeviceName">火瞳边缘盒子</div>
          <div class="sidebar-subtitle" id="sidebarStatus">检测中...</div>
        </div>
      </div>
      <nav class="sidebar-nav">
    `;

    for (const item of navItems) {
      if (item.type === 'separator') {
        html += '<div class="nav-section-title"></div>';
      } else {
        const active = currentPage === item.id || 
          (currentPage.startsWith('system-') && item.id === `system-${currentPage.split('-')[1]}`) ? ' active' : '';
        html += `<a class="nav-item${active}" href="${item.href}">
          <span class="nav-icon">${item.icon}</span>
          <span>${item.label}</span>
        </a>`;
      }
    }

    html += `
      </nav>
      <div class="sidebar-footer">
        <span id="sidebarVersion">v-</span>
      </div>
    `;

    sidebar.innerHTML = html;
  }

  // ── 移动端菜单 ──
  function initMobileMenu() {
    const toggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    
    if (!toggle || !sidebar) return;

    toggle.onclick = () => {
      sidebar.classList.toggle('open');
      if (backdrop) backdrop.classList.toggle('open');
    };

    if (backdrop) {
      backdrop.onclick = () => {
        sidebar.classList.remove('open');
        backdrop.classList.remove('open');
      };
    }

    // 点击导航项后关闭侧边栏（移动端）
    sidebar.querySelectorAll('.nav-item').forEach(item => {
      item.onclick = () => {
        if (window.innerWidth <= 768) {
          sidebar.classList.remove('open');
          if (backdrop) backdrop.classList.remove('open');
        }
      };
    });
  }

  // ── 加载设备信息到侧边栏 ──
  async function loadDeviceInfo() {
    try {
      const info = await EdgeAPI.system.info();
      
      const nameEl = document.getElementById('sidebarDeviceName');
      const statusEl = document.getElementById('sidebarStatus');
      const versionEl = document.getElementById('sidebarVersion');

      if (nameEl) nameEl.textContent = info.device_name || '火瞳边缘盒子';
      if (statusEl) statusEl.textContent = '🟢 在线运行中';
      if (versionEl) versionEl.textContent = `v${info.firmware_version || '-'}`;

      // 存储全局设备信息
      window._deviceInfo = info;
    } catch (err) {
      const statusEl = document.getElementById('sidebarStatus');
      if (statusEl) statusEl.textContent = '🔴 连接异常';
    }
  }

  // ── 页面标题面包屑 ──
  function initPageHeader() {
    const titleEl = document.getElementById('pageTitle');
    const subtitleEl = document.getElementById('pageSubtitle');
    
    if (!titleEl) return;

    const pageTitles = {
      index: ['首页仪表盘', '实时监控边缘盒子运行状态'],
      setup: ['初始化向导', '首次配置或重新初始化'],
      cameras: ['视觉设备管理', '摄像头配置与状态监控'],
      'iot-sensors': ['IoT传感器管理', '温度/燃气/烟雾等传感器'],
      'system-network': ['网络配置', 'IP/DNS/网关设置'],
      'system-hub': ['Hub连接设置', '平台端通信配置'],
      'system-models': ['AI模型管理', '下载/切换/删除模型'],
      'system-ota': ['OTA升级', '固件在线更新'],
      diagnostics: ['诊断工具', '一键检测网络/摄像头/引擎'],
      logs: ['操作日志', '系统与操作审计记录'],
    };

    const [title, subtitle] = pageTitles[currentPage] || [currentPage, ''];
    titleEl.innerHTML = title;
    if (subtitleEl) subtitleEl.textContent = subtitle;
  }

  // ── 全局快捷键 ──
  function initShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+/ 或 Cmd+/ 显示快捷键帮助
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        EdgeUI.toast('快捷键：R=刷新 | S=诊断 | ?=本提示', 'info', 2000);
      }
      // R 键刷新当前页数据
      if (e.key === 'r' && !e.ctrlKey && !e.metaKey && 
          !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {
        // 可由各页面自行实现刷新逻辑
        window.dispatchEvent(new CustomEvent('edgeui:refresh'));
      }
    });
  }

  // ── 初始化 ──
  function init() {
    initSidebar();
    initMobileMenu();
    initPageHeader();
    initShortcuts();
    loadDeviceInfo();

    // 认证失效处理
    EdgeAPI.onAuthExpired(() => {
      EdgeUI.toast('认证已过期，请刷新页面', 'warn');
    });
  }

  // DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 暴露全局刷新事件
  window.EdgeApp = {
    refresh: () => window.dispatchEvent(new CustomEvent('edgeui:refresh')),
  };

})();
