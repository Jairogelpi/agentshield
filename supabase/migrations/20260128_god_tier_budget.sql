-- God Tier Budget System: User Quotas + Prepaid Wallets + Anomaly Detection
-- Revolutionary FinOps with ML-powered spend protection

-- ============================================================================
-- 1. User-Level Quotas (Actor-Level Budget Control)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_quotas (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    
    -- Quota Limits
    daily_limit_usd NUMERIC(10, 2) DEFAULT 10.00,
    monthly_limit_usd NUMERIC(10, 2) DEFAULT 300.00,
    
    -- Current Spend Tracking
    current_daily_spend NUMERIC(10, 2) DEFAULT 0,
    current_monthly_spend NUMERIC(10, 2) DEFAULT 0,
    
    -- Reset Timestamps
    last_reset_daily TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_reset_monthly TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CHECK (daily_limit_usd >= 0),
    CHECK (monthly_limit_usd >= 0),
    CHECK (current_daily_spend >= 0),
    CHECK (current_monthly_spend >= 0)
);

-- Indexes for user quotas
CREATE INDEX idx_user_quotas_tenant ON user_quotas(tenant_id);
CREATE INDEX idx_user_quotas_daily_reset ON user_quotas(last_reset_daily) WHERE current_daily_spend > 0;
CREATE INDEX idx_user_quotas_monthly_reset ON user_quotas(last_reset_monthly) WHERE current_monthly_spend > 0;

-- Function to auto-reset daily quotas
CREATE OR REPLACE FUNCTION reset_daily_user_quotas()
RETURNS void AS $$
BEGIN
    UPDATE user_quotas
    SET 
        current_daily_spend = 0,
        last_reset_daily = NOW()
    WHERE last_reset_daily < NOW() - INTERVAL '24 hours';
END;
$$ LANGUAGE plpgsql;

-- Function to auto-reset monthly quotas
CREATE OR REPLACE FUNCTION reset_monthly_user_quotas()
RETURNS void AS $$
BEGIN
    UPDATE user_quotas
    SET 
        current_monthly_spend = 0,
        last_reset_monthly = NOW()
    WHERE last_reset_monthly < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 2. Prepaid Wallet System
-- ============================================================================

-- Extend existing wallets table
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS wallet_type TEXT DEFAULT 'POSTPAID' CHECK (wallet_type IN ('POSTPAID', 'PREPAID'));
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS overdraft_protection BOOLEAN DEFAULT false;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS low_balance_threshold NUMERIC(10, 2) DEFAULT 5.00;
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS last_low_balance_alert TIMESTAMP WITH TIME ZONE;

-- Wallet top-ups table
CREATE TABLE IF NOT EXISTS wallet_top_ups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    
    -- Top-up Details
    amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
    payment_method TEXT,  -- STRIPE, PAYPAL, CRYPTO, MANUAL
    
    -- Status Tracking
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED', 'REFUNDED')),
    
    -- External References
    payment_intent_id TEXT,  -- Stripe payment intent
    transaction_id TEXT,     -- External transaction ID
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by UUID REFERENCES auth.users(id),
    
    -- Notes
    notes TEXT
);

-- Indexes for top-ups
CREATE INDEX idx_wallet_top_ups_wallet ON wallet_top_ups(wallet_id);
CREATE INDEX idx_wallet_top_ups_status ON wallet_top_ups(status) WHERE status = 'PENDING';
CREATE INDEX idx_wallet_top_ups_created ON wallet_top_ups(created_at DESC);

-- ============================================================================
-- 3. AI-Driven Anomaly Detection
-- ============================================================================

-- Spend anomalies table
CREATE TABLE IF NOT EXISTS spend_anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Subject of Anomaly
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    
    -- Detection Details
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    anomaly_score FLOAT NOT NULL CHECK (anomaly_score >= 0 AND anomaly_score <= 1),
    
    -- Spend Analysis
    spend_baseline NUMERIC(10, 2) NOT NULL,
    spend_actual NUMERIC(10, 2) NOT NULL,
    spend_deviation_pct NUMERIC(5, 2),  -- Percentage deviation from baseline
    
    -- Time Window
    time_window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    time_window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- Action Taken
    action_taken TEXT CHECK (action_taken IN ('ALERT', 'THROTTLE', 'BLOCK', 'NONE')),
    severity TEXT DEFAULT 'LOW' CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    
    -- Resolution
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES auth.users(id),
    resolution_note TEXT,
    
    -- ML Model Info
    model_version TEXT DEFAULT 'v1.0',
    features_used JSONB,
    
    -- Notifications
    notification_sent BOOLEAN DEFAULT false,
    notification_channels JSONB DEFAULT '["email"]'::jsonb
);

-- Indexes for anomalies
CREATE INDEX idx_spend_anomalies_user ON spend_anomalies(user_id);
CREATE INDEX idx_spend_anomalies_tenant ON spend_anomalies(tenant_id);
CREATE INDEX idx_spend_anomalies_unresolved ON spend_anomalies(resolved) WHERE resolved = false;
CREATE INDEX idx_spend_anomalies_detected ON spend_anomalies(detected_at DESC);
CREATE INDEX idx_spend_anomalies_severity ON spend_anomalies(severity, resolved) WHERE resolved = false;

-- Composite index for anomaly dashboard
CREATE INDEX idx_spend_anomalies_dashboard ON spend_anomalies(tenant_id, resolved, detected_at DESC);

-- ============================================================================
-- Row Level Security
-- ============================================================================

-- User Quotas RLS
ALTER TABLE user_quotas ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_quotas_select_policy ON user_quotas
    FOR SELECT
    USING (
        user_id = auth.uid()
        OR tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- Wallet Top-ups RLS
ALTER TABLE wallet_top_ups ENABLE ROW LEVEL SECURITY;

CREATE POLICY wallet_top_ups_select_policy ON wallet_top_ups
    FOR SELECT
    USING (
        wallet_id IN (
            SELECT id FROM wallets WHERE tenant_id IN (
                SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid()
            )
        )
    );

-- Spend Anomalies RLS
ALTER TABLE spend_anomalies ENABLE ROW LEVEL SECURITY;

CREATE POLICY spend_anomalies_select_policy ON spend_anomalies
    FOR SELECT
    USING (
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE user_quotas IS 'Per-user budget quotas with daily and monthly limits';
COMMENT ON TABLE wallet_top_ups IS 'Prepaid wallet top-up transactions';
COMMENT ON TABLE spend_anomalies IS 'ML-detected spending anomalies for fraud prevention';

COMMENT ON COLUMN wallets.wallet_type IS 'POSTPAID: bill later, PREPAID: real-time deduction';
COMMENT ON COLUMN spend_anomalies.anomaly_score IS 'ML model score (0-1), higher = more anomalous';
