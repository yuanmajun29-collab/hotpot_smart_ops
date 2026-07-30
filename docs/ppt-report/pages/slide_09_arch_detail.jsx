<Slide style={{ background: '#FFFFFF', padding: '42px 55px 32px' }}>
  <Text style={{ fontSize: 14, color: '#64748B', fontWeight: '500', marginBottom: 6 }}>SYSTEM SCALE</Text>
  <Text style={{ fontSize: 28, color: '#0F172A', fontWeight: 'bold', marginBottom: 20 }}>四层架构 · 完整落地</Text>

  <Box style={{ display: 'flex', flexDirection: 'row', gap: 20 }}>
    <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {[
        { layer: 'L1 设备层', tech: '摄像头 · 温湿度传感器 · RFID标签', color: '#64748B' },
        { layer: 'L2 边缘层', tech: '门店侧智能终端 · 本地实时识别与处理', color: '#0891B2' },
        { layer: 'L3 平台层', tech: '云端数据引擎 · 经营分析 · 多店看板', color: '#2563EB' },
        { layer: 'L4 应用层', tech: '四角色专属工作台 · 手机 / 电脑 / 大屏', color: '#7C3AED' }
      ].map((item, i) => (
        <Box key={i} style={{
          display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 12,
          background: '#F8FAFC', borderRadius: 8, padding: '12px 16px',
          borderLeft: `3px solid ${item.color}`,
          border: '1px solid #E2E8F0'
        }}>
          <Text style={{
            fontSize: 16, fontWeight: 'bold', color: item.color,
            minWidth: 82
          }}>{item.layer}</Text>
          <Text style={{ fontSize: 14, color: '#334155', lineHeight: 1.4 }}>{item.tech}</Text>
        </Box>
      ))}
    </Box>

    <Box style={{ width: 230, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Box style={{
        borderRadius: 10, padding: '18px 16px',
        background: 'linear-gradient(135deg, rgba(37,99,235,0.04) 0%, rgba(124,58,237,0.02) 100%)',
        border: '1px solid #E2E8F0', textAlign: 'center'
      }}>
        <Text style={{ fontSize: 40, fontWeight: 'bold', backgroundImage: 'linear-gradient(135deg, #2563EB 0%, #7C3AED 100%)', backgroundClip: 'text', color: 'transparent', lineHeight: 1 }}>完整</Text>
        <Text style={{ fontSize: 14, color: '#64748B', marginTop: 2 }}>闭环系统</Text>
      </Box>

      <Box style={{ display: 'flex', flexDirection: 'row', gap: 8 }}>
        <Box style={{ flex: 1, background: '#EFF6FF', borderRadius: 8, padding: '12px 10px', textAlign: 'center', border: '1px solid #BFDBFE' }}>
          <Text style={{ fontSize: 22, fontWeight: 'bold', color: '#2563EB' }}>9</Text>
          <Text style={{ fontSize: 11, color: '#64748B' }}>核心模块</Text>
        </Box>
        <Box style={{ flex: 1, background: '#F5F3FF', borderRadius: 8, padding: '12px 10px', textAlign: 'center', border: '1px solid #DDD6FE' }}>
          <Text style={{ fontSize: 22, fontWeight: 'bold', color: '#7C3AED' }}>19</Text>
          <Text style={{ fontSize: 11, color: '#64748B' }}>数据表</Text>
        </Box>
      </Box>

      <Box style={{ display: 'flex', flexDirection: 'row', gap: 8 }}>
        <Box style={{ flex: 1, background: '#ECFEFF', borderRadius: 8, padding: '12px 10px', textAlign: 'center', border: '1px solid #A5F3FC' }}>
          <Text style={{ fontSize: 22, fontWeight: 'bold', color: '#0891B2' }}>129<span style={{ fontSize: 12 }}></span></Text>
          <Text style={{ fontSize: 11, color: '#64748B' }}>功能项</Text>
        </Box>
        <Box style={{ flex: 1, background: '#FFFBEB', borderRadius: 8, padding: '12px 10px', textAlign: 'center', border: '1px solid #FDE68A' }}>
          <Text style={{ fontSize: 18, fontWeight: 'bold', color: '#D97706' }}>6大能力</Text>
          <Text style={{ fontSize: 11, color: '#64748B' }}>数据引擎</Text>
        </Box>
      </Box>
    </Box>
  </Box>

  <Box style={{ position: 'absolute', bottom: 28, right: 50 }}>
    <Text style={{ fontSize: 13, color: 'rgba(100,116,139,0.4)' }}>9 / 16</Text>
  </Box>
</Slide>
