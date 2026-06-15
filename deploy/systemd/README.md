# systemd 边缘/云端服务单元（DEV-104）

将本目录单元文件安装到试点店边缘盒或云主机：

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Event Hub
sudo systemctl enable --now hotpot-hub.service

# 看板
sudo systemctl enable --now hotpot-dashboard.service

# 按门店启动视觉 worker（%i = store_id）
sudo systemctl enable --now hotpot-vision@store_yuhuan.service
sudo systemctl enable --now hotpot-vision@store_jiaojiang.service

# POS 同步（每 5 分钟）
sudo systemctl enable --now hotpot-pos@store_yuhuan.service
```

## 健康检查

```bash
python3 scripts/edge_health.py --store-id store_yuhuan --hub-url http://127.0.0.1:8088
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `HOTPOT_HUB_URL` | 视觉 worker 上报地址 |
| `HOTPOT_DATABASE_URL` | Hub PostgreSQL（可选） |
| `HOTPOT_RKNN_MODEL` | RKNN 模型路径 |

默认工作目录：`/opt/hotpot_smart_ops`（部署时按实际路径修改 `WorkingDirectory`）。
