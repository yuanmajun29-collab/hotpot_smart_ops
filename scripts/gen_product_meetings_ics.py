#!/usr/bin/env python3
"""Generate Phase 1 product meeting calendar ICS from docs/product_meetings_tencent.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs" / "product_meetings_tencent.json"
OUT = ROOT / "docs" / "product_meetings_phase1.ics"


def fold_line(line: str, limit: int = 75) -> str:
    if len(line.encode("utf-8")) <= limit:
        return line
    out: list[str] = []
    while line:
        out.append(line[: limit - 1])
        line = " " + line[limit - 1 :]
    return "\r\n ".join(out)


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def alarm(minutes_before: int, uid_suffix: str, parent_uid: str) -> str:
    return "\r\n".join(
        [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder",
            f"TRIGGER:-PT{minutes_before}M",
            f"UID:{parent_uid}-alarm-{uid_suffix}@hotpot-smart-ops.local",
            "END:VALARM",
        ]
    )


def event(
    uid: str,
    start: str,
    end: str,
    summary: str,
    location: str,
    description: str,
    categories: str,
    alarms: list[int],
) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}@hotpot-smart-ops.local",
        "DTSTAMP:20260615T060000Z",
        f"DTSTART;TZID=Asia/Shanghai:{start}",
        f"DTEND;TZID=Asia/Shanghai:{end}",
        fold_line(f"SUMMARY:{esc(summary)}"),
        fold_line(f"LOCATION:{esc(location)}"),
        fold_line(f"DESCRIPTION:{esc(description)}"),
        f"CATEGORIES:{categories}",
        "STATUS:CONFIRMED",
    ]
    for i, mins in enumerate(alarms):
        lines.append(alarm(mins, str(i), uid))
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def main() -> None:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    mid = cfg["meeting_id_display"]
    pwd = cfg["password"]
    url = cfg["join_url"]
    dash = cfg["demo_dashboard"]
    acct = cfg["demo_account"]
    loc = f"腾讯会议 {mid} 密码 {pwd}"

    tencent_block = (
        f"腾讯会议号：{mid}\\n"
        f"会议密码：{pwd}\\n"
        f"入会链接：{url}\\n"
        f"\\n"
    )

    ar401_pwd = cfg.get("ar401", {}).get("password", pwd)

    events = [
        event(
            "pm401-20260617",
            "20260617T140000",
            "20260617T160000",
            "PM-401 Phase1 MVP 产品评审",
            loc,
            tencent_block
            + "冯校长火锅·智能运营 Phase 1 MVP 产品评审\\n\\n"
            + "14:00-14:15 目标与边界\\n14:15-15:15 功能走查+看板演示\\n"
            + "15:15-15:45 体验专项\\n15:45-16:00 原则+阻塞项+签字\\n\\n"
            + f"演示看板：{dash}\\n账号：{acct}\\n\\n"
            + "议程：docs/pm401_meeting_agenda_20260617.html",
            "产品评审",
            [1440, 30],
        ),
        event(
            "ar401-20260618",
            "20260618T100000",
            "20260618T123000",
            "AR-401 Phase1 架构设计评审",
            f"腾讯会议 {mid} 密码 {ar401_pwd}",
            tencent_block.replace(f"会议密码：{pwd}", f"会议密码：{ar401_pwd}")
            + "冯校长火锅·智能运营 Phase 1 架构设计评审\\n\\n"
            + "10:00-10:15 目标与边界\\n10:15-10:45 逻辑架构+六闭环\\n"
            + "10:45-11:15 API/数据/ADR\\n11:15-11:45 部署+安全+gap\\n"
            + "11:45-12:15 BL-01~07 排期\\n12:15-12:30 结论签字\\n\\n"
            + f"Hub：http://10.1.12.17:8088/health\\n"
            + "议程：docs/ar401_meeting_agenda_20260618.html",
            "架构评审",
            [1440, 30],
        ),
        event(
            "pm402-yuhuan-20260619",
            "20260619T100000",
            "20260619T105000",
            "PM-402 店长概念测试 · 玉环店",
            "冯校长火锅·玉环店（现场，远程可入会）",
            tencent_block
            + "店长概念测试约50分钟\\n登录门店选「玉环店」\\n\\n"
            + f"演示：{dash}\\n记录：docs/uat_concept_test_record.md",
            "概念测试",
            [1440, 30],
        ),
        event(
            "pm402-jiaojiang-20260620",
            "20260620T100000",
            "20260620T105000",
            "PM-402 店长概念测试 · 椒江店",
            "冯校长火锅·椒江店（现场，远程可入会）",
            tencent_block
            + "店长概念测试约50分钟\\n登录门店选「椒江店」\\n\\n"
            + f"演示：{dash}\\n记录：docs/uat_concept_test_record.md",
            "概念测试",
            [1440, 30],
        ),
    ]

    cal = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Fengxiaozhang Hotpot//Smart Ops Phase1//ZH",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "X-WR-CALNAME:冯校长火锅·智能运营 Phase1 产品+架构会议",
            "X-WR-TIMEZONE:Asia/Shanghai",
            "BEGIN:VTIMEZONE",
            "TZID:Asia/Shanghai",
            "X-LIC-LOCATION:Asia/Shanghai",
            "BEGIN:STANDARD",
            "TZOFFSETFROM:+0800",
            "TZOFFSETTO:+0800",
            "TZNAME:CST",
            "DTSTART:19700101T000000",
            "END:STANDARD",
            "END:VTIMEZONE",
            *events,
            "END:VCALENDAR",
            "",
        ]
    )
    OUT.write_text(cal, encoding="utf-8", newline="\r\n")
    print(f"Wrote {OUT}")
    print(f"  腾讯会议号: {mid}  密码: {pwd}")
    print(f"  入会链接: {url}")


if __name__ == "__main__":
    main()
