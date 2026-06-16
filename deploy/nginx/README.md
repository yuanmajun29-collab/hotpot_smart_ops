# Nginx · 业务平台与运营后台分离

**Phase 2 推荐部署方式**（Phase 1 可继续 `python3 dashboard/serve.py --port 3000`）

| 方案 | 配置文件 | 适用 |
|------|----------|------|
| **同域路径** | `combined.conf` | 试点、内网单域名 |
| **子域分离**（推荐） | `split-subdomain.conf` | 20 店+、SSO/WAF 分治 |
| **端口分离** | `split-ports.conf` | 无 DNS、防火墙按端口控 |

**前提**：`dashboard/admin/` 页面使用 `../assets/`，生产环境请**保留 `/admin/` 路径前缀**（子域方案用 `admin.example.com/admin/`），或统一反代到同一 `dashboard` 根目录。

**Hub API** 默认 `:8088`，可按需在同域增加 `/api/` 反代（示例见各 conf 注释）。

---

## 1. 同域路径（Phase 1 延续）

```
https://ops.example.com/           → 门店看板 login/home
https://ops.example.com/admin/     → 运营后台
https://ops.example.com/regional.html → 层级看板
```

```bash
# 安装后
sudo cp combined.conf /etc/nginx/conf.d/hotpot-ops.conf
# 修改 root、server_name、ssl 证书路径
sudo nginx -t && sudo systemctl reload nginx
```

开发机可不启 nginx，继续：

```bash
python3 dashboard/serve.py --port 3000
```

---

## 2. 子域分离（Phase 2 推荐）

```
https://ops.example.com/              → 业务平台（禁止 /admin/）
https://admin.example.com/admin/      → 运营后台
https://api.example.com/  (可选)      → Hub :8088
```

**DNS**：`ops`、`admin`（及可选 `api`）A 记录指向同一台或 LB。

**门店网络策略示例**：
- 门店 WiFi：仅允许访问 `ops.example.com`
- 总部办公网：允许 `admin.example.com`

---

## 3. 端口分离（内网备选）

```
http://<host>:3000/        → 业务平台（nginx 拒绝 /admin/）
http://<host>:3001/admin/  → 运营后台 + /assets/
```

防火墙：`3001` 仅总部网段可入。

与 systemd 配合时可保留单进程 `serve.py :3000`，由 **nginx 静态托管** `dashboard/`（见 conf），无需两个 Python 进程。

---

## 4. 与 systemd 服务关系

| 服务 | 端口 | 说明 |
|------|------|------|
| `hotpot-hub.service` | 8088 | Event Hub API |
| `hotpot-dashboard.service` | 3000 | Phase 1 开发用；生产可改为 nginx 静态 |
| nginx | 80/443 | 生产入口 |

生产建议：**nginx 直接托管静态文件**，停掉 `hotpot-dashboard.service`，减轻 Python 静态服务占用。

---

## 5. 本地验证

### 5.1 双端口（已验证）

```bash
./deploy/nginx/run_local_split_ports_test.sh
```

| 检查项 | :3000 业务 | :3001 运营后台 |
|--------|------------|----------------|
| login / admin | login 200，**admin 403** | admin 200，home **403** |
| 根路径 | — | 302 → `/admin/index.html` |
| Hub 反代 | `/api/health` → ok | 同左 |
| 登录跳转 | — | 302 → `:3000/login.html?admin=1` |

停止 nginx、恢复 Python 看板：

```bash
nginx -s stop -c deploy/nginx/local-test-main.conf -p /tmp/hotpot-nginx
python3 dashboard/serve.py --port 3000
```

### 5.2 子域（/etc/hosts）

```
127.0.0.1 ops.hotpot.local admin.hotpot.local
```

按 `split-subdomain.conf` 配置系统 nginx 后访问：

- http://ops.hotpot.local/login.html
- http://admin.hotpot.local/admin/index.html

---

## 6. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-06-16 | 初版：combined / split-subdomain / split-ports |
