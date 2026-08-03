-- ============================================================
-- 火瞳 (HotpotEye) — Hub 统一审计 Schema
-- 版本: v1.0 | P0-B 统一主 Hub
-- ============================================================
--
-- 设计原则:
-- 1. append-only 表 (只追加，不更新/删除)
-- 2. correlation_id 全链路串联
-- 3. 与 Gateway 中间件集成
-- 4. 支持 RBAC 角色过滤
--

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. 审计事件主表 (append-only)
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_events (
    -- 主键
    id              BIGSERIAL PRIMARY KEY,
    audit_id        UUID NOT NULL DEFAULT uuid_generate_v4(),
    correlation_id  UUID NOT NULL DEFAULT uuid_generate_v4(),

    -- 时间戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 身份信息 (从 JWT 提取)
    user_id         VARCHAR(64) NOT NULL DEFAULT '',
    user_name       VARCHAR(128),
    role            VARCHAR(32) NOT NULL DEFAULT '',
    store_id        VARCHAR(32) NOT NULL DEFAULT '',
    ip_address      INET,

    -- 操作信息
    action_type     VARCHAR(64) NOT NULL,
    risk_level      VARCHAR(16) NOT NULL DEFAULT 'low',
    endpoint        VARCHAR(256) NOT NULL,
    method          VARCHAR(8) NOT NULL,

    -- 参数和结果 (JSONB)
    request_params  JSONB DEFAULT '{}',
    response_result JSONB,

    -- 状态机
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    -- 状态流转: pending -> approved -> executed
    --           pending -> rejected
    #           pending -> bypassed (低风险自动放行)
    #           pending -> executed (中风险自动执行)

    -- 审批信息
    approval_id     UUID,
    approver_id     VARCHAR(64),
    approved_at     TIMESTAMPTZ,
    approval_notes  TEXT,

    -- 元数据
    user_agent      TEXT,
    session_id      VARCHAR(128),

    -- 索引
    CONSTRAINT uk_audit UNIQUE (audit_id)
);

-- 索引 (查询优化)
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_store ON audit_events (store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events (action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_events (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_risk ON audit_events (risk_level, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events (created_at DESC);

-- 注释
COMMENT ON TABLE audit_events IS '审计事件主表 - append-only，记录所有受控操作';
COMMENT ON COLUMN audit_events.correlation_id IS '全链路追踪ID，串联请求→审批→执行→结果';
COMMENT ON COLUMN audit_events.status IS '状态: pending/approved/rejected/executed/bypassed';


-- ============================================================
-- 2. 审批任务表
-- ============================================================

CREATE TABLE IF NOT EXISTS approval_tasks (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID NOT NULL DEFAULT uuid_generate_v4(),
    correlation_id  UUID NOT NULL,

    -- 关联的审计事件
    audit_id        UUID NOT NULL REFERENCES audit_events(audit_id),

    -- 审批内容
    action_type     VARCHAR(64) NOT NULL,
    risk_level      VARCHAR(16) NOT NULL,
    summary         TEXT,

    -- 申请人
    applicant_id    VARCHAR(64) NOT NULL,
    applicant_role  VARCHAR(32) NOT NULL,
    store_id        VARCHAR(32) NOT NULL,

    -- 审批链
    required_approvers TEXT[] NOT NULL DEFAULT '{}',  -- 需要审批的角色列表
    current_step    INTEGER NOT NULL DEFAULT 0,

    -- 状态
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    -- pending → approved / rejected / expired / cancelled

    -- 时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    decided_at      TIMESTAMPTZ,

    -- 决策
    decision        VARCHAR(8),   -- approve / reject
    decision_by     VARCHAR(64),
    decision_notes  TEXT,

    CONSTRAINT uk_approval_task UNIQUE (task_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_audit ON approval_tasks (audit_id);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_tasks (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approval_applicant ON approval_tasks (applicant_id, created_at DESC);


-- ============================================================
-- 3. 操作日志表 (轻量级，用于调试和trace)
-- ============================================================

CREATE TABLE IF NOT EXISTS operation_log (
    id              BIGSERIAL PRIMARY KEY,
    log_id          UUID NOT NULL DEFAULT uuid_generate_v4(),
    correlation_id  UUID,

    -- 来源
    source          VARCHAR(32) NOT NULL,  -- edge_ui / hub / agent / scheduler
    component       VARCHAR(64) NOT NULL,  -- 模块名

    -- 日志级别和内容
    level           VARCHAR(8) NOT NULL DEFAULT 'info',
    message         TEXT NOT NULL,
    details         JSONB,

    -- 时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oplog_corr ON operation_log (correlation_id);
CREATE INDEX IF NOT EXISTS idx_oplog_source ON operation_log (source, created_at DESC);


-- ============================================================
-- 4. 数据变更追踪表 (用于关键业务实体)
-- ============================================================

CREATE TABLE IF NOT EXISTS data_change_log (
    id              BIGSERIAL PRIMARY KEY,
    change_id       UUID NOT NULL DEFAULT uuid_generate_v4(),
    correlation_id  UUID NOT NULL,

    -- 变更实体
    entity_type     VARCHAR(32) NOT NULL,  -- purchase_order / inventory / receiving_record
    entity_id       VARCHAR(64) NOT NULL,

    -- 变更类型
    change_type     VARCHAR(16) NOT NULL,  -- create / update / delete / approve / reject

    -- 快照 (JSONB)
    before_snapshot JSONB,                 -- 变更前完整数据
    after_snapshot  JSONB,                 -- 变更后完整数据
    changed_fields  TEXT[],                -- 变更字段列表

    -- 操作者
    operator_id     VARCHAR(64) NOT NULL,
    operator_role   VARCHAR(32) NOT NULL,

    -- 时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dcl_entity ON data_change_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_dcl_corr ON data_change_log (correlation_id);


-- ============================================================
-- 5. RBAC 权限变更审计 (可选，高安全场景)
-- ============================================================

CREATE TABLE IF NOT EXISTS rbac_change_log (
    id              BIGSERIAL PRIMARY KEY,
    change_id       UUID NOT NULL DEFAULT uuid_generate_v4(),
    correlation_id  UUID,

    -- 变更内容
    target_user_id  VARCHAR(64) NOT NULL,
    change_type     VARCHAR(16) NOT NULL,  -- grant / revoke / modify
    permission      VARCHAR(128),          -- 被变更的权限

    -- 快照
    before_roles    TEXT[],
    after_roles     TEXT[],

    -- 操作者
    operator_id     VARCHAR(64) NOT NULL,
    reason          TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- 视图: 审计仪表盘
-- ============================================================

CREATE OR REPLACE VIEW v_audit_dashboard AS
SELECT
    DATE(created_at) AS date,
    COUNT(*) FILTER (WHERE status = 'executed') AS executed_count,
    COUNT(*) FILTER (WHERE status = 'approved') AS approved_count,
    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count,
    COUNT(*) FILTER (WHERE risk_level = 'high') AS high_risk_count,
    COUNT(*) FILTER (WHERE risk_level = 'critical') AS critical_count,
    COUNT(*) AS total_count
FROM audit_events
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;


-- ============================================================
-- 清理策略: 保留90天数据
-- ============================================================

-- 创建清理函数 (由定时任务调用)
CREATE OR REPLACE FUNCTION cleanup_old_audit_data(retention_days INTEGER DEFAULT 90)
RETURNS void AS $$
BEGIN
    DELETE FROM audit_events WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
    DELETE FROM approval_tasks WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
    DELETE FROM operation_log WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
    DELETE FROM data_change_log WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
    RAISE NOTICE 'Cleaned audit data older than % days', retention_days;
END;
$$ LANGUAGE plpgsql;

-- 示例: 清理90天前的数据
-- SELECT cleanup_old_audit_data(90);
