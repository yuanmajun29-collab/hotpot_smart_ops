<Slide style={{ background: '#FFFFFF', padding: '40px 55px 30px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 5 }}>SPRINT PLAN</Text>
  <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold', marginBottom: 20 }}>D1-D4 · 冲刺四步走</Text>

  <Box style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
    {[
      {
        id: 'D1', name: '冻品供应链', month: '8月',
        desc: '品牌规格锁定 · 温控追溯 · 退换货流程',
        color: '#2563EB', border: '#BFDBFE', bg: '#EFF6FF'
      },
      {
        id: 'D2', name: '岗位AI助理', month: '8月',
        desc: '店长 / 后厨 / 采购 / 供应商 四角色入口',
        color: '#7C3AED', border: '#DDD6FE', bg: '#F5F3FF'
      },
      {
        id: 'D3', name: '集成测试', month: '9月',
        desc: '双店联调 · 端到端流程验证 · 性能压测',
        color: '#0891B2', border: '#A5F3FC', bg: '#ECFEFF'
      },
      {
        id: 'D4', name: '彩排', month: '9月',
        desc: 'Demo场景打磨 · 讲稿演练 · 应急预案',
        color: '#D97706', border: '#FDE68A', bg: '#FFFBEB'
      }
    ].map((step, i) => (
      <Box key={i} style={{
        display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 14,
        background: step.bg,
        borderRadius: 8, padding: '14px 18px',
        borderLeft: `4px solid ${step.color}`
      }}>
        <Box style={{
          width: 46, height: 46, borderRadius: 8,
          background: `${step.color}12`, border: `1px solid ${step.border}`,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flexShrink: 0
        }}>
          <Text style={{ fontSize: 16, fontWeight: 'bold', color: step.color }}>{step.id}</Text>
          <Text style={{ fontSize: 10, color: '#94A3B8' }}>{step.month}</Text>
        </Box>
        <Box style={{ flex: 1 }}>
          <Text style={{ fontSize: 16, fontWeight: '600', color: '#0F172A' }}>{step.name}</Text>
          <Text style={{ fontSize: 13, color: '#64748B', marginTop: 2 }}>{step.desc}</Text>
        </Box>
      </Box>
    ))}
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>14 / 16</Text>
  </Box>
</Slide>
