/**
 * 火瞳平台端 — 云端演示 Mock 数据层
 *
 * ⚠️ 改造方案要求 (P0-C):
 *    - 生产环境必须禁用此 Mock 层
 *    - Dashboard 应连接真实 Hub API
 *    - 仅开发/演示环境可启用
 *
 * 用法：在 login.html 的 <script> 标签前引入此文件
 *
 * 生产环境禁用方式 (任选其一):
 *   1. 不引入此 JS 文件
 *   2. 设置 window.HOTPOT_PRODUCTION = true
 *   3. URL 参数 ?mock=false
 */

(function() {
    'use strict';

    // ============================================================
    // ⚠️ 生产环境安全检查: 自动禁用 Mock
    // 改造方案要求: Dashboard、前厅、后厨、告警页面全部改接真实 Hub API
    // ============================================================
    const _isProduction = (
        window.HOTPOT_PRODUCTION === true ||
        (window.location && window.location.search.indexOf('mock=false') > -1) ||
        (document.documentElement.getAttribute('data-env') || '').toLowerCase() === 'production'
    );

    if (_isProduction) {
        console.warn('[cloud_mock] ⚠️ 生产环境已禁用 Mock 数据层，所有请求将发送到真实 Hub API');
        return;  // 不执行任何 Mock 逻辑
    }

    console.info('[cloud_mock] ℹ️ 开发/演示模式: Mock 数据层已启用 (非生产环境)');

    // ============================================================
    // Mock 数据生成器
    // ============================================================
    const STORES = {
        store_jiaojiang: { store_id: 'store_jiaojiang', name: '冯校长火锅·椒江店', region: '台州', type: 'flagship', tables: 18, health_score: 92 },
        store_yuhuan:   { store_id: 'store_yuhuan',   name: '冯校长火锅·玉环店',   region: '台州', type: 'standard', tables: 14, health_score: 78 },
    };

    const SKU_LIST = ['毛肚','鸭肠','黄喉','肥牛','羊肉卷','虾滑','午餐肉','土豆片','莲藕','娃娃菜','腐竹','金针菇','宽粉','鱼豆腐','贡菜'];
    const SUPPLIERS = ['蜀海供应链', '鑫源冻品', '绿源农业'];

    function _now() { return new Date().toLocaleString('zh-CN'); }
    function _hoursAgo(h) { const d = new Date(); d.setHours(d.getHours() - h); return d.toLocaleString('zh-CN'); }
    function _rand(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
    function _randF(min, max, dec = 2) { return parseFloat((Math.random() * (max - min) + min).toFixed(dec)); }

    function getStore(id) { return STORES[id] || STORES.store_jiaojiang; }
    function currentStoreId() { return (localStorage.getItem('mock_store_id') || 'store_jiaojiang'); }

    // ============================================================
    // 数据生成函数
    // ============================================================
    function genSummary(storeId) {
        const s = getStore(storeId);
        const flag = s.type === 'flagship';
        return {
            store_name: s.name, store_id: s.id || storeId, timestamp: _now(), health_score: s.health_score,
            table_state_counts: { empty: _rand(2, flag?6:4), dining: _rand(flag?8:5, flag?14:10), need_clean: _rand(1, flag?3:4), checkout: _rand(0,2) },
            by_level: { critical: 0, warn: _rand(0,2), info: _rand(1,4) },
            sop_stats: { total: _rand(45,60), passed: _rand(flag?40:35, flag?56:48), failed: _rand(1, flag?5:8), compliance_rate: _randF(flag?88:72, flag?97:88, 1), today_checked: _rand(12,20) },
            cost_stats: { total_po_amount: _randF(8000,15000,0), total_actual_amount: _randF(7800,15200,0), variance_rate_pct: _randF(-2.5,3.5), batches_today: _rand(5,12), reject_count: flag?0:_rand(0,2) },
            turnover_suggestions: Array.from({length: _rand(1,3)}, (_,i) => ({ table_id: `T${String(i+1).padStart(2,'0')}`, state:'need_clean', action:'安排保洁清台' })),
            active_alerts: _rand(0,3),
        };
    }

    function genLossRisk(storeId, limit=5) {
        return Array.from({length: _rand(2,Math.min(limit,5))}, (_,i) => ({
            batch_id: `B${new Date().toISOString().slice(0,10).replace(/-/g,'')}${String(i+1).padStart(3,'0')}`,
            sku: SKU_LIST[_rand(0,SKU_LIST.length-1)], supplier: SUPPLIERS[_rand(0,2)],
            risk_score: _randF(0.3,0.95), risk_level: ['低','中','高'][Math.floor(_randF(0,2.99))],
            reason: ['短重超标','品质等级偏低','超温预警','临近效期'][_rand(0,3)],
            estimated_loss_amount: _randF(50,500,0), suggested_action: _randF(0.5,1)>0.6?'发起复称留证':'人工复核',
            ref_id: `RISK-${String(i+1).padStart(4,'0')}`, task_id: null,
        }));
    }

    function genLossBudget(storeId, limit=5) {
        return Array.from({length: _rand(3,Math.min(limit,6))}, (_,i) => ({
            sku: SKU_LIST[_rand(0,SKU_LIST.length-1)], forecast_qty: _rand(15,80), forecast_unit: '份',
            budget_loss_amount: _randF(30,200,0),
            reason: ['周末预测上调','历史均值偏高','节假日因素'][_rand(0,2)],
            ref_id: `BUDGET-${String(i+1).padStart(4,'0')}`,
        }));
    }

    function genEvents(storeId, limit=20) {
        const types = [
            ['冷链超温','critical','冷库温度异常，当前-12°C'],
            ['SOP违规','warn','收货未按标准拍照留证'],
            ['短重预警','warn','毛肚到货偏差-3.2%'],
            ['设备离线','info','前厅传感器恢复在线'],
            ['燃气浓度','critical','后厨燃气浓度偏高'],
            ['烟雾报警','warn','排烟系统效率下降'],
            ['品质降级','warn','鸭肠VLM评级为B级'],
            ['复称完成','info','批次复称完成，偏差正常'],
            ['SOP达标','info','SOP检查通过'],
            ['库存预警','info','虾滑库存低于安全线'],
        ];
        return Array.from({length: limit}, (_,i) => {
            const [t,l,m] = types[i % types.length];
            return { event_id: `EVT-${new Date().toISOString().slice(0,10)}-${String(i+1).padStart(4,'0')}`, event_type: t, level: l, message: m,
                source: ['IoT传感器','VLM视觉','SOP引擎','收货PDA','规则引擎'][_rand(0,4)], timestamp: _hoursAgo(_rand(0,Math.ceil(limit/2))), store_id: storeId };
        });
    }

    function genSopAssignments(status='') {
        const all = [
            { id:'SOP-001', sop_id:'SOP-RCV-001', sop_name:'收货验货拍照留证', assignee:'王厨师长', status:'pending', created_at:_hoursAgo(2) },
            { id:'SOP-002', sop_id:'SOP-KIT-003', sop_name:'开档食材温度抽检', assignee:'帮工A', status:'in_progress', created_at:_hoursAgo(1) },
            { id:'SOP-003', sop_id:'SOP-CLN-002', sop_name:'操作台清洁消毒', assignee:'帮工B', status:'passed', created_at:_hoursAgo(3) },
            { id:'SOP-004', sop_id:'SOP-STO-001', sop_name:'冻品入库分类存放', assignee:'王厨师长', status:'failed', created_at:_hoursAgo(5) },
            { id:'SOP-005', sop_id:'SOP-TEMP-001', sop_name:'冷库温度记录', assignee:'张店长', status:'passed', created_at:_hoursAgo(6) },
        ];
        return status ? all.filter(a=>a.status===status) : all;
    }

    function genIotReadings(sensor='cold_storage_1', hours=24) {
        const base = sensor.includes('cold') ? -18 : 4;
        return Array.from({length: hours*2}, (_,i) => ({
            sensor_id: sensor, temperature: _randF(base-1.5, base+1.5, 1),
            humidity: sensor.includes('cold') ? _randF(65,85,1) : null,
            timestamp: new Date(Date.now() - 1800000*i).toLocaleString('zh-CN'),
            status: Math.abs(_randF(base-1.5, base+1.5, 1)-base)<2 ? 'normal' : 'alert',
        }));
    }

    function genIotDevices(requiredOnly=true) {
        const devs = [
            { device_id:'cold_storage_1', name:'一号冷库', type:'temperature', status:'online', last_reading:_now(), battery:87 },
            { device_id:'cold_storage_2', name:'二号冷库', type:'temperature', status:'online', last_reading:_now(), battery:92 },
            { device_id:'freezer_1', name:'速冻柜', type:'temperature', status:'online', last_reading:_now(), battery:65 },
            { device_id:'gas_1', name:'燃气探测器', type:'gas', status:'online', last_reading:_now(), battery:100 },
            { device_id:'smoke_1', name:'烟雾探测器', type:'smoke', status:'online', last_reading:_now(), battery:95 },
            { device_id:'cam_kitchen_1', name:'后厨摄像头A', type:'camera', status:'online', last_reading:_now() },
            { device_id:'cam_receiving_1', name:'收货区摄像头', type:'camera', status:'offline', last_reading:_hoursAgo(2) },
        ];
        return requiredOnly ? devs.filter(d=>d.status==='online') : devs;
    }

    function genAlertPushes(storeId, limit=20) {
        const lvls = [['critical','🔴 严重告警'],['warn','🟡 预警'],['info','🔵 信息']];
        return Array.from({length:Math.min(limit,10)}, (_,i) => {
            const [l,pfx] = lvls[i%3];
            return { id:`PUSH-${String(i+1).padStart(4,'0')}`, title:`${pfx} ${['冷链','SOP','损耗','设备'][_rand(0,3)]}通知`,
                body:`${['椒江店','玉环店'][_rand(0,1])}${['冷库温度异常','SOP未达标','短重预警','设备离线'][_rand(0,3)]}\n时间: ${_hoursAgo(_rand(0,10))}\n状态: ${i>5?'已处理':'待确认'}`,
                level:l, store_id:storeId, created_at:_hoursAgo(_rand(0,10)), push_status: i%3===0?'sent':'delivered' };
        });
    }

    function genDailyReports(storeId, limit=30) {
        return Array.from({length:Math.min(limit,14)}, (_,i) => {
            const d = new Date(); d.setDate(d.getDate()-i);
            const ds = d.toISOString().slice(0,10);
            return { report_id:`RPT-${ds.replace(/-/g,'')}`, report_date:ds, store_id:storeId,
                status: i>0?'published':'draft', generated_at:`${ds} 22:00:00`, pushed: i>0&&i<7,
                summary: { revenue:_randF(15000,45000,0), tables_served:_rand(80,200), sop_rate:_randF(82,96,1), loss_amount:_randF(200,1200,0), alert_count:_rand(0,5) } };
        });
    }

    function genBenchmark() {
        return { industry_avg:{sop_rate:78.5, loss_rate:3.2, table_turnover:4.1},
            top_performer:{store:'冯校长火锅·椒江店', sop_rate:94.2, loss_rate:1.1, table_turnover:5.8 },
            chain_avg:{sop_rate:85.0, loss_rate:2.1, table_turnover:4.9 },
            your_store:{sop_rate:92.0, loss_rate:1.5, table_turnover:5.4 } };
    }

    function genRegionOverview() {
        return { region_id:'taizhou', region_name:'台州区域', store_count:2, total_tables:32, avg_health_score:85, avg_sop_rate:87.5, total_alerts_today:5,
            stores: Object.values(STORES).map(s=>({...s, today_revenue:_randF(20000,50000,0)})) };
    }

    function genNationalOverview() {
        return { total_stores:2, active_stores:2, regions:1, national_avg_health:85, trend:'+2.3 vs 上周',
            top_stores:[{rank:1,name:'冯校长火锅·椒江店',score:92,trend:'↑'},{rank:2,name:'冯校长火锅·玉环店',score:78,trend:'↑'}] };
    }

    function genAdminOrgTree() {
        return { org_id:'hotpot_zhejiang', name:'浙江总代', children:[{ org_id:'reg_taizhou', name:'台州区域', role:'区域督导', user:'潘总',
            children:[{ org_id:'store_jiaojiang', name:'椒江店', role:'店长', user:'张店长' },{ org_id:'store_yuhuan', name:'玉环店', role:'店长', user:'李店长' }] }] };
    }

    function genPipelineStatus() {
        return { status:'running', mode:'inprocess', tick_count:_rand(100,9999), last_tick:_now(), stores_processed:2, anomalies_detected:_rand(0,3), tasks_created:_rand(0,5) };
    }

    function genAuditLogs(limit=20) {
        const users=[{name:'张店长',role:'店长'},{name:'李店长',role:'店长'},{name:'潘总',role:'区域督导'},{name:'系统管理员',role:'总部PMO'}];
        const actions=['登录','查看报表','修改门店配置','确认告警','导出数据'];
        const targets=['门店配置','SOP任务','告警事件','用户权限'];
        return Array.from({length:Math.min(limit,15)}, (_,i)=>({
            log_id:`AUDIT-${String(i+1).padStart(4,'0')}`, user:users[_rand(0,users.length-1)].name, role:users[_rand(0,users.length-1)].role,
            action:actions[_rand(0,actions.length-1)], target:targets[_rand(0,targets.length-1)], timestamp:_hoursAgo(_rand(0,limit)),
            ip:`192.168.${_rand(1,255)}.${_rand(1,255)}` }));
    }

    function genErp(storeId) {
        return { sync_status:'ok', last_sync:_hoursAgo(1), po_count:_rand(5,15), grn_count:_rand(3,10), pending_invoices:_rand(0,3), suppliers:SUPPLIERS };
    }

    function genMetrics() {
        return { uptime_seconds:_rand(3600,604800), requests_total:_rand(1000,99999), requests_today:_rand(100,5000), active_connections:_rand(1,20),
            db_queries_total:_rand(5000,500000), avg_response_ms:_randF(10,150,1), error_rate_pct:_randF(0,0.5,2) };
    }

    // ============================================================
    // 拦截 fetch
    // ============================================================
    const _origFetch = window.fetch;
    window.fetch = async function(url, opts) {
        const urlStr = typeof url === 'string' ? url : (url.url || url.toString());
        
        // 非API请求走原始fetch（静态资源等）
        if (!urlStr.includes('/v1/') && !urlStr.includes('/auth/') && !urlStr.match(/\/(health|metrics)(\?|$)/)) {
            return _origFetch.call(this, url, opts);
        }

        console.log('[Mock API]', opts?.method || 'GET', urlStr);

        // 解析参数
        const urlObj = new URL(urlStr, location.href);
        const storeId = urlObj.searchParams.get('store_id') || currentStoreId();
        const limit = parseInt(urlObj.searchParams.get('limit')||'20');
        const status = urlObj.searchParams.get('status')||'';
        const sensorId = urlObj.searchParams.get('sensor_id')||'cold_storage_1';
        const hours = parseInt(urlObj.searchParams.get('hours')||'24');

        let body = null;
        let status_code = 200;

        try {
            // Auth — 必须返回 access_token（core.js hubLogin 读取 tok.access_token）
            if (urlStr.includes('/auth/token')) {
                const creds = JSON.parse(opts?.body || '{}');
                body = { access_token: 'mock-token-' + Date.now(), user: {
                    username: creds.username||'zhangdian', name: creds.username==='admin'?'系统管理员':creds.username==='pangu'?'潘总':creds.username==='chushi'?'王厨师长':creds.username==='lidian'?'李店长':'张店长',
                    role: creds.username==='admin'?'总部PMO':creds.username==='pangu'?'区域督导':creds.username==='chushi'?'厨师长':'店长',
                    store_id: creds.store_id||(creds.username==='lidian'?'store_yuhuan':'store_jiaojiang'), storeId: creds.store_id||(creds.username==='lidian'?'store_yuhuan':'store_jiaojiang'),
                    storeName: (creds.username==='lidian'?STORES.store_yuhuan:STORES.store_jiaojiang).name,
                }};
            }
            else if (urlStr.includes('/auth/me')) {
                body = { username:'zhangdian', name:'张店长', role:'店长', store_id:storeId, storeId:storeId, storeName:getStore(storeId).name };
            }
            // Summary
            else if (urlStr.endsWith('/summary')) { body = genSummary(storeId); }
            // Cost
            else if (urlStr.includes('/loss-risk')) {
                if (opts?.method === 'POST' && urlStr.includes('/task')) { body = { task_id:`TASK-${Date.now()}`, status:'created' }; }
                else { body = { items: genLossRisk(storeId, limit) }; }
            }
            else if (urlStr.includes('/loss-budget')) { body = { items: genLossBudget(storeId, limit) }; }
            // SOP
            else if (urlStr.includes('/sop/ask')) { body = { answer:'根据SOP标准需要执行以下步骤：\n1.检查外包装完整性\n2.核对送货单与实物\n3.测量中心温度\n4.拍照留证\n5.系统录入', sources:['SOP-RCV-001','SOP-TEMP-001'], confidence:0.92 }; }
            else if (urlStr.includes('/sop/assignments')) {
                if (opts?.method === 'POST') { body = { id:`SOP-${_rand(100,999)}`, status:'assigned' }; }
                else if (opts?.method === 'PUT') { body = { status:'updated' }; }
                else { body = { items: genSopAssignments(status) }; }
            }
            else if (urlStr.includes('/sop/assign')) { body = { id:`SOP-${_rand(100,999)}`, status:'assigned' }; }
            // Alerts
            else if (urlStr.includes('/alerts/push-log')) { body = { items: genAlertPushes(storeId, limit) }; }
            else if (urlStr.includes('/alerts/acks')) { body = { acks:Array.from({length:5},(_,i)=>({event_id:`EVT-${i}`, acked_at:_hoursAgo(i)})) }; }
            else if (urlStr.includes('/alerts/routes')) { body = { routes:[{level:'critical',route:'企微+电话'},{level:'warn',route:'企微推送'},{level:'info',route:'仅记录'}] }; }
            else if (urlStr.includes('/alerts/escalations')) { body = { items:[] }; }
            else if (urlStr.includes('/alerts/ack') && opts?.method==='POST') { body = { ok:true }; }
            // Events
            else if (urlStr.includes('/events')) { body = { items: genEvents(storeId, limit) }; }
            // Stores
            else if (urlStr.endsWith('/stores')) { body = Object.values(STORES); }
            // IoT
            else if (urlStr.includes('/iot/readings')) { body = { readings: genIotReadings(sensorId, hours) }; }
            else if (urlStr.includes('/iot/devices')) { body = { devices: genIotDevices(urlObj.searchParams.get('required_only')!=='false') }; }
            // Reports
            else if (urlStr.includes('/reports/daily/generate')) { body = { report_id:`RPT-${new Date().toISOString().slice(0,10).replace(/-/g,'')}`, status:'generated', pushed:false }; }
            else if (urlStr.includes('/reports/daily')) { body = { reports: genDailyReports(storeId, limit) }; }
            // Region / Benchmark
            else if (urlStr.includes('/region/overview')) { body = genRegionOverview(); }
            else if (urlStr.includes('/benchmark')) { body = genBenchmark(); }
            else if (urlStr.includes('/national/overview')) { body = genNationalOverview(); }
            // Admin
            else if (urlStr.includes('/admin/org-tree')) { body = genAdminOrgTree(); }
            else if (urlStr.includes('/admin/stores')) {
                if (opts?.method === 'POST') { body = {...JSON.parse(opts.body||'{}'), store_id:`store_new_${_rand(100,999)}`, status:'created'}; status_code=201; }
                else if (opts?.method === 'PUT') { body = { status:'updated' }; }
                else { body = { stores:Object.values(STORES) }; }
            }
            else if (urlStr.includes('/admin/pipeline/status')) { body = genPipelineStatus(); }
            else if (urlStr.includes('/admin/pipeline/tick')) { body = genPipelineStatus(); }
            else if (urlStr.includes('/admin/audit-logs')) { body = { logs: genAuditLogs(limit) }; }
            // System
            else if (urlStr.match(/\/health(\?|$)/)) { body = { status:'ok', service:'火瞳平台端 Demo (云端)', version:'1.0.0-cloud-mock', mode:'demo', timestamp:_now() }; }
            else if (urlStr.match(/\/metrics(\?|$)/)) { body = genMetrics(); }
            // ERP
            else if (urlStr.includes('/erp')) { body = genErp(storeId); }
            // Audit
            else if (urlStr.includes('/audit/acks')) { body = { store_id:urlObj.searchParams.get('store_id')||storeId, audit_items:[] }; }
            else {
                // 未匹配的API返回空
                console.warn('[Mock] Unhandled API:', urlStr);
                body = { detail: 'Not implemented in mock mode' };
                status_code = 404;
            }
        } catch(e) {
            body = { detail: e.message };
            status_code = 500;
        }

        // 返回模拟 Response
        return new Response(JSON.stringify(body), {
            status: status_code,
            headers: { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' },
        });
    };

    // 标记已加载
    window.__HOTPOT_MOCK_LOADED = true;
    console.log('✅ 火瞳云端 Mock 数据层已加载 — 所有API调用将返回Demo数据');

})();
