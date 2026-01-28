-- EU AI Act Compliance: Human-in-the-Loop Approval Queue
-- For HIGH_RISK operations requiring human oversight (Annex III)

CREATE TABLE IF NOT EXISTS ai_act_approval_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Request Information
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES auth.users(id) NOT NULL,
    trace_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    
    -- EU AI Act Classification
    risk_level TEXT NOT NULL CHECK (risk_level IN ('HIGH_RISK', 'PROHIBITED')),
    risk_category TEXT NOT NULL,  -- HR_RECRUITMENT, MEDICAL_DIAGNOSIS, etc.
    article_reference TEXT DEFAULT 'Annex III',
    
    -- Request Details
    request_summary TEXT NOT NULL,
    full_request JSONB NOT NULL,
    classification_confidence FLOAT,
    
    -- Approval Workflow
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
    approver_id UUID REFERENCES auth.users(id),
    approval_note TEXT,
    rejection_reason TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    decided_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '24 hours'),
    
    -- Notification
    notification_sent BOOLEAN DEFAULT false,
    notification_channels JSONB DEFAULT '["email"]'::jsonb
);

-- Indexes for performance
CREATE INDEX idx_ai_act_approval_tenant ON ai_act_approval_queue(tenant_id);
CREATE INDEX idx_ai_act_approval_status ON ai_act_approval_queue(status) WHERE status = 'PENDING';
CREATE INDEX idx_ai_act_approval_user ON ai_act_approval_queue(user_id);
CREATE INDEX idx_ai_act_approval_created ON ai_act_approval_queue(created_at DESC);

-- Composite index for dashboard queries
CREATE INDEX idx_ai_act_approval_tenant_status ON ai_act_approval_queue(tenant_id, status, created_at DESC);

-- Auto-expire old pending requests
CREATE OR REPLACE FUNCTION expire_old_ai_act_approvals()
RETURNS void AS $$
BEGIN
    UPDATE ai_act_approval_queue
    SET status = 'EXPIRED'
    WHERE status = 'PENDING'
      AND expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- Scheduled job (run every hour)
-- SELECT cron.schedule('expire-ai-act-approvals', '0 * * * *', 'SELECT expire_old_ai_act_approvals()');

-- Row Level Security
ALTER TABLE ai_act_approval_queue ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see approvals from their tenant
CREATE POLICY ai_act_approval_select_policy ON ai_act_approval_queue
    FOR SELECT
    USING (
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- Policy: Users can approve if they have permission
CREATE POLICY ai_act_approval_update_policy ON ai_act_approval_queue
    FOR UPDATE
    USING (
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
        AND status = 'PENDING'
    );

COMMENT ON TABLE ai_act_approval_queue IS 'EU AI Act Article 14 - Human oversight queue for HIGH_RISK AI operations';
COMMENT ON COLUMN ai_act_approval_queue.risk_category IS 'EU AI Act Annex III category (e.g., HR_RECRUITMENT, MEDICAL_DIAGNOSIS)';
COMMENT ON COLUMN ai_act_approval_queue.expires_at IS 'Requests auto-expire after 24h if not decided';
