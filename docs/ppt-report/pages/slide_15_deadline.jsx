<Slide style={{ background: '#FFFFFF', padding: '42px 55px 32px' }}>
  <Text style={{ fontSize: 14, color: '#DC2626', fontWeight: '600', letterSpacing: 3, marginBottom: 6 }}>HARD DEADLINE</Text>
  <Text style={{ fontSize: 26, color: '#0F172A', fontWeight: 'bold', marginBottom: 22 }}>重庆市政府展会亮相</Text>

  <Box style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 22 }}>
    <Text style={{
      fontSize: 64,
      fontWeight: 'bold',
      backgroundImage: 'linear-gradient(135deg, #D97706 0%, #EA580C 100%)',
      backgroundClip: 'text', color: 'transparent', lineHeight: 1
    }}>2026.10</Text>
    <Text style={{
      fontSize: 30, color: '#0F172A', fontWeight: 'bold',
      marginTop: -2
    }}>重庆</Text>
  </Box>

  <Box style={{
    background: '#FEF2F2', borderRadius: 10,
    padding: '16px 20px', border: '1px solid #FECACA', maxWidth: 660, alignSelf: 'center'
  }}>
    <Text style={{ fontSize: 13, color: '#DC2626', fontWeight: '600', marginBottom: 10 }}>三阶段路线</Text>

    <Box style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {[
        { phase: '两店验证', status: '🟡 进行中', statusColor: '#D97706', dotColor: '#D97706' },
        { phase: '区域标准化', status: '⏳ 展会后', statusColor: '#64748B', dotColor: '#2563EB' },
        { phase: '对外输出', status: '⏳ 标准化后', statusColor: '#64748B', dotColor: '#7C3AED' }
      ].map((p, i) => (
        <Box key={i} style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Box style={{ width: 8, height: 8, borderRadius: '50%', background: p.dotColor, flexShrink: 0 }} />
          <Text style={{ fontSize: 14, fontWeight: '600', color: '#334155', flex: 1 }}>{p.phase}</Text>
          <Text style={{ fontSize: 13, color: p.statusColor }}>{p.status}</Text>
        </Box>
      ))}
    </Box>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>15 / 16</Text>
  </Box>
</Slide>
