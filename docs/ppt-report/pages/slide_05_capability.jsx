<Slide style={{ background: '#FFFFFF', padding: '42px 55px 32px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 5 }}>PRODUCT CAPABILITY</Text>
  <Text style={{ fontSize: 28, color: '#0F172A', fontWeight: 'bold', marginBottom: 22 }}>五层能力 · 从看见到管住</Text>

  <Box style={{ display: 'flex', flexDirection: 'row', gap: 24 }}>
    <Box style={{ width: '54%', position: 'relative', borderRadius: 14, overflow: 'hidden', background: 'linear-gradient(180deg, rgba(37,99,235,0.06) 0%, rgba(124,58,237,0.04) 50%, rgba(6,182,212,0.03) 100%)', border: '1px solid #E2E8F0', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', padding: 22 }}>
      <Box style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
        {[
          { num: '①', label: '看得见的损失', desc: '视觉AI自动识别后厨浪费', color: '#2563EB' },
          { num: '②', label: '算得清的订货', desc: 'AI预测销量，智能建议订货量', color: '#7C3AED' },
          { num: '③', label: '管得住的连锁', desc: '多店统一看板 + SOP合规检查', color: '#0891B2' },
          { num: '④', label: '管得了的冻品', desc: '全程温控追溯 + 品质标准锁定', color: '#D97706' },
          { num: '⑤', label: '配得上的助理', desc: '每个岗位都有专属AI助手', color: '#059669' }
        ].map((item, i) => (
          <Box key={i} style={{
            display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 12,
            background: '#FFFFFF', borderRadius: 8, padding: '11px 14px',
            borderLeft: `3px solid ${item.color}`, boxShadow: '0 1px 3px rgba(0,0,0,0.03)'
          }}>
            <Text style={{ fontSize: 18, fontWeight: 'bold', color: item.color }}>{item.num}</Text>
            <Box>
              <Text style={{ fontSize: 15, fontWeight: '600', color: '#0F172A' }}>{item.label}</Text>
              <Text style={{ fontSize: 12, color: '#64748B' }}>{item.desc}</Text>
            </Box>
          </Box>
        ))}
      </Box>
    </Box>

    <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Box style={{ background: '#F8FAFC', borderRadius: 8, padding: 14, border: '1px solid #E2E8F0', flex: 1 }}>
        <Text style={{ fontSize: 13, color: '#2563EB', fontWeight: '600', marginBottom: 6 }}>视觉引擎</Text>
        <Text style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>覆盖后厨全部工位，自动检测浪费与违规</Text>
      </Box>

      <Box style={{ background: '#F8FAFC', borderRadius: 8, padding: 14, border: '1px solid #E2E8F0', flex: 1 }}>
        <Text style={{ fontSize: 13, color: '#7C3AED', fontWeight: '600', marginBottom: 6 }}>数据引擎</Text>
        <Text style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>销量预测 / 库存优化 / 损耗分析 / 成本核算</Text>
      </Box>

      <Box style={{ background: '#F8FAFC', borderRadius: 8, padding: 14, border: '1px solid #E2E8F0', flex: 1 }}>
        <Text style={{ fontSize: 13, color: '#0891B2', fontWeight: '600', marginBottom: 6 }}>智能体</Text>
        <Text style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>店长 / 后厨 / 采购 / 供应商 四角色专属入口</Text>
      </Box>

      <Box style={{ background: '#F8FAFC', borderRadius: 8, padding: 14, border: '1px solid #E2E8F0', flex: 1 }}>
        <Text style={{ fontSize: 13, color: '#D97706', fontWeight: '600', marginBottom: 6 }}>供应链</Text>
        <Text style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>冻品品质标准、温控追溯、退换货管理</Text>
      </Box>
    </Box>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>5 / 16</Text>
  </Box>
</Slide>
