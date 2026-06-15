/** Hotpot Smart Ops MVP - shared client */
const HotpotApp = (() => {
  const HUB_KEY = "hotpot_hub_url";
  const AUTH_KEY = "hotpot_auth";
  const ACK_KEY = "hotpot_acked_events";
  let hubAckedIds = new Set();

  const STATE_LABELS = {
    empty: "空桌",
    dining: "用餐中",
    need_clean: "待清台",
    checkout: "待结账",
  };

  function hubUrl() {
    return (localStorage.getItem(HUB_KEY) || "http://127.0.0.1:8088").replace(/\/$/, "");
  }

  function setHubUrl(url) {
    localStorage.setItem(HUB_KEY, url.replace(/\/$/, ""));
  }

  function getAuth() {
    try {
      return JSON.parse(sessionStorage.getItem(AUTH_KEY) || "null");
    } catch {
      return null;
    }
  }

  function setAuth(user) {
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(user));
  }

  function logout() {
    sessionStorage.removeItem(AUTH_KEY);
    window.location.href = "login.html";
  }

  function requireAuth() {
    const auth = getAuth();
    if (!auth) {
      window.location.href = "login.html";
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
      await fetch(`${hubUrl()}/alerts/ack`, {
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
    const res = await fetch(`${hubUrl()}/summary?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAlertPushes(limit = 20) {
    const res = await fetch(`${hubUrl()}/alerts/push-log?${storeQuery(`limit=${limit}`)}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchAlertAcks() {
    const res = await fetch(`${hubUrl()}/alerts/acks?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchEscalations() {
    const res = await fetch(`${hubUrl()}/alerts/escalations?${storeQuery()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchEvents(limit = 30) {
    const res = await fetch(`${hubUrl()}/events?${storeQuery(`limit=${limit}`)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchStores() {
    const res = await fetch(`${hubUrl()}/stores`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
  }

  async function fetchBenchmark() {
    const res = await fetch(`${hubUrl()}/benchmark`, { headers: authHeaders() });
    if (!res.ok) throw new Error(res.statusText);
    return res.json();
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
  }

  function injectStoreSwitcher(auth) {
    if (auth.role === "区域督导") return;
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

  function initShell(activeNav) {
    const auth = requireAuth();
    if (!auth) return null;

    document.querySelectorAll(".nav-item[data-nav]").forEach((el) => {
      if (el.dataset.nav === activeNav) el.classList.add("active");
    });

    enhanceSidebar(activeNav, auth);
    injectStoreSwitcher(auth);

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
    getAuth,
    setAuth,
    logout,
    requireAuth,
    storeId,
    hubLogin,
    fetchSummary,
    fetchEvents,
    fetchAlertPushes,
    fetchAlertAcks,
    fetchEscalations,
    syncHubAcks,
    fetchStores,
    fetchBenchmark,
    switchStore,
    buildReport,
    renderTableGrid,
    renderEvents,
    renderWechatPreview,
    initShell,
    countUnackedCritical,
    ackEvent,
    isAcked,
    STATE_LABELS,
  };
})();
