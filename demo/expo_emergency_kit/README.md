# 🎒 火瞳展会应急包 (Expo Emergency Kit)

> **版本**: v0.4.0-expo-ready
> **创建日期**: 2026-08-02
> **用途**: 展会现场故障时的备用方案

---

## 📦 应急包内容清单

### 1. 离线演示数据 (`data/`)

| 文件名 | 说明 | 使用场景 |
|--------|------|---------|
| `demo_optimistic.json` | **乐观数据**（效果最好） | 投资人/政府领导 |
| `demo_conservative.json` | **保守数据**（真实保守） | 技术专家/同行 |
| `demo_realistic.json` | **真实数据**（椒江店实测） | 一般观众 |
| `gateway_audit_sample.json` | Gateway审计日志样本 | IP-5演示备用 |

### 2. 关键截图 (`screenshots/`)

| 文件名 | 说明 |
|--------|------|
| `01_login_page.png` | 登录页面 |
| `02_dashboard_kpi.png` | Dashboard KPI卡片 |
| `03_waste_detection.png` | 废料检测页面 |
| `04_sales_forecast.png` | 销量预测页面 |
| `05_supply_chain.png` | 冻品供应链页面 |
| `06_ai_assistant.png` | 岗位AI助理页面 |
| `07_chain_dashboard.png` | 连锁看板页面 |
| `08_ip5_approval_flow.png` | IP-5审批流程 |
| `09_gateway_status.png` | Gateway状态页 |
| `10_audit_log.png` | 审计日志页面 |

### 3. 演示脚本 (`scripts/`)

| 文件名 | 说明 |
|--------|------|
| `expo_demo_full.sh` | 完整演示一键运行脚本 |
| `expo_demo_offline.py` | 离线模式演示脚本 |
| `ip5_gateway_demo.py` | IP-5 Gateway专用演示 |

### 4. 文档 (`docs/`)

| 文件名 | 说明 |
|--------|------|
| `操作手册_精简版.pdf` | 操作手册打印版（A4，双面） |
| `FAQ速查卡.pdf` | 常见问题一页纸 |
| `故障处理流程图.pdf` | 故障处理决策树 |

---

## 🚀 快速使用指南

### 场景A: Jetson无法连接（完全离线）

```bash
# Step 1: 启动本地Mock服务器
cd demo/expo_emergency_kit
python3 -m http.server 9000

# Step 2: 浏览器打开
open http://localhost:9000/screenshots/index.html

# Step 3: 按截图顺序讲解（配合离线演示脚本）
```

### 场景B: 部分功能异常（降级演示）

```bash
# 只使用离线数据替代API调用
python3 scripts/expo_demo_offline.py --mode conservative
```

### 场景C: IP-5 Gateway演示失败

```bash
# 使用预录制的审计日志数据
python3 scripts/ip5_gateway_demo.py --use-sample-data
```

## 📊 三套数据集说明

### 乐观数据集 (optimistic)

**适用场景**: 融资路演、政府汇报、媒体采访

```json
{
  "kpi": {
    "mape": "8.2%",           // 预测准确率更高
    "waste_reduction": "65%",  // 损耗降低更多
    "annual_savings": "180000",// 年省更多
    "sop_compliance": "98"     // SOP接近满分
  },
  "narrative": "火瞳系统在椒江店部署3个月后，
               损耗率从15%降至5.2%，年节省18万元"
}
```

### 保守数据集 (conservative)

**适用场景**: 技术评审、同行交流、专家答辩

```json
{
  "kpi": {
    "mape": "12.5%",          // 真实波动范围
    "waste_reduction": "45%",  // 保守估计
    "annual_savings": "120000",// 保底数字
    "sop_compliance": "85"     // 还有提升空间
  },
  "narrative": "火瞳系统在真实环境中验证有效，
               当前处于优化迭代阶段"
}
```

### 真实数据集 (realistic)

**适用场景**: 一般展示、日常演示、客户拜访

```json
{
  "kpi": {
    "mape": "10.6%",           // 实测值
    "waste_reduction": "55%",  // 实测值
    "annual_savings": "150000",// 实测值
    "sop_compliance": "100"    // 实测值
  },
  "narrative": "基于椒江店90天POS数据和30天视觉检测数据"
}
```

---

## 🎬 离线演示HTML模板

如果需要完全离线演示（无网络、无Jetson），可以使用以下HTML：

```html
<!DOCTYPE html>
<html>
<head>
  <title>火瞳系统 - 离线演示模式</title>
  <style>
    body { font-family: 'Microsoft YaHei', sans-serif; margin: 40px; }
    .slide { display: none; }
    .slide.active { display: block; }
    .nav { position: fixed; bottom: 20px; right: 20px; }
    button { padding: 10px 20px; margin: 0 5px; cursor: pointer; }
    img { max-width: 100%; height: auto; }
  </style>
</head>
<body>
  <h1>🔥 火瞳AI运营中台 - 展示演示</h1>

  <div id="slide1" class="slide active">
    <h2>S1 后厨之眼</h2>
    <img src="screenshots/03_waste_detection.png" alt="废料检测">
    <p>实时废料检测：今日6件，损耗¥1,195</p>
  </div>

  <!-- 更多幻灯片... -->

  <div class="nav">
    <button onclick="prevSlide()">⬅️ 上一张</button>
    <button onclick="nextSlide()">➡️ 下一张</button>
  </div>

  <script>
    let current = 0;
    const slides = document.querySelectorAll('.slide');
    function showSlide(n) {
      slides[current].classList.remove('active');
      current = (n + slides.length) % slides.length;
      slides[current].classList.add('active');
    }
    function nextSlide() { showSlide(current + 1); }
    function prevSlide() { showSlide(current - 1); }
    // 键盘控制
    document.addEventListener('keydown', e => {
      if(e.key === 'ArrowRight') nextSlide();
      if(e.key === 'ArrowLeft') prevSlide();
    });
  </script>
</body>
</html>
```

---

## ⚠️ 重要提醒

1. **展会前1天务必测试应急包**
   - 确认所有文件完整
   - 测试离线演示流程
   - 准备U盘备份

2. **截图需定期更新**
   - 每次代码更新后重新截图
   - 保持与线上版本一致

3. **数据集选择策略**
   - 根据听众类型选择合适的数据集
   - 保持诚实，不要过度夸大

4. **练习离线演示**
   - 至少完整演练3次
   - 控制在12-15分钟内

---

## 📞 应急联系人

- **技术支持**: [待填写]
- **现场负责人**: [待填写]
- **远程支援**: SSH root@172.16.1.60

---

> 💡 **提示**: 将整个`expo_emergency_kit`目录复制到U盘，展会当天随身携带！
