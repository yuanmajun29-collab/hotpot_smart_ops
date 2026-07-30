<Slide style={{ background: '#FFFFFF', padding: '40px 55px 30px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 5 }}>DOCUMENT CHAIN</Text>
  <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold', marginBottom: 18 }}>六层文档 · 全程可追溯</Text>

  <Box style={{ display: 'flex', flexDirection: 'row', gap: 20 }}>
    <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 7 }}>
      {[
        { num: '1', name: '市场调研', sub: '行业数据 + 竞品分析 + 政策红利', color: '#DC2626' },
        { num: '2', name: '产品需求', sub: '129项功能 · 完整业务场景覆盖', color: '#D97706' },
        { num: '3', name: '产品设计', sub: '产品定位 + 竞品差异化 + 全景分析', color: '#EA580C' },
        { num: '4', name: '解决方案', sub: '技术选型 + 部署方案 + 实施路径', color: '#2563EB' },
        { num: '5', name: '总体架构', sub: '系统视图 + 架构决策记录', color: '#7C3AED' },
        { num: '6', name: '详细设计', sub: '9大模块 · 19张表 · 129功能完整映射', color: '#0891B2', highlight: true }
      ].map((item, i) => (
        <Box key={i} style={{
          display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10,
          background: item.highlight ? '#ECFEFF' : '#F8FAFC',
          borderRadius: 7, padding: '10px 12px',
          border: item.highlight ? '1px solid #99F6E4' : '1px solid #E2E8F0'
        }}>
          <Box style={{
            width: 24, height: 24, borderRadius: '50%',
            background: item.color, display: 'flex',
            alignItems: 'center', justifyContent: 'center', flexShrink: 0
          }}>
            <Text style={{ fontSize: 12, fontWeight: 'bold', color: '#FFF' }}>{item.num}</Text>
          </Box>
          <Box>
            <Text style={{
              fontSize: 14,
              fontWeight: '600',
              color: item.highlight ? '#0E7490' : '#0F172A'
            }}>{item.name}</Text>
            <Text style={{ fontSize: 11, color: '#64748B' }}>{item.sub}</Text>
          </Box>
        </Box>
      ))}
    </Box>

    <Box style={{ width: 220, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Box style={{
        borderRadius: 8, padding: '14px 14px',
        background: 'linear-gradient(135deg, rgba(37,99,235,0.04) 0%, rgba(124,58,237,0.02) 100%)',
        border: '1px solid #E2E8F0'
      }}>
        <Text style={{ fontSize: 12, color: '#2563EB', fontWeight: '600', marginBottom: 8 }}>链路通过率</Text>
        {[
          { label: '市场→需求', rate: '96%' },
          { label: '需求→设计', rate: '100%' },
          { label: '设计→方案', rate: '100%' },
          { label: '方案→架构', rate: '92%' },
          { label: '架构→详细', rate: '95%' }
        ].map((r, i) => (
          <Box key={i} style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: i < 4 ? '1px solid #F1F5F9' : 'none' }}>
            <Text style={{ fontSize: 12, color: '#64748B' }}>{r.label}</Text>
            <Text style={{ fontSize: 12, fontWeight: '600', color: r.rate === '100%' ? '#059669' : '#2563EB' }}>{r.rate}</Text>
          </Box>
        ))}
      </Box>

      <Box style={{
        borderRadius: 8, padding: '14px',
        background: '#F8FAFC', border: '1px solid #E2E8F0'
      }}>
        <Text style={{ fontSize: 12, color: '#64748B', marginBottom: 5 }}>文档标准</Text>
        <Text style={{ fontSize: 12, color: '#334155', lineHeight: 1.5 }}>每份文档包含：版本 / 日期 / 上游依据 / 下游交付 — 形成完整追溯链</Text>
      </Box>

      <Box style={{
        borderRadius: 8, padding: '14px',
        background: '#ECFDF5', border: '1px solid #A7F3D0'
      }}>
        <Text style={{ fontSize: 12, color: '#059669', fontWeight: '600', marginBottom: 3 }}>✅ 数据一致性</Text>
        <Text style={{ fontSize: 11, color: '#64748B', lineHeight: 1.4 }}>全链路核心数据已统一校验，确保各环节信息一致</Text>
      </Box>
    </Box>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>13 / 16</Text>
  </Box>
</Slide>
