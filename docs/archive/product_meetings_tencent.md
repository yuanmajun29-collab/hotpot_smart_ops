# 腾讯会议配置 · Phase 1 产品会议

**单场会议三场复用（PM-401 + PM-402 玉环 + PM-402 椒江）**

| 项目 | 内容 |
|------|------|
| 配置文件 | [product_meetings_tencent.json](product_meetings_tencent.json) |
| 生成 ICS | `python3 scripts/gen_product_meetings_ics.py` |
| 输出文件 | [product_meetings_phase1.ics](product_meetings_phase1.ics) |

---

## 1. 创建腾讯会议（PMO / 产品操作）

1. 打开 [腾讯会议](https://meeting.tencent.com/) → **预定会议**
2. 建议设置：
   - **主题**：冯校长火锅·智能运营 Phase1 产品会议
   - **时间**：覆盖 6/17 14:00（首场）；周期会议可选 6/17、6/19、6/20
   - **密码**：建议 `061717`（易记，与 6/17 评审日相关）或自定义
   - **等候室**：开启（外店入会需主持人放行）
3. 创建后复制：
   - **会议号**（9 位，如 `123 456 789`）
   - **密码**
   - **入会链接**（`https://meeting.tencent.com/dm/...`）

---

## 2. 更新配置并重新生成 ICS

编辑 `product_meetings_tencent.json`：

```json
{
  "meeting_id": "123456789",
  "meeting_id_display": "123-456-789",
  "password": "061717",
  "join_url": "https://meeting.tencent.com/dm/你的真实链接"
}
```

执行：

```bash
cd /mnt/project/hotpot_smart_ops
python3 scripts/gen_product_meetings_ics.py
```

将生成的 `docs/product_meetings_phase1.ics` 发给参会人导入日历。

---

## 3. 当前占位值（发布前必须替换）

| 项 | 占位值 | 说明 |
|----|--------|------|
| 会议号 | `888-888-888` | 创建会议后替换 |
| 密码 | `061717` | 可与腾讯会议实际密码一致 |
| 入会链接 | `.../placeholder-replace-after-create` | 替换为真实 dm 链接 |

---

## 4. 同步更新邀请文案

替换会议号后，请同步修改：

- [pm401_meeting_invite_20260617.md](pm401_meeting_invite_20260617.md)
- [pm402_meeting_invite_20260619_20.md](pm402_meeting_invite_20260619_20.md)

搜索 `___________` 和 `______` 填入真实会议号与密码。

---

## 5. ICS 提醒设置

每场会议已内置：

- **提前 1 天** 提醒
- **提前 30 分钟** 提醒

导入 Outlook / 苹果日历后自动生效。
