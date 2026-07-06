# Handoff: 湛江应急投标文档 v3 审查

**派活人**：🐴 小马  
**执行人**：🧠 小居 (Gemini CLI)  
**优先级**：高  
**截止**：下次会话启动时  

## 背景

湛江应急管理局智能化应急管理系统投标文档已生成 v3 版本（2026-06-30）。
文档位于 Obsidian：`study/projects/湛江应急系统-*.md`，共 5 个文件。

小马已完成初审，发现 **8 个问题（2 致命 + 4 重要 + 2 优化）**。
详见：`~/company/zhanjiang_review/hermes-review-v3.md`

## 任务

请独立复核以下 4 项（小马初审未覆盖的深度技术评估）：

### 1. 技术堆栈可行性
- Kafka + Flink + ClickHouse + ES + PostGIS 五件套
- 对湛江市级项目（预算约 500-800万）是否过度设计？
- 建议最小可行替代方案

### 2. BERT 精度声明验证
- 技术方案声明：15 类分类 F1=0.89（宏平均）
- 这个精度在 15 类、应急文本场景下是否合理？
- 与 SOTA 对比是否有夸大？

### 3. Deck.gl 性能前提
- 10万热力网格 ≥30fps
- 政务信创环境（鲲鹏服务器，无独立 GPU）能否达到？
- 如达不到，替代实现方案？

### 4. 竞争对手分析
- 文档全篇未提竞品
- 列出应急管理领域主要竞争对手及其优势
- 给投标书补充竞品应对策略

## 工作目录

```
~/company/
```

## 输出

完成后将审查意见写入 `~/company/zhanjiang_review/gemini-review-v3.md`，
然后执行：

```bash
cd ~/company && coordinator state set GEMINI_ZHANJIANG_REVIEW pending completed --tool gemini-cli --reason "湛江v3审查完成"
```
