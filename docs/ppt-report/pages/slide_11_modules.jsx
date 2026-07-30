<Slide style={{ background: '#FFFFFF', padding: '40px 55px 30px' }}>
  <Box style={{ display: 'flex', flexDirection: 'row', marginBottom: 16 }}>
    <Box style={{ width: 160, background: 'linear-gradient(180deg, rgba(37,99,235,0.06) 0%, rgba(37,99,235,0.02) 100%)', borderRadius: 8, padding: '14px 14px', marginRight: 18, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
      <Text style={{ fontSize: 12, color: '#2563EB', fontWeight: '600', letterSpacing: 2, marginBottom: 6 }}>9 CORE</Text>
      <Text style={{ fontSize: 12, color: '#2563EB', fontWeight: '600', letterSpacing: 2 }}>MODULES</Text>
      <Text style={{ fontSize: 11, color: '#64748B', marginTop: 8, lineHeight: 1.4 }}>核心能力模块</Text>
    </Box>
    <Box style={{ flex: 1 }}>
      <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold' }}>完整覆盖 · 从需求到落地</Text>
      <Text style={{ fontSize: 13, color: '#64748B', marginTop: 5 }}>129项功能 → 能力模块 → 业务场景 → 数据支撑</Text>
    </Box>
  </Box>

  <Box style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    {[
      { num: '①', name: '边缘AI引擎', desc: '后厨全工位自动识别 + 前厅双模式分析', new: false },
      { num: '②', name: '事件中枢', desc: '18类业务事件的统一调度与分发', new: false },
      { num: '③', name: '数据引擎', desc: '销量预测 / 库存优化 / 损耗分析 / 成本核算', new: false },
      { num: '④', name: '系统集成', desc: '对接收银、ERP、采购等现有系统', new: false },
      { num: '⑤', name: '告警中心', desc: '分级告警 + 多渠道即时推送', new: false },
      { num: '★⑥', name: 'SOP合规引擎', desc: '6种检查策略 + 违规自动记录与追踪', new: true },
      { num: '★⑦', name: '知识库', desc: '菜品知识 / 操作规范 智能检索问答', new: true },
      { num: '★⑧', name: '仓库IoT', desc: '批次追溯 + 先进先出监控 + 温湿度预警', new: true },
      { num: '★⑨', name: '会员营销', desc: '会员识别 + 积分体系 + 营销活动管理', new: true }
    ].map((m, i) => (
      <Box key={i} style={{
        display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10,
        background: m.new ? '#EFF6FF' : '#F8FAFC',
        borderRadius: 7, padding: '9px 14px',
        borderLeft: m.new ? '3px solid #3B82F6' : '3px solid #E2E8F0',
        border: m.new ? '1px solid #BFDBFE' : '1px solid #E2E8F0'
      }}>
        <Text style={{
          fontSize: m.new ? 14 : 13,
          fontWeight: 'bold',
          color: m.new ? '#2563EB' : '#94A3B8',
          minWidth: 28
        }}>{m.num}</Text>
        <Text style={{
          fontSize: 14,
          fontWeight: '600',
          color: '#0F172A',
          minWidth: 100
        }}>{m.name}</Text>
        <Text style={{ fontSize: 12, color: '#64748B', flex: 1 }}>{m.desc}</Text>
      </Box>
    ))}
  </Box>

  <Text style={{ fontSize: 11, color: '#94A3B8', marginTop: 8 }}>★ v1.1 新增模块（原版5个核心模块）</Text>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>11 / 16</Text>
  </Box>
</Slide>
