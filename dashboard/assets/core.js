/** Hotpot Smart Ops MVP - shared client */
const HotpotApp = (() => {
  const HUB_KEY = "hotpot_hub_url";
  const AUTH_KEY = "hotpot_auth";
  const AUTH_COOKIE = "hotpot_auth";
  const ACK_KEY = "hotpot_acked_events";
  const ADMIN_ORIGIN_KEY = "hotpot_admin_origin";
  const OPS_ORIGIN_KEY = "hotpot_ops_origin";
  let hubAckedIds = new Set();

  function currentOrigin() {
    const { protocol, hostname, port } = window.location;
    return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
  }

  /** 记录双端口部署（nginx :3000 业务 / :3001 运营后台） */
  function syncDeploymentOrigins(opts = {}) {
    const { protocol, hostname, port } = window.location;
    if (opts.admin === true || port === "3001") {
      localStorage.setItem(ADMIN_ORIGIN_KEY, `${protocol}//${hostname}:3001`);
      localStorage.setItem(OPS_ORIGIN_KEY, `${protocol}//${hostname}:3000`);
    } else if (opts.combined === true) {
      localStorage.removeItem(ADMIN_ORIGIN_KEY);
      localStorage.removeItem(OPS_ORIGIN_KEY);
    }
  }

  function adminOrigin() {
    const stored = localStorage.getItem(ADMIN_ORIGIN_KEY);
    if (stored) return stored.replace(/\/$/, "");
    if (window.location.port === "3001") {
      return currentOrigin();
    }
    if (new URLSearchParams(window.location.search).get("admin") === "1" && window.location.port === "3000") {
      const { protocol, hostname } = window.location;
      return `${protocol}//${hostname}:3001`;
    }
    return currentOrigin();
  }

  function opsOrigin() {
    const stored = localStorage.getItem(OPS_ORIGIN_KEY);
    if (stored) return stored.replace(/\/$/, "");
    if (window.location.port === "3001") {
      const { protocol, hostname } = window.location;
      return `${protocol}//${hostname}:3000`;
    }
    return currentOrigin();
  }

  /** 运营后台页面 URL（双端口时跳到 :3001） */
  function adminPageUrl(relativePath = "admin/index.html") {
    const rel = relativePath.replace(/^\//, "");
    const admin = adminOrigin();
    const here = currentOrigin();
    if (admin === here) return rel;
    return `${admin}/${rel}`;
  }

  function hubUrl() {
    const stored = localStorage.getItem(HUB_KEY);
    if (stored) return stored.replace(/\/$/, "");
    const port = window.location.port;
    if (port === "3000" || port === "3001") {
      return `${currentOrigin()}/api`;
    }
    return "http://127.0.0.1:8088";
  }

  function setHubUrl(url) {
    localStorage.setItem(HUB_KEY, url.replace(/\/$/, ""));
  }

  function readAuthCookie() {
    const match = document.cookie.match(/(?:^|;\s*)hotpot_auth=([^;]*)/);
    if (!match) return null;
    try {
      return JSON.parse(decodeURIComponent(match[1]));
    } catch {
      return null;
    }
  }

  function writeAuthCookie(user) {
    const payload = encodeURIComponent(JSON.stringify(user));
    document.cookie = `${AUTH_COOKIE}=${payload}; path=/; max-age=86400; SameSite=Lax`;
  }

  function clearAuthCookie() {
    document.cookie = `${AUTH_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
  }

  function getAuth() {
    try {
      const raw = sessionStorage.getItem(AUTH_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed) return parsed;
      }
    } catch {
      /* ignore */
    }
    const fromCookie = readAuthCookie();
    if (fromCookie) {
      sessionStorage.setItem(AUTH_KEY, JSON.stringify(fromCookie));
      return fromCookie;
    }
    return null;
  }

  function setAuth(user) {
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(user));
    writeAuthCookie(user);
  }

  const STATE_LABELS = {
    empty: "空桌",
    dining: "用餐中",
    need_clean: "待清台",
    checkout: "待结账",
  };

  function loginPageUrl() {
    const path = window.location.pathname || "";
    // 运营后台端口：同端口登录，避免 session 隔离导致死循环
    if (window.location.port === "3001") {
      return "/login.html?admin=1";
    }
    if (localStorage.getItem(ADMIN_ORIGIN_KEY)) {
      return `${opsOrigin()}/login.html?admin=1`;
    }
    if (path.includes("/admin/") || path.includes("/pda/") || path.includes("/mobile/")) {
      return "../login.html";
    }
    return "login.html";
  }

  function logout() {
    sessionStorage.removeItem(AUTH_KEY);
    clearAuthCookie();
    window.location.href = loginPageUrl();
  }

  function requireAuth() {
    const auth = getAuth();
    if (!auth) {
      window.location.href = loginPageUrl();
      return null;
    }
    return auth;
  }

  function getAckedIds() {
    try {
      return new Set(JSON.parse(localStorage.getItem(ackStorageKey()) || "[]"));
    } catch {
      return new Set();
    }
  }

  function isAcked(eventId) {
    return getAckedIds().has(eventId) || hubAckedIds.has(eventId);
  }

  async function syncHubAcks() {
    try {
      const data = await fetchAlertAcks();
      hubAckedIds = new Set((data.acks || []).map((a) => a.event_id));
    } catch {
      hubAckedIds = new Set();
    }
  }

  async function ackEvent(eventId, ackNote = "") {
    const ids = getAckedIds();
    ids.add(eventId);
    localStorage.setItem(ackStorageKey(), JSON.stringify([...ids]));
    hubAckedIds.add(eventId);
    const auth = getAuth();
    try {
      await fetch(`${hubUrl()}/v1/alerts/ack`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          event_id: eventId,
          store_id: storeId(),
          ack_by: auth?.name || auth?.username || "店长",
          ack_note: ackNote,
        }),
      });
    } catch (e) {
      console.warn("Hub ack sync failed", e);
    }
  }

  function getToken() {
    return getAuth()?.token || "";
  }

  let RBAC_MATRIX = null;

  const NAV_PAGES = {
    home: "home.html",
    tables: "tables.html",
    kitchen: "kitchen.html",
    sop: "sop.html",
    cost: "cost.html",
    alerts: "alerts.html",
    report: "report.html",
    pda: "pda/receiving.html",
    regional: "regional.html",
    cockpit: "cockpit.html",
    system: "system.html",
    admin: "admin/index.html",
    admin_stores: "admin/stores.html",
    admin_pipeline: "admin/pipeline.html",
  };

  async function loadRbac() {
    if (RBAC_MATRIX) return RBAC_MATRIX;
    try {
      const base = window.location.pathname.replace(/[^/]+$/, "");
      const res = await fetch(base + "assets/rbac.json");
      RBAC_MATRIX = await res.json();
    } catch {
      RBAC_MATRIX = { roles: {} };
    }
    return RBAC_MATRIX;
  }

  function canAccessMenu(role, navKey) {
    if (!RBAC_MATRIX?.roles?.[role]) return true;
    return (RBAC_MATRIX.roles[role].menus || []).includes(navKey);
  }

  function canAction(role, action) {
    if (!RBAC_MATRIX?.roles?.[role]) return true;
    return (RBAC_MATRIX.roles[role].actions || []).includes(action);
  }

  async function applyRbac(auth, activeNav) {
    await loadRbac();
    document.querySelectorAll(".nav-item[data-nav]").forEach((el) => {
      const nav = el.dataset.nav;
      el.style.display = canAccessMenu(auth.role, nav) ? "" : "none";
    });
    if (activeNav && !canAccessMenu(auth.role, activeNav)) {
      const first = RBAC_MATRIX?.roles?.[auth.role]?.menus?.[0];
      if (first && NAV_PAGES[first]) window.location.href = NAV_PAGES[first];
    }
  }

  function authHeaders(extra = {}) {
    const headers = { ...extra };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  function storeId() {
    return getAuth()?.storeId || "store_yuhuan";
  }

  async function hubLogin(username, password, storeIdVal, role) {
    const res = await fetch(`${hubUrl()}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: username || "zhangdian",
        password: password || "demo",
        store_id: storeIdVal || "store_yuhuan",
        role: role || "店长",
      }),
    });
    if (!res.ok) throw new Error("Hub 登录失败: " + res.statusText);
    return res.json();
  }

  function storeQuery(extra = "") {
    const q = `store_id=${encodeURIComponent(storeId())}`;
    return extra ? `${q}&${extra}` : q;
  }

  function ackStorageKey() {
    return `${ACK_KEY}_${storeId()}`;
  }

  async function fetchSummary() {
    const res = await fetch(`${hubUrl()}/v1/summary?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchHealth() {
    const res = await fetch(`${hubUrl()}/health`);
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchMetrics() {
    const res = await fetch(`${hubUrl()}/metrics`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function askSop(question, backend = "rule") {
    const res = await fetch(`${hubUrl()}/v1/sop/ask`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question, backend, top_k: 3 }),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAlertPushes(limit = 20) {
    const res = await fetch(`${hubUrl()}/v1/alerts/push-log?${storeQuery(`limit=${limit}`)}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAlertAcks() {
    const res = await fetch(`${hubUrl()}/v1/alerts/acks?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchEscalations() {
    const res = await fetch(`${hubUrl()}/v1/alerts/escalations?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchEvents(limit = 30) {
    const res = await fetch(`${hubUrl()}/v1/events?${storeQuery(`limit=${limit}`)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchStores() {
    const res = await fetch(`${hubUrl()}/v1/stores`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchSopAssignments(status = "") {
    const q = storeQuery(status ? `status=${encodeURIComponent(status)}` : "");
    const res = await fetch(`${hubUrl()}/v1/sop/assignments?${q}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function assignSop({ sop_id, sop_name, assignee, event_id, note }) {
    const auth = getAuth();
    const res = await fetch(`${hubUrl()}/v1/sop/assign`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        store_id: auth?.store_id,
        sop_id,
        sop_name,
        assignee: assignee || "厨师长",
        event_id,
        note: note || "",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  async function updateSopAssignmentStatus(assignmentId, status) {
    const auth = getAuth();
    const res = await fetch(`${hubUrl()}/v1/sop/assignments/${assignmentId}/status`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ status, store_id: auth?.store_id }),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchIotReadings(sensorId = "cold_storage_1", hours = 24) {
    const q = storeQuery(`sensor_id=${encodeURIComponent(sensorId)}&hours=${hours}`);
    const res = await fetch(`${hubUrl()}/v1/iot/readings?${q}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAuditForStore(targetStoreId) {
    const res = await fetch(
      `${hubUrl()}/v1/audit/acks?store_id=${encodeURIComponent(targetStoreId)}`,
      { headers: authHeaders() }
    );
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchErp() {
    const res = await fetch(`${hubUrl()}/v1/erp?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAlertRoutes(targetStoreId = "") {
    const q = targetStoreId
      ? `store_id=${encodeURIComponent(targetStoreId)}`
      : storeQuery();
    const res = await fetch(`${hubUrl()}/v1/alerts/routes?${q}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchDailyReports(limit = 30, reportDate = "") {
    let extra = `limit=${limit}`;
    if (reportDate) extra += `&report_date=${encodeURIComponent(reportDate)}`;
    const res = await fetch(`${hubUrl()}/v1/reports/daily?${storeQuery(extra)}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function generateDailyReport(push = false) {
    const auth = getAuth();
    const res = await fetch(`${hubUrl()}/v1/reports/daily/generate`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ store_id: auth?.store_id, push }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  async function vlmQualityGrade(sku, batchId = "", imageBase64 = "") {
    const vlmBase = hubUrl().replace(":8088", ":8089");
    const body = { sku, batch_id: batchId };
    if (imageBase64) body.image_base64 = imageBase64;
    const res = await fetch(`${vlmBase}/quality-grade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchRegionOverview(regionId = "") {
    const q = regionId ? `region_id=${encodeURIComponent(regionId)}` : "";
    const res = await fetch(`${hubUrl()}/v1/region/overview${q ? "?" + q : ""}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchBenchmark() {
    const res = await fetch(`${hubUrl()}/v1/benchmark`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchNationalOverview() {
    const res = await fetch(`${hubUrl()}/v1/national/overview`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAuthMe() {
    const res = await fetch(`${hubUrl()}/v1/auth/me`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAdminOrgTree() {
    const res = await fetch(`${hubUrl()}/v1/admin/org-tree`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Admin API: " + res.statusText);
    return res.json();
  }

  async function fetchAdminStores() {
    const res = await fetch(`${hubUrl()}/v1/admin/stores`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Admin API: " + res.statusText);
    return res.json();
  }

  async function createAdminStore(payload) {
    const res = await fetch(`${hubUrl()}/v1/admin/stores`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  async function updateAdminStore(storeId, payload) {
    const res = await fetch(`${hubUrl()}/v1/admin/stores/${encodeURIComponent(storeId)}`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAdminPipelineStatus() {
    const res = await fetch(`${hubUrl()}/v1/admin/pipeline/status`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function adminPipelineTick(opts = {}) {
    const res = await fetch(`${hubUrl()}/v1/admin/pipeline/tick`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        store_id: opts.store_id || null,
        mode: opts.mode || "inprocess",
        inject_anomaly: !!opts.inject_anomaly,
        hub_url: hubUrl(),
      }),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAdminAuditLogs(limit = 20) {
    const res = await fetch(`${hubUrl()}/v1/admin/audit-logs?limit=${limit}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  function initAdminShell(activeNav) {
    syncDeploymentOrigins({ admin: true });
    const auth = requireAuth();
    if (!auth) return null;
    if (auth.role !== "总部PMO" && auth.role !== "总部 IT") {
      window.location.href = loginPageUrl();
      return null;
    }
    document.querySelectorAll(".nav-item[data-nav]").forEach((el) => {
      if (el.dataset.nav === activeNav) el.classList.add("active");
    });
    const userEl = document.getElementById("user-name");
    if (userEl) userEl.textContent = auth.name + "（" + auth.role + "）";
    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn) logoutBtn.onclick = logout;
    const hubInput = document.getElementById("hub-url");
    if (hubInput) {
      hubInput.value = hubUrl();
      hubInput.onchange = () => setHubUrl(hubInput.value);
    }
    return auth;
  }

  const STORE_OPTIONS = [
    { id: "store_yuhuan", name: "冯校长火锅·玉环店" },
    { id: "store_jiaojiang", name: "冯校长火锅·椒江店" },
  ];

  function switchStore(storeId, storeName) {
    const auth = getAuth();
    if (!auth) return;
    setAuth({ ...auth, storeId, storeName });
    window.location.reload();
  }

  function enhanceSidebar(activeNav, auth) {
    const sidebar = document.querySelector(".sidebar");
    if (!sidebar || sidebar.querySelector('[data-nav="regional"]')) return;
    const anchor = sidebar.querySelector('[data-nav="report"]');
    if (!anchor) return;
    const link = document.createElement("a");
    link.className = "nav-item" + (activeNav === "regional" ? " active" : "");
    link.dataset.nav = "regional";
    link.href = "regional.html";
    link.textContent = "区域 · 跨店对标";
    anchor.insertAdjacentElement("afterend", link);

    if (!sidebar.querySelector('[data-nav="system"]')) {
      const sys = document.createElement("a");
      sys.className = "nav-item" + (activeNav === "system" ? " active" : "");
      sys.dataset.nav = "system";
      sys.href = "system.html";
      sys.textContent = "系统状态";
      link.insertAdjacentElement("afterend", sys);
    }
  }

  function injectStoreSwitcher(auth) {
    if (auth.role === "区域督导" || auth.role === "集团决策者") return;
    const left = document.querySelector(".topbar-left");
    if (!left || document.getElementById("store-switch")) return;
    const sel = document.createElement("select");
    sel.id = "store-switch";
    sel.className = "store-switch";
    sel.title = "切换门店";
    STORE_OPTIONS.forEach((o) => {
      const opt = document.createElement("option");
      opt.value = o.id;
      opt.textContent = o.name.replace("冯校长火锅·", "");
      opt.selected = o.id === storeId();
      sel.appendChild(opt);
    });
    sel.onchange = () => {
      const picked = STORE_OPTIONS.find((o) => o.id === sel.value);
      if (picked) switchStore(picked.id, picked.name);
    };
    left.appendChild(sel);
  }

  function buildReport(summary) {
    const auth = getAuth();
    const storeTitle = auth?.storeName || "冯校长火锅·玉环店";
    const t = summary.table_state_counts || {};
    const ev = summary.by_level || {};
    const sop = summary.sop_stats || {};
    const cost = summary.cost_stats || {};
    const suggestions = summary.turnover_suggestions || [];
    const lines = [
      `# ${storeTitle} 运营日报`,
      "生成时间: " + new Date().toLocaleString("zh-CN"),
      "",
      "## 前厅翻台",
      `空桌 ${t.empty || 0} | 用餐 ${t.dining || 0} | 待清台 ${t.need_clean || 0} | 待结账 ${t.checkout || 0}`,
      "",
      "## 后厨 SOP",
      sop.compliance_rate != null
        ? `合规率 ${sop.compliance_rate}% (${sop.passed || 0}/${sop.total || 0})`
        : "暂无数据",
      "",
      "## 来料成本",
      cost.variance_rate_pct != null
        ? `偏差 ${cost.variance_rate_pct}% | PO ¥${cost.total_po_amount || 0} → 实收 ¥${cost.total_actual_amount || 0}`
        : "暂无数据",
      "",
      "## 告警统计",
      `严重 ${ev.critical || 0} | 警告 ${ev.warn || 0} | 信息 ${ev.info || 0}`,
      "",
      "## 翻台建议",
    ];
    suggestions.slice(0, 5).forEach((s) => {
      lines.push(`- ${s.table_id} [${s.state}] → ${s.action}`);
    });
    lines.push("", "## 改进建议");
    if ((t.need_clean || 0) >= 2) lines.push("- 增配保洁，缩短清台等待");
    if ((ev.critical || 0) > 0) lines.push("- 立即处理冷链/燃气/烟雾严重告警");
    if ((sop.failed || 0) > 0) lines.push("- 补录未达标 SOP 并班组长复盘");
    if ((cost.variance_rate_pct || 0) > 3) lines.push("- 来料成本偏差超标，启动供应商对账");
    if (lines.length < 20) lines.push("- 运营态势平稳，继续监控");
    return lines.join("\n");
  }

  function renderTableGrid(container, states, onClick) {
    container.innerHTML = "";
    if (!states || !Object.keys(states).length) {
      for (let i = 1; i <= 8; i++) {
        const id = "T" + String(i).padStart(2, "0");
        states = states || {};
        states[id] = { table_id: id, state: "empty" };
      }
    }
    Object.values(states)
      .sort((a, b) => a.table_id.localeCompare(b.table_id))
      .forEach((t) => {
        const div = document.createElement("div");
        div.className = "table-cell " + (t.state || "empty");
        div.innerHTML = `<div>${t.table_id}</div><div class="table-label">${STATE_LABELS[t.state] || t.state}</div>`;
        if (onClick) div.onclick = () => onClick(t);
        container.appendChild(div);
      });
  }

  function renderEvents(container, events, opts = {}) {
    const { filter = "all", showAck = false, onAck } = opts;
    container.innerHTML = "";
    let list = events || [];
    if (filter !== "all") list = list.filter((e) => e.level === filter);
    if (!list.length) {
      container.innerHTML = '<p style="color:var(--muted)">暂无事件</p>';
      return;
    }
    list.forEach((ev) => {
      const id = ev.event_id || ev.timestamp + ev.event_type;
      const isAckedFlag = isAcked(id);
      const div = document.createElement("div");
      div.className = "event " + (ev.level || "info") + (isAckedFlag ? " acked" : "");
      div.innerHTML = `<strong>${ev.event_type}</strong> · ${ev.message}
        <div class="event-meta">${ev.source} · ${ev.timestamp || ""}${isAckedFlag ? " · 已确认" : ""}</div>`;
      if (showAck && !isAckedFlag && ev.level !== "info" && onAck) {
        const auth = getAuth();
        if (canAction(auth?.role, "ack")) {
        const actions = document.createElement("div");
        actions.className = "event-actions";
        const btn = document.createElement("button");
        btn.className = "btn btn-sm";
        btn.textContent = "确认已处理";
        btn.onclick = async () => {
          btn.disabled = true;
          await ackEvent(id);
          await onAck(id);
          renderEvents(container, events, opts);
        };
        actions.appendChild(btn);
        div.appendChild(actions);
        }
      }
      container.appendChild(div);
    });
  }

  function renderWechatPreview(container, pushes) {
    container.innerHTML = "";
    const list = pushes || [];
    if (!list.length) {
      container.innerHTML = '<p style="color:var(--muted)">暂无企微推送记录（严重告警将自动推送）</p>';
      return;
    }
    list.forEach((p) => {
      const card = document.createElement("div");
      card.className = "wechat-card " + (p.level || "info");
      const lines = (p.body || "").split("\n");
      card.innerHTML = `
        <div class="wechat-card-header">
          <span class="wechat-badge">企微</span>
          <span class="wechat-time">${p.created_at || ""}</span>
        </div>
        <div class="wechat-title">${p.title || "告警通知"}</div>
        <div class="wechat-body">${lines.map((l) => `<div>${l}</div>`).join("")}</div>
      `;
      container.appendChild(card);
    });
  }

  function guardAction(role, action, el) {
    if (!el) return;
    if (!canAction(role, action)) {
      el.disabled = true;
      el.title = "当前角色无此操作权限";
      el.classList.add("rbac-disabled");
    }
  }

  async function initPdaShell() {
    await loadRbac();
    const auth = requireAuth();
    if (!auth) return null;
    if (!canAccessMenu(auth.role, "pda")) {
      const first = RBAC_MATRIX?.roles?.[auth.role]?.menus?.[0];
      window.location.href = first && NAV_PAGES[first] ? NAV_PAGES[first] : loginPageUrl();
      return null;
    }
    return auth;
  }

  function initShell(activeNav) {
    const auth = requireAuth();
    if (!auth) return null;

    document.querySelectorAll(".nav-item[data-nav]").forEach((el) => {
      if (el.dataset.nav === activeNav) el.classList.add("active");
    });

    enhanceSidebar(activeNav, auth);
    injectStoreSwitcher(auth);
    loadRbac().then(() => applyRbac(auth, activeNav));

    const storeEl = document.getElementById("store-name");
    if (storeEl) storeEl.textContent = auth.storeName || "冯校长火锅·玉环店";

    const userEl = document.getElementById("user-name");
    if (userEl) userEl.textContent = auth.name + "（" + auth.role + "）";

    const logoutBtn = document.getElementById("btn-logout");
    if (logoutBtn) logoutBtn.onclick = logout;

    const hubInput = document.getElementById("hub-url");
    if (hubInput) {
      hubInput.value = hubUrl();
      hubInput.onchange = () => setHubUrl(hubInput.value);
    }

    const connEl = document.getElementById("conn-status");
    if (connEl) {
      fetchSummary()
        .then(() => {
          connEl.innerHTML = '<span class="status-dot online"></span>已连接';
        })
        .catch((e) => {
          connEl.innerHTML = '<span class="status-dot offline"></span>未连接';
        });
    }

    return auth;
  }

  function countUnackedCritical(events) {
    return (events || []).filter(
      (e) =>
        (e.level === "critical" || e.level === "warn") &&
        !isAcked(e.event_id || e.timestamp + e.event_type)
    ).length;
  }

  return {
    hubUrl,
    setHubUrl,
    adminPageUrl,
    syncDeploymentOrigins,
    opsOrigin,
    adminOrigin,
    getAuth,
    setAuth,
    logout,
    requireAuth,
    storeId,
    hubLogin,
    fetchSummary,
    fetchHealth,
    fetchMetrics,
    askSop,
    assignSop,
    fetchSopAssignments,
    updateSopAssignmentStatus,
    fetchIotReadings,
    fetchAuditForStore,
    fetchEvents,
    fetchAlertPushes,
    fetchAlertRoutes,
    fetchAlertAcks,
    fetchEscalations,
    syncHubAcks,
    fetchStores,
    fetchBenchmark,
    fetchRegionOverview,
    fetchNationalOverview,
    fetchAuthMe,
    fetchAdminOrgTree,
    fetchAdminStores,
    createAdminStore,
    updateAdminStore,
    fetchAdminPipelineStatus,
    adminPipelineTick,
    fetchAdminAuditLogs,
    initAdminShell,
    switchStore,
    buildReport,
    renderTableGrid,
    renderEvents,
    renderWechatPreview,
    initShell,
    loadRbac,
    canAccessMenu,
    canAction,
    guardAction,
    initPdaShell,
    authHeaders,
    fetchErp,
    fetchDailyReports,
    generateDailyReport,
    vlmQualityGrade,
    countUnackedCritical,
    ackEvent,
    isAcked,
    STATE_LABELS,
  };
})();
