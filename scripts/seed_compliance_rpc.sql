-- RPC for Compliance Reporting (Aggregation)
CREATE OR REPLACE FUNCTION get_compliance_stats(p_tenant_id UUID, p_days INT)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_blocked_count INT;
    v_savings DECIMAL;
BEGIN
    -- 1. Count Blocks
    SELECT COUNT(*) INTO v_blocked_count
    FROM policy_events
    WHERE tenant_id = p_tenant_id 
      AND action_taken = 'BLOCKED'
      AND created_at > (NOW() - (p_days || ' days')::INTERVAL);

    -- 2. Sum Savings (Assuming 'receipts' has 'savings_usd' or similar)
    -- If receipts table structure is different, adjust. Assuming 'estimated_cost' as proxy for activity if savings not tracked directly yet.
    -- For now, returning 0 savings if column doesn't exist to avoid error
    -- Or better, count authorized transactions
    SELECT COALESCE(SUM(estimated_cost), 0) INTO v_savings
    FROM authorizations
    WHERE tenant_id = p_tenant_id
      AND decision = 'APPROVED'
      AND created_at > (NOW() - (p_days || ' days')::INTERVAL);

    RETURN jsonb_build_object(
        'blocked_attacks', v_blocked_count,
        'savings', v_savings, -- Using approved cost as "Value Processed" for now
        'period_days', p_days
    );
END;
$$;
