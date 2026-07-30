<Slide style={{ background: '#FFFFFF', padding: '40px 55px 30px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 5 }}>THREE-LAYER ARCHITECTURE</Text>
  <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold', marginBottom: 16 }}>三层闭环 · 边缘到云端</Text>

  <Box style={{ borderRadius: 12, overflow: 'hidden', border: '1px solid #E2E8F0', marginBottom: 14, boxShadow: '0 1px 6px rgba(0,0,0,0.04)' }}>
    <Box style={{ background: 'linear-gradient(180deg, rgba(8,145,178,0.05) 0%, rgba(37,99,235,0.03) 100%)', padding: '18px 24px' }}>
      <Box style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <Text style={{ fontSize: 17, fontWeight: 'bold', color: '#0891B2' }}>L2 边缘层 · 门店侧</Text>
      </Box>
      <Text style={{ fontSize: 14, color: '#334155', lineHeight: 1.5 }}>摄像头实时识别后厨操作 · 数据本地处理不上云 · 毫秒级响应</Text>
    </Box>
    <Box style={{ height: 1, background: '#E2E8F0' }} />
    <Box style={{ display: 'flex', flexDirection: 'row', justifyContent: 'center', alignItems: 'center', padding: '6px 0' }}>
      <Text style={{ fontSize: 14, color: '#94A3B8' }}>↓ 安全加密传输 ↓</Text>
    </Box>
    <Box style={{ height: 1, background: '#E2E8F0' }} />
    <Box style={{ background: 'linear-gradient(180deg, rgba(37,99,235,0.05) 0%, rgba(124,58,237,0.03) 100%)', padding: '18px 24px' }}>
      <Box style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <Text style={{ fontSize: 17, fontWeight: 'bold', color: '#2563EB' }}>L3 平台层 · 云端大脑</Text>
      </Box>
      <Text style={{ fontSize: 14, color: '#334155', lineHeight: 1.5 }}>数据引擎 · 事件中枢 · 经营看板 · SOP合规引擎</Text>
    </Box>
    <Box style={{ height: 1, background: '#E2E8F0' }} />
    <Box style={{ display: 'flex', flexDirection: 'row', justifyContent: 'center', alignItems: 'center', padding: '6px 0' }}>
      <Text style={{ fontSize: 14, color: '#94A3B8' }}>↓ 多端访问 ↓</Text>
    </Box>
    <Box style={{ height: 1, background: '#E2E8F0' }} />
    <Box style={{ background: 'linear-gradient(180deg, rgba(124,58,237,0.05) 0%, rgba(236,72,153,0.02) 100%)', padding: '18px 24px' }}>
      <Box style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <Text style={{ fontSize: 17, fontWeight: 'bold', color: '#7C3AED' }}>L4 应用层 · 各角色入口</Text>
      </Box>
      <Text style={{ fontSize: 14, color: '#334155', lineHeight: 1.5 }}>店长 / 后厨 / 采购 / 供应商 专属工作台 · 手机 + 电脑 + 大屏</Text>
    </Box>
  </Box>

  <Box style={{
    background: '#F8FAFC', borderRadius: 8, padding: '12px 20px',
    border: '1px solid #E2E8F0', textAlign: 'center'
  }}>
    <Text style={{ fontSize: 14, color: '#64748B' }}>
      <span style={{ color: '#0891B2' }}>决策在边缘</span> ·
      <span style={{ color: '#2563EB' }}> 数据在云端</span> ·
      <span style={{ color: '#7C3AED' }}> 智能在两端</span>
    </Text>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>8 / 16</Text>
  </Box>
</Slide>
