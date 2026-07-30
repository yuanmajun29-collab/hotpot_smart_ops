<Slide style={{ background: '#FFFFFF', padding: '42px 55px 32px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 6 }}>产品功能全景</Text>
  <Box style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: 14, marginBottom: 18 }}>
    <Text style={{
      fontSize: 60,
      fontWeight: 'bold',
      backgroundImage: 'linear-gradient(135deg, #2563EB 0%, #7C3AED 100%)',
      backgroundClip: 'text',
      color: 'transparent',
      lineHeight: 1
    }}>129</Text>
    <Text style={{ fontSize: 22, color: '#64748B' }}>项功能需求</Text>
  </Box>

  <Box style={{ display: 'flex', flexDirection: 'row', gap: 12, marginBottom: 16 }}>
    <Box style={{ flex: 1, background: '#FEF2F2', borderRadius: 8, padding: '14px 16px', border: '1px solid #FECACA', textAlign: 'center' }}>
      <Text style={{ fontSize: 28, fontWeight: 'bold', color: '#DC2626' }}>27</Text>
      <Text style={{ fontSize: 12, color: '#64748B', marginTop: 2 }}>核心功能</Text>
    </Box>
    <Box style={{ flex: 1, background: '#FFFBEB', borderRadius: 8, padding: '14px 16px', border: '1px solid #FDE68A', textAlign: 'center' }}>
      <Text style={{ fontSize: 28, fontWeight: 'bold', color: '#D97706' }}>42</Text>
      <Text style={{ fontSize: 12, color: '#64748B', marginTop: 2 }}>重要功能</Text>
    </Box>
    <Box style={{ flex: 1, background: '#EFF6FF', borderRadius: 8, padding: '14px 16px', border: '1px solid #BFDBFE', textAlign: 'center' }}>
      <Text style={{ fontSize: 28, fontWeight: 'bold', color: '#2563EB' }}>56</Text>
      <Text style={{ fontSize: 12, color: '#64748B', marginTop: 2 }}>增强功能</Text>
    </Box>
    <Box style={{ flex: 1, background: '#F8FAFC', borderRadius: 8, padding: '14px 16px', border: '1px solid #E2E8F0', textAlign: 'center' }}>
      <Text style={{ fontSize: 28, fontWeight: 'bold', color: '#64748B' }}>4</Text>
      <Text style={{ fontSize: 12, color: '#94A3B8', marginTop: 2 }}>前瞻规划</Text>
    </Box>
  </Box>

  <Text style={{ fontSize: 13, color: '#64748B', marginBottom: 10 }}>九大功能领域</Text>
  <Box style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: 7 }}>
    {[
      { label: '视觉识别', count: 70, color: '#2563EB' },
      { label: '数据分析', count: 27, color: '#7C3AED' },
      { label: '连锁管控', count: 14, color: '#0891B2' },
      { label: '仓库管理', count: 6, color: '#D97706' },
      { label: '岗位助理', count: 5, color: '#059669' },
      { label: '会员营销', count: 4, color: '#DC2626' },
      { label: 'SOP合规', count: 3, color: '#6366F1' },
      { label: '知识库', count: 2, color: '#0D9488' },
      { label: '供应链', count: 4, color: '#EA580C' }
    ].map((tag, i) => (
      <Box key={i} style={{
        background: `${tag.color}08`,
        border: `1px solid ${tag.color}25`,
        borderRadius: 16,
        padding: '5px 12px',
        display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 5
      }}>
        <Text style={{ fontSize: 12, fontWeight: '600', color: tag.color }}>{tag.label}</Text>
        <Text style={{ fontSize: 11, color: '#64748B' }}>{tag.count}</Text>
      </Box>
    ))}
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>6 / 16</Text>
  </Box>
</Slide>
