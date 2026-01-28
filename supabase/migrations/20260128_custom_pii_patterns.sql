-- AgentShield: Custom PII Patterns (Dynamic Configuration) - IDEMPOTENT VERSION
-- This enables tenant/department/user level PII pattern customization with LLM assistance

-- Drop existing table if recreating (comment out if you want to preserve data)
-- DROP TABLE IF EXISTS custom_pii_patterns CASCADE;

CREATE TABLE IF NOT EXISTS custom_pii_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Hierarchical Scoping (Tenant → Department → User)
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Pattern Definition
    pattern_name VARCHAR(100) NOT NULL,
    pattern_type VARCHAR(50) NOT NULL,
    regex_pattern TEXT NOT NULL,
    redaction_strategy VARCHAR(50) DEFAULT 'FULL',  -- FULL, PARTIAL, HINT
    
    -- LLM Generation Metadata
    is_active BOOLEAN DEFAULT true,
    confidence_score FLOAT CHECK (confidence_score >= 0 AND confidence_score <= 1),
    generated_by_llm BOOLEAN DEFAULT false,
    llm_prompt TEXT,
    llm_model VARCHAR(50) DEFAULT 'gpt-4',
    
    -- Test Examples (JSON array)
    test_examples JSONB DEFAULT '[]'::jsonb,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id),
    
    -- Constraints: At least one scope must be defined
    CONSTRAINT valid_scope CHECK (
        (tenant_id IS NOT NULL) OR
        (department_id IS NOT NULL) OR
        (user_id IS NOT NULL)
    )
);

-- Drop existing indexes if they exist
DROP INDEX IF EXISTS idx_custom_pii_tenant;
DROP INDEX IF EXISTS idx_custom_pii_department;
DROP INDEX IF EXISTS idx_custom_pii_user;
DROP INDEX IF EXISTS idx_custom_pii_active;
DROP INDEX IF EXISTS idx_custom_pii_hierarchy;
DROP INDEX IF EXISTS idx_custom_pii_pattern_name;

-- Hierarchical indexes for fast lookup
CREATE INDEX idx_custom_pii_tenant ON custom_pii_patterns(tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX idx_custom_pii_department ON custom_pii_patterns(department_id) WHERE department_id IS NOT NULL;
CREATE INDEX idx_custom_pii_user ON custom_pii_patterns(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_custom_pii_active ON custom_pii_patterns(is_active) WHERE is_active = true;

-- Composite index for hierarchical queries
CREATE INDEX idx_custom_pii_hierarchy ON custom_pii_patterns(tenant_id, department_id, user_id);

-- Full-text search on pattern names
CREATE INDEX idx_custom_pii_pattern_name ON custom_pii_patterns USING gin(to_tsvector('english', pattern_name));

-- Drop existing trigger if exists
DROP TRIGGER IF EXISTS trigger_custom_pii_patterns_updated_at ON custom_pii_patterns;

-- Auto-update timestamp
CREATE OR REPLACE FUNCTION update_custom_pii_patterns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_custom_pii_patterns_updated_at
    BEFORE UPDATE ON custom_pii_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_custom_pii_patterns_updated_at();

-- Row Level Security
ALTER TABLE custom_pii_patterns ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS custom_pii_patterns_select_policy ON custom_pii_patterns;
DROP POLICY IF EXISTS custom_pii_patterns_insert_policy ON custom_pii_patterns;
DROP POLICY IF EXISTS custom_pii_patterns_update_policy ON custom_pii_patterns;
DROP POLICY IF EXISTS custom_pii_patterns_delete_policy ON custom_pii_patterns;

-- Policy: Users can see patterns from their tenant and more specific scopes
CREATE POLICY custom_pii_patterns_select_policy ON custom_pii_patterns
    FOR SELECT
    USING (
        -- User can see tenant-level patterns from their tenant
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
        -- User can see department-level patterns from their department
        OR department_id IN (SELECT department_id FROM user_profiles WHERE user_id = auth.uid())
        -- User can see their own user-level patterns
        OR user_id = auth.uid()
    );

-- Policy: Users with appropriate permissions can insert patterns
CREATE POLICY custom_pii_patterns_insert_policy ON custom_pii_patterns
    FOR INSERT
    WITH CHECK (
        -- Must belong to user's tenant
        tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- Policy: Users can update patterns they created or have access to
CREATE POLICY custom_pii_patterns_update_policy ON custom_pii_patterns
    FOR UPDATE
    USING (
        created_by = auth.uid()
        OR tenant_id IN (SELECT tenant_id FROM user_profiles WHERE user_id = auth.uid())
    );

-- Policy: Users can delete patterns they created
CREATE POLICY custom_pii_patterns_delete_policy ON custom_pii_patterns
    FOR DELETE
    USING (created_by = auth.uid());

COMMENT ON TABLE custom_pii_patterns IS 'Dynamic PII pattern configuration with hierarchical scoping (Tenant → Department → User) and LLM generation support';
COMMENT ON COLUMN custom_pii_patterns.tenant_id IS 'Tenant-level patterns apply to all users in tenant';
COMMENT ON COLUMN custom_pii_patterns.department_id IS 'Department-level patterns apply to all users in department';
COMMENT ON COLUMN custom_pii_patterns.user_id IS 'User-level patterns apply only to specific user';
COMMENT ON COLUMN custom_pii_patterns.redaction_strategy IS 'FULL: complete redaction, PARTIAL: preserve context, HINT: show first chars';
COMMENT ON COLUMN custom_pii_patterns.confidence_score IS 'LLM confidence score (0-1) for generated patterns';
