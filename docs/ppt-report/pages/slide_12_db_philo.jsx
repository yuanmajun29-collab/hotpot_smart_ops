<Slide style={{ background: '#FFFFFF', padding: '42px 55px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 6 }}>DATA FOUNDATION</Text>
  <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold', marginBottom: 18 }}>完整数据体系</Text>

  <Box style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 16
  }}>
    <Text style={{
      fontSize: 60,
      fontWeight: 'bold',
      backgroundImage: 'linear-gradient(135deg, #2563EB 0%, #0891B2 100%)',
      backgroundClip: 'text', color: 'transparent', lineHeight: 1
    }}>19<span style={{ fontSize: 36 }}>张</span></Text>
    <Text style={{ fontSize: 14, color: '#64748B', marginTop: 3 }}>核心业务数据表 · 覆盖用户/运营/供应链/营销全领域</Text>
  </Box>

  <Box style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 6, justifyContent: 'center', maxWidth: 860, marginBottom: 18 }}>
    {['用户与权限', 'SOP标准模板', '合规检查记录', '知识库内容', '会员档案', '积分流水', '组织架构', '操作审计', '告警通知'].map((t, i) => (
      <Box key={i} style={{
        background: '#F8FAFC', borderRadius: 6,
        padding: '5px 12px', border: '1px solid #E2E8F0'
      }}>
        <Text style={{ fontSize: 12, color: '#334155' }}>{t}</Text>
      </Box>
    ))}
    <Box style={{
      background: '#EFF6FF', borderRadius: 6,
      padding: '5px 12px', border: '1px solid #BFDBFE'
    }}>
      <Text style={{ fontSize: 12, color: '#2563EB' }}>+ 更多业务表...</Text>
    </Box>
  </Box>

  <Box style={{ width: 100, height: 2, background: 'linear-gradient(90deg, transparent, #0891B2, #2563EB, transparent)', borderRadius: 1, marginBottom: 14 }} />

  <Box style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
    <Text style={{ fontSize: 18, color: '#0F172A', fontWeight: '600', lineHeight: 1.5 }}>视频不上云 · 决策在边缘 · 数据在云端 · 智能在两端</Text>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>12 / 16</Text>
  </Box>
</Slide>
