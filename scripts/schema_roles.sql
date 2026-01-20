-- scripts/schema_roles.sql

CREATE TABLE IF NOT EXISTS public.role_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID REFERENCES public.tenants(id),
    department TEXT NOT NULL,
    function TEXT NOT NULL,
    system_persona TEXT NOT NULL,
    allowed_modes TEXT[] DEFAULT '{agentshield-secure}',
    pii_policy TEXT DEFAULT 'REDACT', -- 'REDACT' or 'BLOCK'
    max_tokens INTEGER DEFAULT 4000,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(tenant_id, department, function)
);

-- Enable RLS
ALTER TABLE public.role_definitions ENABLE ROW LEVEL SECURITY;

-- Simple RLS: Tenants can only see their own roles
DROP POLICY IF EXISTS "Tenants see own roles" ON public.role_definitions;
CREATE POLICY "Tenants see own roles" ON public.role_definitions
    USING (tenant_id = (current_setting('app.current_tenant_id', true)::uuid));
