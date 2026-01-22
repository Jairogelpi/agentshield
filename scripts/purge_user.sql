-- ⚠️ DANGEROUS: Complete User Data Purge Script
-- This script deletes ALL data associated with a user from ALL tables
-- Run in Supabase SQL Editor

-- 🔴 SET YOUR USER ID HERE:
DO $$
DECLARE
    target_user_id UUID := '660b9702-3405-4b5f-813d-539ae0a3afa0';  -- Replace with actual user ID
    target_tenant_id UUID;
BEGIN
    -- 1. Find the user's tenant (column is user_id, not owner_id)
    SELECT id INTO target_tenant_id FROM tenants WHERE user_id = target_user_id LIMIT 1;
    
    RAISE NOTICE 'Purging User: % | Tenant: %', target_user_id, target_tenant_id;

    -- 2. Delete from all tenant-scoped tables
    IF target_tenant_id IS NOT NULL THEN
        -- Financial/Wallets
        DELETE FROM wallets WHERE tenant_id = target_tenant_id;
        DELETE FROM cost_centers WHERE tenant_id = target_tenant_id;
        DELETE FROM departments WHERE tenant_id = target_tenant_id;
        DELETE FROM authorizations WHERE tenant_id = target_tenant_id;
        DELETE FROM receipts WHERE tenant_id = target_tenant_id;
        DELETE FROM internal_ledger WHERE tenant_id = target_tenant_id;
        DELETE FROM pending_transactions_log WHERE tenant_id = target_tenant_id::text;
        
        -- Policies & Governance
        DELETE FROM policy_events WHERE tenant_id = target_tenant_id;
        DELETE FROM policies WHERE tenant_id = target_tenant_id;
        DELETE FROM semantic_budgets WHERE tenant_id = target_tenant_id;
        DELETE FROM intent_definitions WHERE tenant_id = target_tenant_id;
        DELETE FROM config_snapshots WHERE tenant_id = target_tenant_id;
        
        -- Security & Compliance
        DELETE FROM quarantine_queue WHERE tenant_id = target_tenant_id;
        DELETE FROM custom_pii_rules WHERE tenant_id = target_tenant_id;
        DELETE FROM compliance_certificates WHERE tenant_id = target_tenant_id;
        DELETE FROM compliance_actions WHERE tenant_id = target_tenant_id;
        DELETE FROM security_events WHERE tenant_id = target_tenant_id;
        DELETE FROM semantic_whitelist WHERE tenant_id = target_tenant_id;
        
        -- SIEM & Automation
        DELETE FROM automation_rules WHERE tenant_id = target_tenant_id;
        DELETE FROM event_destinations WHERE tenant_id = target_tenant_id;
        DELETE FROM system_events WHERE tenant_id = target_tenant_id;
        
        -- Vault & Knowledge
        DELETE FROM vault_chunks WHERE tenant_id = target_tenant_id;
        DELETE FROM vault_documents WHERE tenant_id = target_tenant_id;
        DELETE FROM revenue_splits WHERE collection_id IN (SELECT id FROM knowledge_collections WHERE tenant_id = target_tenant_id);
        DELETE FROM marketplace_listings WHERE collection_id IN (SELECT id FROM knowledge_collections WHERE tenant_id = target_tenant_id);
        DELETE FROM active_subscriptions WHERE tenant_id = target_tenant_id;
        DELETE FROM knowledge_collections WHERE tenant_id = target_tenant_id;
        DELETE FROM knowledge_assets WHERE tenant_id = target_tenant_id;
        
        -- Tools & Approvals
        DELETE FROM tool_approvals WHERE tenant_id = target_tenant_id;
        DELETE FROM tool_policies WHERE tenant_id = target_tenant_id;
        DELETE FROM tool_definitions WHERE tenant_id = target_tenant_id;
        
        -- Other
        DELETE FROM hive_memory WHERE tenant_id = target_tenant_id;
        DELETE FROM carbon_ledger WHERE tenant_id = target_tenant_id;
        DELETE FROM flight_recorder_logs WHERE tenant_id = target_tenant_id;
        DELETE FROM forensic_receipts WHERE tenant_id = target_tenant_id;
        DELETE FROM semantic_cache_logs WHERE tenant_id = target_tenant_id;
        DELETE FROM webhooks WHERE tenant_id = target_tenant_id;
        DELETE FROM function_configs WHERE tenant_id = target_tenant_id;
        DELETE FROM role_definitions WHERE id IN (SELECT id FROM role_definitions); -- Check if tenant-scoped
    END IF;

    -- 3. Delete from user-scoped tables (by user_id directly)
    DELETE FROM user_profiles WHERE user_id = target_user_id;
    DELETE FROM trust_events WHERE user_id = target_user_id;
    DELETE FROM reputation_ledger WHERE user_id = target_user_id;

    -- 4. Delete the tenant itself
    IF target_tenant_id IS NOT NULL THEN
        DELETE FROM tenants WHERE id = target_tenant_id;
    END IF;

    RAISE NOTICE '✅ Purge complete for user %', target_user_id;
END $$;

-- 5. DELETE USER FROM SUPABASE AUTH
-- Run this AFTER the above script completes successfully.
-- Replace YOUR_USER_ID_HERE with the actual UUID.

-- Option A: Via Supabase Dashboard
-- Go to Authentication > Users > Find the user > Delete

-- Option B: Via Supabase Admin API (in a backend script)
-- await supabase.auth.admin.deleteUser('YOUR_USER_ID_HERE')
