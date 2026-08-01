#!/usr/bin/env python3
"""火瞳平台端 — 云端演示服务器（轻量版）

内置 Mock API，无需外部依赖，单文件启动
适合展会演示 / CloudStudio 部署 / 任何云服务器

用法:
    python cloud_demo.py [--port 8080]

访问:
    登录页: http://localhost:<port>/login.html
    首页:   http://localhost:<port>/home.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import random
import hashlib

# ============================================================
# 路径配置
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]  # hotpot_smart_ops/
DASHBOARD_DIR = PROJECT_ROOT / "hotpot_platform" / "dashboard"

# ============================================================
# Demo 数据生成器
# ============================================================

STORES = {
    "store_jiaojiang": {
        "store_id": "store_jiaojiang",
        "name": "冯校长火锅·椒江店",
        "region": "台州",
        "type": "flagship",
        "tables": 18,
        "address": "浙江省台州市椒江区",
        "manager": "张店长",
        "status": "active",
        "health_score": 92,
    },
    "store_yuhuan": {
        "store_id": "store_yuhuan",
        "name": "冯校长火锅·玉环店",
        "region": "台州",
        "type": "standard",
        "tables": 14,
        "address": "浙江省台州市玉环市",
        "manager": "李店长",
        "status": "active",
        "health_score": 78,
    },
}

USERS = {
    "zhangdian": {"username": "zhangdian", "password": "demo", "name": "张店长", "role": "店长", "store_id": "store_jiaojiang"},
    "lidian": {"username": "lidian", "password": "demo", "name": "李店长", "role": "店长", "store_id": "store_yuhuan"},
    "chushi": {"username": "chushi", "password": "demo", "name": "王厨师长", "role": "厨师长", "store_id": "store_jiaojiang"},
    "pangu": {"username": "pangu", "password": "demo", "name": "潘总", "role": "区域督导", "store_id": "store_jiaojiang"},
    "admin": {"username": "admin", "password": "admin", "name": "系统管理员", "role": "总部PMO", "store_id": "store_jiaojiang"},
}

SKU_LIST = [
    "毛肚", "鸭肠", "黄喉", "肥牛", "羊肉卷",
    "虾滑", "午餐肉", "土豆片", "莲藕", "娃娃菜",
    "腐竹", "金针菇", "宽粉", "鱼豆腐", "贡菜",
]

SUPPLIERS = ["蜀海供应链", "鑫源冻品", "绿源农业"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hours_ago(h: int) -> str:
    return (datetime.now() - timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")


def generate_summary(store_id: str = "store_jiaojiang") -> dict:
    """生成首页汇总数据"""
    store = STORES.get(store_id, list(STORES.values())[0])
    is_flagship = store["type"] == "flagship"

    return {
        "store_name": store["name"],
        "store_id": store_id,
        "timestamp": _now(),
        "health_score": store["health_score"],
        "table_state_counts": {
            "empty": random.randint(2, 6) if is_flagship else random.randint(1, 4),
            "dining": random.randint(8, 14) if is_flagship else random.randint(5, 10),
            "need_clean": random.randint(1, 3) if is_flagship else random.randint(1, 4),
            "checkout": random.randint(0, 2),
        },
        "by_level": {
            "critical": 0 if is_flagship else random.randint(0, 1),
            "warn": random.randint(0, 2),
            "info": random.randint(1, 4),
        },
        "sop_stats": {
            "total": random.randint(45, 60),
            "passed": random.randint(40, 56) if is_flagship else random.randint(35, 48),
            "failed": random.randint(2, 8) if not is_flagship else random.randint(1, 5),
            "compliance_rate": round(random.uniform(88, 97) if is_flagship else random.uniform(72, 88), 1),
            "today_checked": random.randint(12, 20),
        },
        "cost_stats": {
            "total_po_amount": round(random.uniform(8000, 15000), 0),
            "total_actual_amount": round(random.uniform(7800, 15200), 0),
            "variance_rate_pct": round(random.uniform(-2.5, 3.5), 2),
            "batches_today": random.randint(5, 12),
            "reject_count": 0 if is_flagship else random.randint(0, 2),
        },
        "turnover_suggestions": [
            {"table_id": f"T{str(i).zfill(2)}", "state": "need_clean", "action": "安排保洁清台"}
            for i in range(1, min(4, random.randint(1, 4)))
        ],
        "active_alerts": random.randint(0, 3),
    }


def generate_loss_risk(store_id: str = "store_jiaojiang", limit: int = 5) -> list:
    """生成损耗风险数据"""
    risks = []
    for i in range(min(limit, random.randint(2, 5))):
        sku = random.choice(SKU_LIST)
        risk_score = round(random.uniform(0.3, 0.95), 2)
        risks.append({
            "batch_id": f"B{datetime.now().strftime('%Y%m%d')}{i+1:03d}",
            "sku": sku,
            "supplier": random.choice(SUPPLIERS),
            "risk_score": risk_score,
            "risk_level": "高" if risk_score > 0.7 else ("中" if risk_score > 0.4 else "低"),
            "reason": random.choice(["短重超标", "品质等级偏低", "超温预警", "临近效期"]),
            "estimated_loss_amount": round(random.uniform(50, 500), 0),
            "suggested_action": "发起复称留证" if risk_score > 0.6 else "人工复核",
            "ref_id": f"RISK-{i+1:04d}",
            "task_id": None,
        })
    return risks


def generate_loss_budget(store_id: str = "store_jiaojiang", limit: int = 5) -> list:
    """生成备货预算建议"""
    items = []
    for i in range(min(limit, random.randint(3, 6))):
        items.append({
            "sku": random.choice(SKU_LIST),
            "forecast_qty": random.randint(15, 80),
            "forecast_unit": "份",
            "budget_loss_amount": round(random.uniform(30, 200), 0),
            "reason": random.choice(["周末预测上调", "历史均值偏高", "节假日因素"]),
            "suggested_action": "按建议量订货",
            "ref_id": f"BUDGET-{i+1:04d}",
        })
    return items


def generate_events(store_id: str = "store_jiaojiang", limit: int = 20) -> list:
    """生成事件列表"""
    event_types = [
        ("冷链超温", "critical", "冷库温度异常，当前-12°C"),
        ("SOP违规", "warn", "收货未按标准拍照留证"),
        ("短重预警", "warn", "毛肚到货偏差-3.2%"),
        ("设备离线", "info", "前厅3号桌传感器恢复在线"),
        ("燃气浓度", "critical", "后厨燃气浓度偏高"),
        ("烟雾报警", "warn", "后厨排烟系统效率下降"),
        ("品质降级", "warn", "鸭肠VLM评级为B级"),
        ("复称完成", "info", "批次B001复称完成，偏差正常"),
        ("SOP达标", "info", "今日SOP检查第18次通过"),
        ("库存预警", "info", "虾滑库存低于安全线"),
    ]
    events = []
    for i in range(limit):
        etype, level, msg = event_types[i % len(event_types)]
        events.append({
            "event_id": f"EVT-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
            "event_type": etype,
            "level": level,
            "message": msg,
            "source": random.choice(["IoT传感器", "VLM视觉", "SOP引擎", "收货PDA", "规则引擎"]),
            "timestamp": _hours_ago(random.randint(0, limit // 2)),
            "store_id": store_id,
        })
    return events


def generate_sop_assignments(store_id: str = "", status: str = "") -> list:
    """生成SOP任务列表"""
    assignments = [
        {"id": "SOP-001", "sop_id": "SOP-RCV-001", "sop_name": "收货验货拍照留证", "assignee": "王厨师长", "status": "pending", "created_at": _hours_ago(2)},
        {"id": "SOP-002", "sop_id": "SOP-KIT-003", "sop_name": "开档食材温度抽检", "assignee": "帮工A", "status": "in_progress", "created_at": _hours_ago(1)},
        {"id": "SOP-003", "sop_id": "SOP-CLN-002", "sop_name": "操作台清洁消毒", "assignee": "帮工B", "status": "passed", "created_at": _hours_ago(3)},
        {"id": "SOP-004", "sop_id": "SOP-STO-001", "sop_name": "冻品入库分类存放", "assignee": "王厨师长", "status": "failed", "created_at": _hours_ago(5)},
        {"id": "SOP-005", "sop_id": "SOP-TEMP-001", "sop_name": "冷库温度记录", "assignee": "张店长", "status": "passed", "created_at": _hours_ago(6)},
    ]
    if status:
        assignments = [a for a in assignments if a["status"] == status]
    return assignments


def generate_iot_readings(sensor_id: str = "cold_storage_1", hours: int = 24) -> list:
    """生成IoT温度读数"""
    readings = []
    base_temp = -18.0 if "cold" in sensor_id else 4.0
    for i in range(hours * 2):  # 每30分钟一个点
        t = datetime.now() - timedelta(minutes=30 * i)
        temp = base_temp + random.uniform(-1.5, 1.5)
        readings.append({
            "sensor_id": sensor_id,
            "temperature": round(temp, 1),
            "humidity": round(random.uniform(65, 85), 1) if "cold" in sensor_id else None,
            "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "normal" if abs(temp - base_temp) < 2 else "alert",
        })
    return readings


def generate_iot_devices(required_only: bool = True) -> list:
    """生成IoT设备列表"""
    devices = [
        {"device_id": "cold_storage_1", "name": "一号冷库", "type": "temperature", "status": "online", "last_reading": _now(), "battery": 87},
        {"device_id": "cold_storage_2", "name": "二号冷库", "type": "temperature", "status": "online", "last_reading": _now(), "battery": 92},
        {"device_id": "freezer_1", "name": "速冻柜", "type": "temperature", "status": "online", "last_reading": _now(), "battery": 65},
        {"device_id": "gas_1", "name": "燃气探测器", "type": "gas", "status": "online", "last_reading": _now(), "battery": 100},
        {"device_id": "smoke_1", "name": "烟雾探测器", "type": "smoke", "status": "online", "last_reading": _now(), "battery": 95},
        {"device_id": "cam_kitchen_1", "name": "后厨摄像头A", "type": "camera", "status": "online", "last_reading": _now()},
        {"device_id": "cam_receiving_1", "name": "收货区摄像头", "type": "camera", "status": "offline", "last_reading": _hours_ago(2)},
    ]
    if required_only:
        devices = [d for d in devices if d["status"] == "online"]
    return devices


def generate_alert_pushes(store_id: str = "store_jiaojiang", limit: int = 20) -> list:
    """生成企微推送记录"""
    pushes = []
    levels_data = [("critical", "🔴 严重告警"), ("warn", "🟡 预警"), ("info", "🔵 信息")]
    for i in range(min(limit, 10)):
        level, prefix = levels_data[i % 3]
        pushes.append({
            "id": f"PUSH-{i+1:04d}",
            "title": f"{prefix} {random.choice(['冷链', 'SOP', '损耗', '设备'])}通知",
            "body": f"{random.choice(['椒江店', '玉环店'])}{random.choice(['冷库温度异常', 'SOP未达标', '短重预警', '设备离线'])}\n时间: {_hours_ago(i)}\n状态: {'已处理' if i > 5 else '待确认'}",
            "level": level,
            "store_id": store_id,
            "created_at": _hours_ago(random.randint(0, 10)),
            "push_status": "sent" if i % 3 == 0 else "delivered",
        })
    return pushes


def generate_daily_reports(store_id: str = "store_jiaojiang", limit: int = 30) -> list:
    """生成日报列表"""
    reports = []
    for i in range(min(limit, 14)):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        reports.append({
            "report_id": f"RPT-{date.replace('-', '')}",
            "report_date": date,
            "store_id": store_id,
            "status": "published" if i > 0 else "draft",
            "generated_at": f"{date} 22:00:00",
            "pushed": i < 7 and i > 0,
            "summary": {
                "revenue": round(random.uniform(15000, 45000), 0),
                "tables_served": random.randint(80, 200),
                "sop_rate": round(random.uniform(82, 96), 1),
                "loss_amount": round(random.uniform(200, 1200), 0),
                "alert_count": random.randint(0, 5),
            }
        })
    return reports


def generate_stores() -> list:
    """返回门店列表"""
    return list(STORES.values())


def generate_benchmark() -> dict:
    """生成对标数据"""
    return {
        "industry_avg": {"sop_rate": 78.5, "loss_rate": 3.2, "table_turnover": 4.1},
        "top_performer": {"store": "冯校长火锅·椒江店", "sop_rate": 94.2, "loss_rate": 1.1, "table_turnover": 5.8},
        "chain_avg": {"sop_rate": 85.0, "loss_rate": 2.1, "table_turnover": 4.9},
        "your_store": {"sop_rate": 92.0, "loss_rate": 1.5, "table_turnover": 5.4},
    }


def generate_region_overview(region_id: str = "") -> dict:
    """生成区域概览"""
    return {
        "region_id": region_id or "taizhou",
        "region_name": "台州区域",
        "store_count": 2,
        "total_tables": 32,
        "avg_health_score": 85,
        "avg_sop_rate": 87.5,
        "total_alerts_today": 5,
        "stores": [
            {**s, "today_revenue": round(random.uniform(20000, 50000), 0)}
            for s in STORES.values()
        ],
    }


def generate_national_overview() -> dict:
    """生成全国概览"""
    return {
        "total_stores": 2,
        "active_stores": 2,
        "regions": 1,
        "national_avg_health": 85,
        "trend": "+2.3 vs 上周",
        "top_stores": [
            {"rank": 1, "name": "冯校长火锅·椒江店", "score": 92, "trend": "↑"},
            {"rank": 2, "name": "冯校长火锅·玉环店", "score": 78, "trend": "↑"},
        ],
    }


def generate_admin_org_tree() -> dict:
    """生成管理组织架构"""
    return {
        "org_id": "hotpot_zhejiang",
        "name": "浙江总代",
        "children": [
            {
                "org_id": "reg_taizhou",
                "name": "台州区域",
                "role": "区域督导",
                "user": "潘总",
                "children": [
                    {"org_id": "store_jiaojiang", "name": "椒江店", "role": "店长", "user": "张店长"},
                    {"org_id": "store_yuhuan", "name": "玉环店", "role": "店长", "user": "李店长"},
                ]
            }
        ]
    }


def generate_admin_pipeline_status() -> dict:
    """生成Pipeline状态"""
    return {
        "status": "running",
        "mode": "inprocess",
        "tick_count": random.randint(100, 9999),
        "last_tick": _now(),
        "stores_processed": 2,
        "anomalies_detected": random.randint(0, 3),
        "tasks_created": random.randint(0, 5),
    }


def generate_audit_logs(limit: int = 20) -> list:
    """生成审计日志"""
    actions = ["登录", "查看报表", "修改门店配置", "确认告警", "导出数据"]
    logs = []
    for i in range(min(limit, 15)):
        user = random.choice(list(USERS.values()))
        logs.append({
            "log_id": f"AUDIT-{i+1:04d}",
            "user": user["name"],
            "role": user["role"],
            "action": random.choice(actions),
            "target": random.choice(["门店配置", "SOP任务", "告警事件", "用户权限"]),
            "timestamp": _hours_ago(random.randint(0, limit)),
            "ip": f"192.168.{random.randint(1,255)}.{random.randint(1,255)}",
        })
    return logs


def generate_erp(store_id: str = "store_jiaojiang") -> dict:
    """生成ERP对接数据"""
    return {
        "sync_status": "ok",
        "last_sync": _hours_ago(1),
        "po_count": random.randint(5, 15),
        "grn_count": random.randint(3, 10),
        "pending_invoices": random.randint(0, 3),
        "suppliers": SUPPLIERS,
    }


def generate_metrics() -> dict:
    """生成系统指标"""
    return {
        "uptime_seconds": random.randint(3600, 86400 * 7),
        "requests_total": random.randint(1000, 99999),
        "requests_today": random.randint(100, 5000),
        "active_connections": random.randint(1, 20),
        "db_queries_total": random.randint(5000, 500000),
        "avg_response_ms": round(random.uniform(10, 150), 1),
        "error_rate_pct": round(random.uniform(0, 0.5), 2),
    }


# ============================================================
# 路由表
# ============================================================

ROUTES = {
    # Auth
    "POST:/auth/token": lambda params, body: handle_login(body),
    "GET:/v1/auth/me": lambda params, body: handle_auth_me(params),

    # Summary & Home
    "GET:/v1/summary": lambda params, body: handle_summary(params),

    # Cost
    "GET:/v1/cost/loss-risk": lambda params, body: handle_loss_risk(params),
    "GET:/v1/cost/loss-budget": lambda params, body: handle_loss_budget(params),
    "POST:/v1/cost/loss-risk/{id}/task": lambda params, body: handle_risk_to_task(params, body),

    # SOP
    "POST:/v1/sop/ask": lambda params, body: handle_sop_ask(body),
    "GET:/v1/sop/assignments": lambda params, body: handle_sop_assignments(params),
    "POST:/v1/sop/assign": lambda params, body: handle_sop_assign(body),
    "PUT:/v1/sop/assignments/{id}/status": lambda params, body: handle_sop_update_status(params, body),

    # Alerts
    "GET:/v1/alerts/push-log": lambda params, body: handle_alert_pushes(params),
    "GET:/v1/alerts/acks": lambda params, body: handle_alert_acks(params),
    "GET:/v1/alerts/routes": lambda params, body: handle_alert_routes(params),
    "GET:/v1/alerts/escalations": lambda params, body: handle_escalations(params),
    "POST:/v1/alerts/ack": lambda params, body: handle_alert_ack(body),

    # Events
    "GET:/v1/events": lambda params, body: handle_events(params),

    # Stores
    "GET:/v1/stores": lambda params, body: handle_stores_list(),

    # IoT
    "GET:/v1/iot/readings": lambda params, body: handle_iot_readings(params),
    "GET:/v1/iot/devices": lambda params, body: handle_iot_devices(params),

    # Reports
    "GET:/v1/reports/daily": lambda params, body: handle_daily_reports(params),
    "POST:/v1/reports/daily/generate": lambda params, body: handle_generate_report(body),

    # Region & Benchmark
    "GET:/v1/region/overview": lambda params, body: handle_region_overview(params),
    "GET:/v1/benchmark": lambda params, body: handle_benchmark(),
    "GET:/v1/national/overview": lambda params, body: handle_national_overview(),

    # Admin
    "GET:/v1/admin/org-tree": lambda params, body: handle_admin_org_tree(),
    "GET:/v1/admin/stores": lambda params, body: handle_admin_stores(),
    "POST:/v1/admin/stores": lambda params, body: handle_create_store(body),
    "PUT:/v1/admin/stores/{id}": lambda params, body: handle_update_store(params, body),
    "GET:/v1/admin/pipeline/status": lambda params, body: handle_pipeline_status(),
    "POST:/v1/admin/pipeline/tick": lambda params, body: handle_pipeline_tick(body),
    "GET:/v1/admin/audit-logs": lambda params, body: handle_audit_logs(params),

    # System
    "GET:/health": lambda params, body: handle_health(),
    "GET:/metrics": lambda params, body: handle_metrics(),

    # ERP
    "GET:/v1/erp": lambda params, body: handle_erp(params),

    # Audit
    "GET:/v1/audit/acks": lambda params, body: handle_audit_for_store(params),
}


# ============================================================
# Handler 函数
# ============================================================

def _get_store_id(params: dict) -> str:
    return params.get("store_id", "store_jiaojiang")


def _json_resp(data, status: int = 200) -> tuple:
    return json.dumps(data, ensure_ascii=False, default=str), status


def handle_login(body: dict) -> tuple:
    username = (body or {}).get("username", "zhangdian")
    password = (body or {}).get("password", "demo")
    user = USERS.get(username)

    if not user or user["password"] != password:
        return _json_resp({"detail": "用户名或密码错误"}, 401)

    token = hashlib.sha256(f"{username}:{time.time()}".encode()).hexdigest()[:32]
    return _json_resp({
        "token": token,
        "user": {
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
            "store_id": user.get("store_id", "store_jiaojiang"),
            "storeId": user.get("store_id", "store_jiaojiang"),
            "storeName": STORES.get(user.get("store_id", ""), {}).get("name", ""),
        }
    })


def handle_auth_me(params: dict) -> tuple:
    return _json_resp({
        "username": "zhangdian",
        "name": "张店长",
        "role": "店长",
        "store_id": "store_jiaojiang",
        "storeId": "store_jiaojiang",
        "storeName": "冯校长火锅·椒江店",
    })


def handle_summary(params: dict) -> tuple:
    return _json_resp(generate_summary(_get_store_id(params)))


def handle_loss_risk(params: dict) -> tuple:
    limit = int(params.get("limit", 5))
    return _json_resp({"items": generate_loss_risk(_get_store_id(params), limit)})


def handle_loss_budget(params: dict) -> tuple:
    limit = int(params.get("limit", 5))
    return _json_resp({"items": generate_loss_budget(_get_store_id(params), limit)})


def handle_risk_to_task(params, body: dict) -> tuple:
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return _json_resp({"task_id": task_id, "status": "created"})


def handle_sop_ask(body: dict) -> tuple:
    q = (body or {}).get("question", "")
    return _json_resp({
        "answer": f"根据SOP标准：{q or '收货验货'}需要执行以下步骤：\n1. 检查外包装完整性\n2. 核对送货单与实物\n3. 测量中心温度\n4. 拍照留证\n5. 系统录入",
        "sources": ["SOP-RCV-001", "SOP-TEMP-001"],
        "confidence": 0.92,
    })


def handle_sop_assignments(params: dict) -> tuple:
    status = params.get("status", "")
    return _json_resp({"items": generate_sop_assignments(_get_store_id(params), status)})


def handle_sop_assign(body: dict) -> tuple:
    return _json_resp({"id": f"SOP-{random.randint(100,999)}", "status": "assigned"})


def handle_sop_update_status(params, body: dict) -> tuple:
    return _json_resp({"status": "updated"})


def handle_alert_pushes(params: dict) -> tuple:
    limit = int(params.get("limit", 20))
    return _json_resp({"items": generate_alert_pushes(_get_store_id(params), limit)})


def handle_alert_acks(params: dict) -> tuple:
    return _json_resp({"acks": [{"event_id": f"EVT-{i}", "acked_at": _hours_ago(i)} for i in range(5)]})


def handle_alert_routes(params: dict) -> tuple:
    return _json_resp({"routes": [
        {"level": "critical", "route": "企微+电话", "escalation_min": 15},
        {"level": "warn", "route": "企微推送", "escalation_min": 30},
        {"level": "info", "route": "仅记录", "escalation_min": None},
    ]})


def handle_escalations(params: dict) -> tuple:
    return _json_resp({"items": []})


def handle_alert_ack(body: dict) -> tuple:
    return _json_resp({"ok": True})


def handle_events(params: dict) -> tuple:
    limit = int(params.get("limit", 30))
    return _json_resp({"items": generate_events(_get_store_id(params), limit)})


def handle_stores_list() -> tuple:
    return _json_resp(generate_stores())


def handle_iot_readings(params: dict) -> tuple:
    sensor_id = params.get("sensor_id", "cold_storage_1")
    hours = int(params.get("hours", 24))
    return _json_resp({"readings": generate_iot_readings(sensor_id, hours)})


def handle_iot_devices(params: dict) -> tuple:
    required_only = params.get("required_only", "true").lower() == "true"
    return _json_resp({"devices": generate_iot_devices(required_only)})


def handle_daily_reports(params: dict) -> tuple:
    limit = int(params.get("limit", 30))
    report_date = params.get("report_date", "")
    return _json_resp({"reports": generate_daily_reports(_get_store_id(params), limit)})


def handle_generate_report(body: dict) -> tuple:
    return _json_resp({
        "report_id": f"RPT-{datetime.now().strftime('%Y%m%d')}",
        "status": "generated",
        "pushed": (body or {}).get("push", False),
    })


def handle_region_overview(params: dict) -> tuple:
    return _json_resp(generate_region_overview(params.get("region_id", "")))


def handle_benchmark() -> tuple:
    return _json_resp(generate_benchmark())


def handle_national_overview() -> tuple:
    return _json_resp(generate_national_overview())


def handle_admin_org_tree() -> tuple:
    return _json_resp(generate_admin_org_tree())


def handle_admin_stores() -> tuple:
    return _json_resp({"stores": generate_stores()})


def handle_create_store(body: dict) -> tuple:
    return _json_resp({**(body or {}), "store_id": f"store_new_{random.randint(100,999)}", "status": "created"}, 201)


def handle_update_store(params, body: dict) -> tuple:
    return _json_resp({"status": "updated"})


def handle_pipeline_status() -> tuple:
    return _json_resp(generate_admin_pipeline_status())


def handle_pipeline_tick(body: dict) -> tuple:
    return _json_resp(generate_admin_pipeline_status())


def handle_audit_logs(params: dict) -> tuple:
    limit = int(params.get("limit", 20))
    return _json_resp({"logs": generate_audit_logs(limit)})


def handle_health() -> tuple:
    return _json_resp({"status": "ok", "service": "火瞳平台端 Demo API", "version": "1.0.0-cloud", "mode": "demo", "timestamp": _now()})


def handle_metrics() -> tuple:
    return _json_resp(generate_metrics())


def handle_erp(params: dict) -> tuple:
    return _json_resp(generate_erp(_get_store_id(params)))


def handle_audit_for_store(params: dict) -> tuple:
    target = params.get("store_id", _get_store_id(params))
    return _json_resp({"store_id": target, "audit_items": []})


# ============================================================
# HTTP 请求处理器
# ============================================================

class CloudDemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        # config.js 注入
        if self.path == "/config.js":
            self._serve_config()
            return
        # API 路由
        if self._is_api_path():
            self._handle_api("GET")
            return
        # 静态文件
        super().do_GET()

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if self._is_api_path():
            self._handle_api("POST", body)
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if self._is_api_path():
            self._handle_api("PUT", body)
            return
        self.send_error(404)

    def _is_api_path(self) -> bool:
        p = self.path.split("?")[0]
        return p.startswith("/auth/") or p.startswith("/v1/") or p in ("/health", "/metrics")

    def _serve_config(self) -> None:
        config = {"hubUrl": "", "apiPrefix": ""}
        body = f"window.HOTPOT_CONFIG = {json.dumps(config)};\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode())

    def _handle_api(self, method: str, raw_body: bytes = b"{}") -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 扁平化查询参数
        params = {}
        for k, v in query.items():
            params[k] = v[0] if v else ""

        # 解析body
        try:
            body = json.loads(raw_body) if raw_body else {}
        except Exception:
            body = {}

        # 匹配路由
        route_key = f"{method}:{path}"
        handler = ROUTES.get(route_key)

        # 尝试通配符匹配 {id}
        if not handler:
            for pattern, h in ROUTES.items():
                p_method, p_path = pattern.split(":", 1)
                if p_method != method:
                    continue
                # 将 {xxx} 替换为正则
                regex = "^" + re.sub(r"\{[^}]+\}", "[^/]+", p_path) + "$"
                if re.match(regex, path):
                    handler = h
                    break

        if handler:
            try:
                resp_body, status = handler(params, body)
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"detail": str(e)}).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"detail": f"Not found: {method} {path}"}).encode())

    def log_message(self, fmt, *args):
        path = args[0] if args else ""
        code = args[1] if len(args) > 1 else ""
        # 只显示API调用和错误
        if path.startswith("/v1") or path.startswith("/auth") or path == "/health":
            sys.stderr.write(f"[API] {path} → {code}\n")
        elif code and code != "200":
            sys.stderr.write(f"[{code}] {path}\n")


# ============================================================
# 主入口
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="火瞳平台端 — 云端演示服务器")
    parser.add_argument("--port", type=int, default=8080, help="服务端口 (默认 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    args = parser.parse_args()

    print("=" * 58)
    print(f"  🔥 火瞳 Hotpot Smart Ops — 平台端云端演示版")
    print("=" * 58)
    print(f"  服务地址: http://{args.host}:{args.port}")
    print(f"  Dashboard: {DASHBOARD_DIR}")
    print(f"  API端点数: {len(ROUTES)}")
    print(f"  门店数:   {len(STORES)}")
    print(f"  用户数:   {len(USERS)}")
    print("=" * 58)
    print(f"\n  📱 页面入口:")
    print(f"     登录页:     http://localhost:{args.port}/login.html")
    print(f"     运营首页:   http://localhost:{args.port}/home.html")
    print(f"     CEO驾驶舱:  http://localhost:{args.port}/ceo-cockpit.html")
    print(f"     数字座舱:   http://localhost:{args.port}/cockpit.html")
    print(f"     区域对标:   http://localhost:{args.port}/regional.html")
    print(f"     成本管理:   http://localhost:{args.port}/cost.html")
    print(f"     SOP合规:    http://localhost:{args.port}/sop.html")
    print(f"     告警中心:   http://localhost:{args.port}/alerts.html")
    print(f"     手机H5:     http://localhost:{args.port}/mobile/index.html")
    print(f"     运营后台:   http://localhost:{args.port}/admin/index.html")
    print(f"     VLM演示:    http://localhost:{args.port}/vlm-demo.html")
    print(f"     样式指南:   http://localhost:{args.port}/styleguide.html")
    print(f"\n  🔑 Demo账号:")
    print(f"     店长:   zhangdian / demo")
    print(f"     厨师长: chushi / demo")
    print(f"     督导:   pangu / demo")
    print(f"     管理员: admin  / admin")
    print("=" * 58 + "\n")

    server = ThreadingHTTPServer((args.host, args.port), CloudDemoHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止\n")
        server.shutdown()


if __name__ == "__main__":
    main()
