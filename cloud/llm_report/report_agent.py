#!/usr/bin/env python3
"""LLM operations report agent for hotpot stores."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class RuleBasedReportAgent:
    """Rule-based report generator (PoC fallback, no API key required)."""

    def generate(self, summary: Dict[str, Any], store_name: str = "试点门店") -> str:
        events = summary.get("by_level", {})
        tables = summary.get("table_state_counts", {})
        pos = summary.get("pos_stats", {})
        suggestions = summary.get("turnover_suggestions", [])
        sop = summary.get("sop_stats", {})
        cost = summary.get("cost_stats", {})
        iot = summary.get("iot_stats", {})
        critical = events.get("critical", 0)
        warn = events.get("warn", 0)

        turnover_rate = pos.get("turnover_rate", 2.5)
        revenue = pos.get("daily_revenue", 48000)
        dish_timeout = pos.get("dish_timeout_count", 0)

        lines = [
            f"# {store_name} 运营日报",
            f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## 一、前厅翻台概况",
            f"- 空桌：{tables.get('empty', 0)} 桌 | 用餐中：{tables.get('dining', 0)} 桌",
            f"- 待清台：{tables.get('need_clean', 0)} 桌 | 待结账：{tables.get('checkout', 0)} 桌",
            f"- 当前翻台率（POS）：{turnover_rate} 次/日",
            "",
            "### 翻台优先建议",
        ]
        if suggestions:
            for s in suggestions[:5]:
                lines.append(f"- **{s['table_id']}** [{s['state']}] → {s['action']}")
        else:
            lines.append("- 暂无待处理翻台任务")

        lines.extend(
            [
                "",
                "## 二、后厨与食安",
                f"- 警告事件：{warn} 条 | 严重事件：{critical} 条",
                f"- 出餐超时（POS）：{dish_timeout} 单",
            ]
        )
        if critical > 0:
            lines.append("- **需立即处理**：存在严重告警（烟雾/冷链/燃气），请值班店长确认")
        else:
            lines.append("- 食安态势正常，建议继续保持冷链巡检频次")

        # SOP compliance section
        lines.extend(["", "## 三、后厨 SOP 执行"])
        if sop:
            lines.append(
                f"- 午市班次合规率：**{sop.get('compliance_rate', 0)}%** "
                f"（通过 {sop.get('passed', 0)}/{sop.get('total', 0)}）"
            )
            failed_sops = [r for r in sop.get("results", []) if r.get("status") == "failed"]
            if failed_sops:
                lines.append("- 未达标 SOP：")
                for r in failed_sops[:5]:
                    lines.append(f"  - {r['sop_name']}：{r.get('reason', '')}")
            else:
                lines.append("- 当前班次 SOP 全部达标")
        else:
            lines.append("- 暂无 SOP 巡检数据")

        # Cost control section
        lines.extend(["", "## 四、来料成本控制"])
        if cost:
            var_amt = cost.get("total_variance_amount", 0)
            lines.append(f"- 本批次来料 {cost.get('batch_count', 0)} 项，PO 总额 ¥{cost.get('total_po_amount', 0):,.2f}")
            lines.append(
                f"- 实收总额 ¥{cost.get('total_actual_amount', 0):,.2f}，"
                f"偏差 **{cost.get('variance_rate_pct', 0):+.2f}%**（¥{var_amt:+,.2f}）"
            )
            lines.append(f"- 建议拒收/协商：{cost.get('reject_count', 0)} 批")
            for rec in cost.get("recommendations", [])[:3]:
                lines.append(f"- {rec}")
        else:
            lines.append("- 暂无来料成本分析数据")

        # IoT lifecycle section
        lines.extend(["", "## 五、IoT 食材全链路（来料→保存→加工）"])
        if iot:
            iot_sum = iot.get("summary", {})
            by_stage = iot_sum.get("readings_by_stage", {})
            lines.append(
                f"- IoT 采集点：来料 {by_stage.get('receiving', 0)} | "
                f"保存 {by_stage.get('storage', 0)} | 加工 {by_stage.get('processing', 0)}"
            )
            lines.append(f"- IoT 告警：{iot_sum.get('iot_alert_count', 0)} 条")
            for alert_type, cnt in list(iot_sum.get("iot_alerts_by_type", {}).items())[:5]:
                lines.append(f"  - {alert_type}: {cnt}")
            lines.append("- **IoT×VLM×LLM 协同**：IoT 提供数量/温度/时长硬数据，VLM 做外观品质，LLM 生成整改与对账建议")
        else:
            lines.append("- 暂无 IoT 链路数据")

        lines.extend(
            [
                "",
                "## 六、经营摘要",
                f"- 日营收（POS）：¥{revenue:,.0f}",
                f"- 预估翻台提升空间：待清台 {tables.get('need_clean', 0)} 桌，清台后可增约 ¥{tables.get('need_clean', 0) * 120 * 0.8:,.0f}",
                "",
                "## 七、改进建议（LLM）",
            ]
        )

        recs = []
        if tables.get("need_clean", 0) >= 2:
            recs.append("待清台较多，建议高峰段增配 1 名保洁，目标翻台等待 <8 分钟")
        if dish_timeout >= 3:
            recs.append("出餐超时偏多，排查毛肚/鲜切档口备料与传菜路径")
        if critical > 0:
            recs.append("触发食安联合巡检 SOP，2 小时内完成整改闭环并上传照片")
        if sop.get("failed", 0) > 0:
            recs.append(f"后厨 {sop.get('failed')} 项 SOP 未达标，安排班组长 30 分钟内复盘并补录")
        if cost.get("variance_rate_pct", 0) > 3:
            recs.append(f"来料成本偏差 {cost.get('variance_rate_pct')}% 超标，启动供应商对账与出成率复盘")
        if cost.get("reject_count", 0) > 0:
            recs.append("存在建议拒收批次，按来料 SOP 执行退货并更新采购协议价")
        iot_alerts = (iot.get("summary") or {}).get("iot_alert_count", 0)
        if iot_alerts >= 3:
            recs.append(f"IoT 全链路告警 {iot_alerts} 条，优先排查保存环节门磁/温控与来料 RFID 追溯")
        if not recs:
            recs.append("整体运营平稳，建议对比同区域门店 SLA 继续优化等位转化")

        for i, r in enumerate(recs, 1):
            lines.append(f"{i}. {r}")

        lines.extend(["", "---", "*本报告由 Hotpot Smart Ops PoC 自动生成*"])
        return "\n".join(lines)


class OpenAIReportAgent(RuleBasedReportAgent):
    """Optional OpenAI-compatible LLM backend."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback = RuleBasedReportAgent()

    def generate(self, summary: Dict[str, Any], store_name: str = "试点门店") -> str:
        try:
            prompt = (
                "你是连锁火锅门店运营专家。根据以下 JSON 运营数据，"
                "生成简洁的中文门店日报，包含：前厅翻台、后厨食安、SOP执行、来料成本控制、经营摘要、改进建议。\n\n"
                f"门店：{store_name}\n数据：{json.dumps(summary, ensure_ascii=False)}"
            )
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            }
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            print(f"[WARN] LLM API failed ({exc}), using rule-based fallback")
            return self.fallback.generate(summary, store_name)


def fetch_summary(hub_url: str, store_id: str = "store_yuhuan") -> Dict[str, Any]:
    url = hub_url.rstrip("/") + f"/summary?store_id={store_id}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def create_agent(backend: str):
    if backend == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            return OpenAIReportAgent(key, base, model)
        print("[WARN] OPENAI_API_KEY not set, using rule backend")
    return RuleBasedReportAgent()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotpot LLM report agent")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8088")
    parser.add_argument("--store-id", default="store_yuhuan")
    parser.add_argument("--store-name", default="冯校长火锅·玉环店")
    parser.add_argument("--backend", choices=("rule", "openai"), default="rule")
    parser.add_argument("--output", default="", help="Write report to file")
    args = parser.parse_args()

    summary = fetch_summary(args.hub_url, args.store_id)
    agent = create_agent(args.backend)
    report = agent.generate(summary, args.store_name)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[Report] Written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
