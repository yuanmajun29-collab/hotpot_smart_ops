/**
 * 火瞳边缘盒子 · API 客户端封装
 * 
 * 统一处理：请求/响应、错误、重试、认证
 */
const EdgeAPI = (() => {
  const BASE = '';  // 同源部署，使用相对路径
  const API_PREFIX = '/api/v1';
  
  // ── 内部状态 ──
  let _csrfToken = null;
  let _on401 = null;  // 认证失效回调

  /**
   * 通用请求方法
   */
  async function request(method, path, options = {}) {
    const url = `${API_PREFIX}${path}`;
    const { body, query, raw, timeout = 10000 } = options;
    
    let fullUrl = url;
    if (query) {
      const params = new URLSearchParams(query);
      fullUrl += `?${params.toString()}`;
    }

    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };
    
    if (_csrfToken) {
      headers['X-CSRF-Token'] = _csrfToken;
    }

    const fetchOpts = { method, headers };
    if (body !== undefined) {
      fetchOpts.body = JSON.stringify(body);
    }

    // 超时控制
    const controller = new AbortController();
    fetchOpts.signal = controller.signal;
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
      const res = await fetch(fullUrl, fetchOpts);
      clearTimeout(timer);

      // 更新CSRF token（如果响应头中有）
      const newCsrf = res.headers.get('X-CSRF-Token');
      if (newCsrf) _csrfToken = newCsrf;

      // 处理 401 未认证
      if (res.status === 401) {
        if (_on401) _on401();
        throw new Error('认证已过期，请重新登录');
      }

      // 处理非 JSON 响应（如图片快照）
      if (raw) return res;

      const data = await res.json();

      if (!res.ok) {
        const msg = data.detail || data.message || `请求失败 (${res.status})`;
        throw new Error(msg);
      }

      return data;
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') {
        throw new Error('请求超时，请检查网络连接');
      }
      throw err;
    }
  }

  // ── 便捷方法 ──
  const get = (path, opts) => request('GET', path, opts);
  const post = (path, opts) => request('POST', path, opts);
  const put = (path, opts) => request('PUT', path, opts);
  const del = (path, opts) => request('DELETE', path, opts);

  // ── 公开 API ──
  return {
    /** 设置认证失效回调 */
    onAuthExpired(cb) { _on401 = cb; },

    // ─── 系统 ───
    system: {
      info: () => get('/system/info'),
      resources: () => get('/system/resources'),
      uptime: () => get('/system/uptime'),
      version: () => get('/system/version'),
      updateNetwork: (cfg) => put('/system/network', { body: cfg }),
      restartService: (svc) => post(`/system/restart?service=${svc}`),
    },

    // ─── 摄像头 ───
    cameras: {
      list: () => get('/cameras'),
      get: (id) => get(`/cameras/${id}`),
      create: (data) => post('/cameras', { body: data }),
      update: (id, data) => put(`/cameras/${id}`, { body: data }),
      delete: (id) => del(`/cameras/${id}`),
      reconnect: (id) => post(`/cameras/${id}/reconnect`),
      snapshot: (id) => get(`/cameras/${id}/snapshot`, { raw: true }),
    },

    // ─── IoT 传感器 ───
    iot: {
      sensors: () => get('/iot/sensors'),
      getSensor: (id) => get(`/iot/sensors/${id}`),
      create: (data) => post('/iot/sensors', { body: data }),
      update: (id, data) => put(`/iot/sensors/${id}`, { body: data }),
      delete: (id) => del(`/iot/sensors/${id}`),
      history: (id, hours) => get(`/iot/sensors/${id}/history?hours=${hours || 24}`),
    },

    // ─── 引擎 ───
    engines: {
      status: () => get('/engines/status'),
      getEngine: (name) => get(`/engines/${name}/status`),
      restart: (name) => post(`/engines/${name}/restart`),
      logs: (name) => get(`/engines/${name}/logs`),
    },

    // ─── 诊断 ───
    diagnostics: {
      run: () => post('/diagnostics/run'),
      getTask: (taskId) => get(`/diagnostics/tasks/${taskId}`),
      network: () => get('/diagnostics/network'),
      cameras: () => get('/diagnostics/cameras'),
    },

    // ─── 初始化 ───
    setup: {
      initialize: (data) => post('/setup/initialize', { body: data }),
      status: () => get('/setup/status'),
    },

    // ─── OTA ───
    ota: {
      check: () => post('/ota/check'),
      upgrade: () => post('/ota/upgrade'),
      status: () => get('/ota/status'),
    },

    // ─── 模型 ───
    models: {
      list: () => get('/models'),
      download: (name) => post(`/models/download?name=${name}`),
      delete: (name) => del(`/models/${name}`),
      activate: (name) => post(`/models/${name}/activate`),
    },

    // ─── 日志 ───
    logs: {
      list: (params) => get('/logs', { query: params }),
      tail: () => get('/logs/tail'),
    },

    // ─── 配置管理 (v1.1) ───
    config: {
      getAll: () => get('/config'),                    // 获取全部配置(脱敏)
      updateDevice: (cfg) => put('/config/device', { body: cfg }),  // 更新设备配置
      updateCameras: (cfg) => put('/config/cameras', { body: cfg }), // 更新摄像头配置
      updateHub: (cfg) => put('/config/hub', { body: cfg }),         // 更新Hub连接配置
      reload: () => post('/config/reload'),             // 重新加载配置
    },

    // ─── 平台状态 (v1.1, 只读) ───
    platform: {
      status: () => get('/platform/status'),           // 平台连接状态
      heartbeatDetail: () => get('/platform/heartbeat-detail'), // 心跳详情
      queueStatus: () => get('/platform/queue-status'), // 队列状态
    },

    // ─── 摄像头扩展 (v1.1) ───
    cameras: {
      list: () => get('/cameras'),
      get: (id) => get(`/cameras/${id}`),
      create: (data) => post('/cameras', { body: data }),
      update: (id, data) => put(`/cameras/${id}`, { body: data }),
      delete: (id) => del(`/cameras/${id}`),
      reconnect: (id) => post(`/cameras/${id}/reconnect`),
      snapshot: (id, fmt) => get(`/cameras/${id}/snapshot${fmt ? `?format=${fmt}` : ''}`, { raw: true }),
      test: (id) => post(`/cameras/${id}/test`),        // 测试连接 (v1.1)
    },
  };
})();
