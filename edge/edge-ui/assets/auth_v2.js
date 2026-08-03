/**
 * 火瞳 Edge UI · 认证逻辑模块 v2.0
 *
 * 升级特性:
 *   - 双模式登录: JWT(账号密码, 推荐) + PIN(6位数字, 降级)
 *   - 选项卡切换 (默认JWT)
 *   - PIN降级提示 + 新用户引导弹窗
 *   - Token自动刷新 + 过期重定向
 *   - 登录状态持久化 (LocalStorage + Cookie双写)
 *
 * API端点:
 *   POST /api/v1/auth/jwt-login    ← JWT登录
 *   POST /api/v1/auth/pin-login     ← PIN登录
 *   POST /api/v1/auth/refresh       ← Token刷新
 *   GET  /api/v1/auth/status        ← 认证状态检查
 */

(function () {
  'use strict';

  // ── DOM 引用 ──
  const tabJwt = document.getElementById('tabJwt');
  const tabPin = document.getElementById('tabPin');
  const jwtForm = document.getElementById('jwtForm');
  const pinForm = document.getElementById('pinForm');
  const jwtUsername = document.getElementById('jwtUsername');
  const jwtPassword = document.getElementById('jwtPassword');
  const jwtSubmitBtn = document.getElementById('jwtSubmitBtn');
  const rememberMe = document.getElementById('rememberMe');

  const realPinInput = document.getElementById('realPinInput');
  const pinDigits = document.querySelectorAll('.pin-digit');
  const pinSubmitBtn = document.getElementById('pinSubmitBtn');
  const pinHint = document.getElementById('pinHint');
  const errorMsg = document.getElementById('errorMsg');

  const upgradeModal = document.getElementById('upgradeModal');
  const btnSkipUpgrade = document.getElementById('btnSkipUpgrade');
  const btnDoUpgrade = document.getElementById('btnDoUpgrade');

  // ── 状态 ──
  let currentTab = 'jwt';  // 'jwt' | 'pin'
  let pinValue = '';
  let isSubmitting = false;

  // ── Token 管理 ──
  const TokenManager = {
    STORAGE_KEY: 'hotpot_auth_token',
    REFRESH_KEY: 'hotpot_refresh_token',
    USER_KEY: 'hotpot_user_info',

    save(access, refresh, user) {
      try {
        localStorage.setItem(this.STORAGE_KEY, access);
        if (refresh) localStorage.setItem(this.REFRESH_KEY, refresh);
        if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
      } catch (e) {
        console.warn('[Token] LocalStorage不可用:', e);
      }
      // Cookie备份 (用于同源API请求)
      document.cookie = `hotpot_token=${access}; path=/; max-age=86400; SameSite=Strict`;
    },

    getAccessToken() {
      return localStorage.getItem(this.STORAGE_KEY) || this.getCookie('hotpot_token');
    },

    getRefreshToken() {
      return localStorage.getItem(this.REFRESH_KEY);
    },

    getUser() {
      try {
        const raw = localStorage.getItem(this.USER_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch { return null; }
    },

    clear() {
      localStorage.removeItem(this.STORAGE_KEY);
      localStorage.removeItem(this.REFRESH_KEY);
      localStorage.removeItem(this.USER_KEY);
      document.cookie = 'hotpot_token=; path=/; max-age=0';
    },

    getCookie(name) {
      const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
      return match ? match[2] : null;
    },

    async refreshToken() {
      const refresh = this.getRefreshToken();
      if (!refresh) return false;

      try {
        const resp = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
          credentials: 'same-origin',
        });

        if (resp.ok) {
          const data = await resp.json();
          this.save(data.access_token, data.refresh_token, data.user);
          return true;
        } else {
          this.clear();
          return false;
        }
      } catch (e) {
        console.warn('[Token] 刷新失败:', e);
        return false;
      }
    },

    // 自动刷新定时器 (每23分钟，Token有效期24小时)
    startAutoRefresh() {
      setInterval(async () => {
        if (this.getAccessToken()) {
          await this.refreshToken();
        }
      }, 23 * 60 * 1000);
    }
  };

  // ── 初始化 ──
  async function init() {
    // 检查是否已登录
    try {
      const resp = await fetch('/api/v1/auth/status', { credentials: 'same-origin' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.authenticated) {
          window.location.href = '/index.html';
          return;
        }
      }
    } catch (e) {
      console.warn('[Auth] 无法获取认证状态:', e);
    }

    bindEvents();
    TokenManager.startAutoRefresh();

    // 默认聚焦到JWT用户名输入框
    setTimeout(() => jwtUsername.focus(), 100);

    // 检查是否显示升级引导 (上次使用PIN登录)
    if (localStorage.getItem('hotpot_last_login_mode') === 'pin' &&
        !localStorage.getItem('hotpot_upgrade_dismissed')) {
      // 延迟显示，避免干扰首次体验
      setTimeout(() => showUpgradeModal(), 2000);
    }
  }

  // ── 选项卡切换 ──
  function switchTab(tab) {
    currentTab = tab;
    errorMsg.textContent = '';

    if (tab === 'jwt') {
      tabJwt.classList.add('active');
      tabPin.classList.remove('active');
      jwtForm.classList.add('active');
      pinForm.classList.remove('active');
      setTimeout(() => jwtUsername.focus(), 100);
    } else {
      tabPin.classList.add('active');
      tabJwt.classList.remove('active');
      pinForm.classList.add('active');
      jwtForm.classList.remove('active');
      setTimeout(() => realPinInput.focus(), 100);
    }
  }

  // ── 事件绑定 ──
  function bindEvents() {
    // 选项卡切换
    tabJwt.addEventListener('click', () => switchTab('jwt'));
    tabPin.addEventListener('click', () => switchTab('pin'));

    // JWT表单
    jwtSubmitBtn.addEventListener('click', handleJwtLogin);
    jwtPassword.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleJwtLogin();
    });

    // PIN表单
    realPinInput.addEventListener('input', handlePinInput);
    realPinInput.addEventListener('keydown', handlePinKeydown);
    pinDigits.forEach(d => d.addEventListener('click', () => realPinInput.focus()));
    pinSubmitBtn.addEventListener('click', handlePinLogin);

    // 物理键盘回车提交PIN
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && currentTab === 'pin' && pinValue.length === 6) {
        handlePinLogin();
      }
    });

    // 升级弹窗
    btnSkipUpgrade.addEventListener('click', hideUpgradeModal);
    btnDoUpgrade.addEventListener('click', () => {
      hideUpgradeModal();
      switchTab('jwt');  // 切换到JWT表单让用户设置
    });
  }

  // ── JWT 登录处理 ──
  async function handleJwtLogin() {
    if (isSubmitting) return;

    const username = jwtUsername.value.trim();
    const password = jwtPassword.value;

    if (!username || !password) {
      showError('请输入用户名和密码');
      return;
    }

    isSubmitting = true;
    jwtSubmitBtn.disabled = true;
    jwtSubmitBtn.textContent = '登录中...';
    errorMsg.textContent = '';

    try {
      const resp = await fetch('/api/v1/auth/jwt-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'same-origin',
      });

      const data = await resp.json();

      if (resp.ok && data.access_token) {
        // 保存Token
        TokenManager.save(
          data.access_token,
          data.refresh_token,
          data.user
        );

        // 记录登录模式
        localStorage.setItem('hotpot_last_login_mode', 'jwt');

        // 成功跳转
        errorMsg.style.color = '#3B6D11';
        errorMsg.textContent = `欢迎回来, ${data.user?.username || username}! 正在跳转...`;
        setTimeout(() => { window.location.href = '/index.html'; }, 600);
      } else {
        showError(data.detail || '用户名或密码错误');
        shakeCard();
      }
    } catch (err) {
      showError('网络错误，请重试');
      console.error('[Auth] JWT Login Error:', err);
    } finally {
      isSubmitting = false;
      jwtSubmitBtn.disabled = false;
      jwtSubmitBtn.textContent = '登 录';
    }
  }

  // ── PIN 登录处理 ──
  function handlePinInput(e) {
    let value = e.target.value.replace(/\D/g, '');
    if (value.length > 6) value = value.slice(0, 6);
    e.target.value = value;

    pinValue = value;
    updatePinDisplay();

    if (pinValue.length === 6) {
      pinSubmitBtn.disabled = false;
      // 自动提交
      handlePinLogin();
    } else {
      pinSubmitBtn.disabled = true;
    }
  }

  function handlePinKeydown(e) {
    if (e.key === 'Backspace' && pinValue.length > 0) {
      pinValue = pinValue.slice(0, -1);
      realPinInput.value = pinValue;
      updatePinDisplay();
      pinSubmitBtn.disabled = true;
    }
  }

  function updatePinDisplay() {
    pinDigits.forEach((d, i) => {
      d.value = pinValue[i] || '';
      d.classList.toggle('filled', i < pinValue.length);
    });
  }

  function clearPin() {
    pinValue = '';
    realPinInput.value = '';
    updatePinDisplay();
    pinSubmitBtn.disabled = true;
  }

  async function handlePinLogin() {
    if (isSubmitting || pinValue.length !== 6) return;

    const pin = pinValue;
    isSubmitting = true;
    pinSubmitBtn.disabled = true;
    pinSubmitBtn.textContent = '验证中...';
    errorMsg.textContent = '';

    try {
      const resp = await fetch('/api/v1/auth/pin-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
        credentials: 'same-origin',
      });

      const data = await resp.json();

      if (resp.ok && data.access_token) {
        // PIN→JWT转换成功，保存Token
        TokenManager.save(
          data.access_token,
          data.refresh_token,
          data.user
        );

        // 记录登录模式 (用于升级引导)
        localStorage.setItem('hotpot_last_login_mode', 'pin');

        // 成功跳转
        errorMsg.style.color = '#3B6D11';
        errorMsg.textContent = `欢迎, ${data.user?.username || '用户'}! 正在跳转...`;
        setTimeout(() => { window.location.href = '/index.html'; }, 600);
      } else {
        showError(data.detail || 'PIN码错误');
        shakeCard();
        clearPin();
        realPinInput.focus();
      }
    } catch (err) {
      showError('网络错误，请重试');
      console.error('[Auth] PIN Login Error:', err);
    } finally {
      isSubmitting = false;
      pinSubmitBtn.disabled = pinValue.length !== 6;
      pinSubmitBtn.textContent = '确认';
    }
  }

  // ── 升级弹窗 ──
  function showUpgradeModal() {
    upgradeModal.classList.add('show');
  }

  function hideUpgradeModal() {
    upgradeModal.classList.remove('show');
    localStorage.setItem('hotpot_upgrade_dismissed', 'true');
    // 7天后再次提示
    setTimeout(() => {
      localStorage.removeItem('hotpot_upgrade_dismissed');
    }, 7 * 24 * 60 * 60 * 1000);
  }

  // ── 工具函数 ──
  function showError(msg) {
    errorMsg.style.color = 'var(--color-text-danger, #E24B4A)';
    errorMsg.textContent = msg;
  }

  function shakeCard() {
    const card = document.querySelector('.login-card');
    card.style.animation = 'none';
    card.offsetHeight; // 触发reflow
    card.style.animation = 'shake 0.4s ease';
  }

  // ── CSS动画注入 ──
  const style = document.createElement('style');
  style.textContent = `
    @keyframes shake {
      0%, 100% { transform: translateX(0); }
      20% { transform: translateX(-8px); }
      40% { transform: translateX(8px); }
      60% { transform: translateX(-4px); }
      80% { transform: translateX(4px); }
    }
  `;
  document.head.appendChild(style);

  // ── 启动 ──
  init();

})();
