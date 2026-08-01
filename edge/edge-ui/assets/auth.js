/**
 * 火瞳 Edge UI · 认证逻辑模块
 *
 * 设计文档: §7 安全架构 (L2 访问控制)
 * 功能:
 *   - PIN输入组件 (6位数字)
 *   - 登录 / 设置初始PIN 模式切换
 *   - Session状态检测
 *   - API请求自动携带Cookie (浏览器原生行为)
 *   - 401响应自动跳转登录页
 */

(function () {
  'use strict';

  // ── DOM 引用 ──
  const realInput = document.getElementById('realPinInput');
  const digits = document.querySelectorAll('.pin-digit');
  const submitBtn = document.getElementById('submitBtn');
  const errorMsg = document.getElementById('errorMsg');
  const pinHint = document.getElementById('pinHint');
  const pageTitle = document.getElementById('pageTitle');
  const pageSubtitle = document.getElementById('pageSubtitle');
  const modeToggle = document.getElementById('modeToggle');
  const modeToggleText = document.getElementById('modeToggleText');

  // ── 状态 ──
  let currentMode = 'login';  // 'login' | 'setup'
  let pinValue = '';

  // ── 初始化 ──
  async function init() {
    // 检查认证状态，决定显示模式
    try {
      const resp = await fetch('/api/v1/auth/status', { credentials: 'same-origin' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.authenticated) {
          // 已登录 → 跳转首页
          window.location.href = '/index.html';
          return;
        }
        if (data.setup_required) {
          // 需要设置初始PIN
          setMode('setup');
        } else {
          setMode('login');
        }
      }
    } catch (e) {
      console.warn('[Auth] 无法获取认证状态:', e);
    }

    bindEvents();
    // 自动聚焦隐藏输入框
    setTimeout(() => realInput.focus(), 100);
  }

  // ── 模式切换 ──
  function setMode(mode) {
    currentMode = mode;
    clearPin();
    errorMsg.textContent = '';

    if (mode === 'setup') {
      pageTitle.textContent = '初始化访问密码';
      pageSubtitle.textContent = '首次使用需要设置6位数字密码';
      pinHint.textContent = '请设置一个容易记住的6位数字密码';
      submitBtn.textContent = '设置密码';
      submitBtn.classList.add('btn-setup');
      modeToggle.style.display = 'none';
    } else {
      pageTitle.textContent = '边缘盒子控制台';
      pageSubtitle.textContent = '请输入访问密码';
      pinHint.textContent = '输入6位数字密码';
      submitBtn.textContent = '确认';
      submitBtn.classList.remove('btn-setup');
      modeToggle.style.display = '';
      modeToggleText.innerHTML = '还未设置密码? <a id="linkToSetup">前往设置</a>';
      document.getElementById('linkToSetup').onclick = () => setMode('setup');
    }
  }

  // ── PIN 输入处理 ──
  function bindEvents() {
    // 隐藏输入框捕获键盘事件
    realInput.addEventListener('input', handleInput);
    realInput.addEventListener('keydown', handleKeydown);

    // 点击digit框聚焦到真实输入框
    digits.forEach(d => d.addEventListener('click', () => realInput.focus()));

    // 提交按钮
    submitBtn.addEventListener('click', handleSubmit);

    // 物理键盘回车提交
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && pinValue.length === 6) handleSubmit();
    });
  }

  function handleInput(e) {
    // 只保留数字
    let value = e.target.value.replace(/\D/g, '');
    // 限制6位
    if (value.length > 6) value = value.slice(0, 6);
    e.target.value = value;

    pinValue = value;
    updateDigitDisplay();

    // 自动提交
    if (pinValue.length === 6) {
      submitBtn.disabled = false;
      handleSubmit();
    } else {
      submitBtn.disabled = true;
    }
  }

  function handleKeydown(e) {
    // Backspace 处理
    if (e.key === 'Backspace') {
      if (pinValue.length > 0) {
        pinValue = pinValue.slice(0, -1);
        realInput.value = pinValue;
        updateDigitDisplay();
        submitBtn.disabled = true;
      }
      return;
    }
  }

  function updateDigitDisplay() {
    digits.forEach((d, i) => {
      d.value = pinValue[i] || '';
      d.classList.toggle('filled', i < pinValue.length);
    });
  }

  function clearPin() {
    pinValue = '';
    realInput.value = '';
    updateDigitDisplay();
    submitBtn.disabled = true;
  }

  // ── 提交逻辑 ──
  async function handleSubmit() {
    if (pinValue.length !== 6) return;

    const pin = pinValue;
    submitBtn.disabled = true;
    errorMsg.textContent = '';

    try {
      const endpoint = currentMode === 'setup'
        ? '/api/v1/auth/setup'
        : '/api/v1/auth/login';

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
        credentials: 'same-origin',
      });

      const data = await resp.json();

      if (resp.ok && data.ok) {
        // 成功 → 跳转首页
        errorMsg.style.color = '#3B6D11';
        errorMsg.textContent = data.message + ', 正在跳转...';
        setTimeout(() => { window.location.href = '/index.html'; }, 600);
      } else {
        // 失败
        showError(data.detail || '操作失败');
        shakeCard();
        clearPin();
        realInput.focus();
      }
    } catch (err) {
      showError('网络错误，请重试');
      console.error('[Auth] Error:', err);
      submitBtn.disabled = false;
    }
  }

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
