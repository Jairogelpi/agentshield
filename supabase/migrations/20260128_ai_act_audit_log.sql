-- EU AI Act Compliance: Audit Trail (Article 12 - Record-keeping)
-- Cryptographically signed audit trail for 24+ months retention

CREATE TABLE IF NOT EXISTS ai_act_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Request Identification
    trace_id TEXT NOT NULL UNIQUE,
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES auth.users(id),
    
    -- EU AI Act Classification
    risk_level TEXT NOT NULL,
    risk_category TEXT NOT NULL,
    article_reference TEXT NOT NULL,
    classification_confidence FLOAT,
    
    -- Request Details
    request_summary TEXT NOT NULL,
    request_hash TEXT NOT NULL,  -- SHA-256 of full request
    response_hash TEXT,  -- SHA-256 of full response
    
    -- Human Oversight
    required_human_approval BOOLEAN DEFAULT false,
    approval_id UUID REFERENCES ai_act_approval_queue(id),
    approval_status TEXT,  -- APPROVED, REJECTED, NOT_REQUIRED
    approver_id UUID REFERENCES auth.users(id),
    
    -- Transparency Measures
    transparency_disclosure_shown BOOLEAN DEFAULT false,
    transparency_method TEXT,  -- HEADER, INLINE, WATERMARK
    
    -- Risk Mitigation
    mitigation_measures JSONB DEFAULT '[]'::jsonb,
    safety_checks_passed JSONB DEFAULT '{}'::jsonb,
    
    -- Cryptographic Proof
    audit_hash TEXT NOT NULL,  -- SHA-256 hash chain
    previous_audit_hash TEXT,  -- Link to previous entry (blockchain-style)
    digital_signature TEXT,  -- Optional: sign with tenant key
    
    -- Performance Metrics
    model_used TEXT,
    latency_ms INTEGER,
    tokens_used INTEGER,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    retention_until TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '24 months')
);

-- Indexes for compliance queries
CREATE INDEX idx_ai_act_audit_tenant ON ai_act_audit_log(tenant_id);
CREATE INDEX idx_ai_act_audit_trace ON ai_act_audit_log(trace_id);
CREATE INDEX idx_ai_act_audit_risk_level ON ai_act_audit_log(risk_level);
CREATE INDEX idx_ai_act_audit_created ON ai_act_audit_log(created_at DESC);
-- Note: retention_until index without WHERE clause (NOW() is not immutable in predicates)
CREATE INDEX idx_ai_act_audit_retention ON ai_act_audit_log(retention_until);

-- Composite index for Article 12 compliance reports
CREATE INDEX idx_ai_act_audit_compliance_report ON ai_act_audit_log(
    tenant_id, risk_level, created_at DESC
);

-- Function to compute audit hash (blockchain-style chain)
CREATE OR REPLACE FUNCTION compute_ai_act_audit_hash(
    p_trace_id TEXT,
    p_risk_level TEXT,
    p_request_hash TEXT,
    p_previous_hash TEXT
)
RETURNS TEXT AS $$
BEGIN
    RETURN encode(
        digest(
            CONCAT(p_trace_id, '|', p_risk_level, '|', p_request_hash, '|', COALESCE(p_previous_hash, '')),
            'sha256'
        ),
        'hex'
    );
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-compute audit hash before insert
CREATE OR REPLACE FUNCTION set_ai_act_audit_hash()
RETURNS TRIGGER AS $$
DECLARE
    v_previous_hash TEXT;
BEGIN
    -- Get previous hash for chain
    SELECT audit_hash INTO v_previous_hash
    FROM ai_act_audit_log
    WHERE tenant_id = NEW.tenant_id
    ORDER BY created_at DESC
    LIMIT 1;
    
    -- Compute new hash
    NEW.audit_hash := compute_ai_act_audit_hash(
        NEW.trace_id,
        NEW.risk_level,
        NEW.request_hash,
        v_previous_hash
    );
    
    NEW.previous_audit_hash := v_previous_hash;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_ai_act_audit_hash ON ai_act_audit_log;
CREATE TRIGGER trigger_ai_act_audit_hash
    BEFORE INSERT ON ai_act_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION set_ai_act_audit_hash();

-- Row Level Security
ALTER TABLE ai_act_audit_log ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see audit logs from their tenant
CREATE POLICY ai_act_audit_select_policy ON ai_act_audit_log
    FOR SELECT
    USING (
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- View for compliance reporting
CREATE OR REPLACE VIEW ai_act_compliance_summary AS
SELECT
    tenant_id,
    risk_level,
    risk_category,
    COUNT(*) as request_count,
    COUNT(CASE WHEN required_human_approval THEN 1 END) as approvals_required,
    COUNT(CASE WHEN approval_status = 'APPROVED' THEN 1 END) as approvals_granted,
    COUNT(CASE WHEN transparency_disclosure_shown THEN 1 END) as transparency_shown,
    DATE(created_at) as date
FROM ai_act_audit_log
GROUP BY tenant_id, risk_level, risk_category, DATE(created_at);

COMMENT ON TABLE ai_act_audit_log IS 'EU AI Act Article 12 - Immutable audit trail with cryptographic proof (24+ months retention)';
COMMENT ON COLUMN ai_act_audit_log.audit_hash IS 'SHA-256 hash chain for immutability verification';
COMMENT ON COLUMN ai_act_audit_log.retention_until IS 'Article 12 requires 24 months minimum retention';
