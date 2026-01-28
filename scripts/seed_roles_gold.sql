-- app/scripts/seed_roles_gold.sql
-- GOD TIER ARCHETYPES + V2 SCHEMA UPGRADE
-- Use this to override default roles with "Deep Personas"

-- 0. COMPREHENSIVE SCHEMA REPAIR (Upgrades V1 table to V2)
DO $$
BEGIN
    -- 1. Add tenant_id if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='role_definitions' AND column_name='tenant_id') THEN
        ALTER TABLE role_definitions ADD COLUMN tenant_id UUID REFERENCES public.tenants(id);
    END IF;
    
    -- 2. Add metadata if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='role_definitions' AND column_name='metadata') THEN
        ALTER TABLE role_definitions ADD COLUMN metadata JSONB DEFAULT '{}';
    END IF;

    -- 3. Add ai_generated if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='role_definitions' AND column_name='ai_generated') THEN
        ALTER TABLE role_definitions ADD COLUMN ai_generated BOOLEAN DEFAULT FALSE;
    END IF;

    -- 4. Add allowed_modes if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='role_definitions' AND column_name='allowed_modes') THEN
        ALTER TABLE role_definitions ADD COLUMN allowed_modes TEXT[] DEFAULT '{agentshield-secure}';
    END IF;

    -- 5. Add pii_policy if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='role_definitions' AND column_name='pii_policy') THEN
        ALTER TABLE role_definitions ADD COLUMN pii_policy TEXT DEFAULT 'REDACT';
    END IF;

    -- 6. Ensure Unique Constraint exists
    -- We use a check to avoid duplication errors during schema migration
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name='role_definitions' AND constraint_type='UNIQUE'
        AND constraint_name='role_definitions_tenant_id_department_function_key' -- Potential default name
    ) THEN
        -- Safely try to add it, ignoring if exists under another name
        BEGIN
            ALTER TABLE role_definitions ADD CONSTRAINT role_definitions_unique_identity UNIQUE(tenant_id, department, function);
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Constraint might already exist or data duplicates found. Skipping.';
        END;
    END IF;

END $$;

-- 1. CLEANUP (Optional)
-- DELETE FROM role_definitions WHERE department IN ('Legal', 'Engineering');

-- 2. LEGAL EAGLE
INSERT INTO role_definitions (tenant_id, department, function, system_persona, pii_policy, allowed_modes, metadata, ai_generated)
VALUES (
    (SELECT id FROM tenants LIMIT 1), 
    'Legal',
    'Senior Counsel',
    'Eres un Asesor Legal Senior protegido por AgentShield. Tu marco cognitivo es "Verificación Forense".\n\nNo asumas hechos que no estén en el texto.\nSi detectas una ambigüedad contractual, señálala agresivamente.\nUsa un tono formal, distanciado y preciso.\nCita siempre la fuente de tus afirmaciones.',
    'BLOCK',
    '{"agentshield-secure"}', -- Note: Array syntax for Postgres
    '{
        "active_rules": ["Strict Liabilities", "No Assumptions", "Cite Sources"],
        "cognitive_framework": "Prioritize risk mitigation over speed. Assume worst-case interpretation.",
        "tone_guidelines": ["Formal", "Distanced", "Precise"],
        "communication_constraints": ["Never speculate on facts", "Never give financial advice"]
    }'::jsonb,
    false
)
ON CONFLICT (tenant_id, department, function) 
DO UPDATE SET 
    system_persona = EXCLUDED.system_persona,
    metadata = EXCLUDED.metadata,
    pii_policy = EXCLUDED.pii_policy,
    allowed_modes = EXCLUDED.allowed_modes;

-- 3. CODE NINJA
INSERT INTO role_definitions (tenant_id, department, function, system_persona, pii_policy, allowed_modes, metadata, ai_generated)
VALUES (
    (SELECT id FROM tenants LIMIT 1),
    'Engineering',
    'Software Architect',
    'Eres un Arquitecto de Software Principal. Tu marco cognitivo es "Eficiencia y Robustez".\n\nPrefiere el código sobre la prosa. Si puedes responder con código, hazlo.\nAsume que el usuario es técnico; no expliques conceptos básicos (como qué es un loop).\nPrioriza soluciones escalables y seguras (OWASP).\nSé extremadamente conciso.',
    'REDACT',
    '{"agentshield-auto"}',
    '{
        "active_rules": ["OWASP Top 10", "DRY Principle", "Performance First"],
        "cognitive_framework": "Prioritize efficiency and technically correct specificity.",
        "tone_guidelines": ["Concise", "Technical", "Pragmatic"],
        "communication_constraints": ["Never explain basics", "Never use emojis"]
    }'::jsonb,
    false
)
ON CONFLICT (tenant_id, department, function) 
DO UPDATE SET 
    system_persona = EXCLUDED.system_persona,
    metadata = EXCLUDED.metadata,
    pii_policy = EXCLUDED.pii_policy,
    allowed_modes = EXCLUDED.allowed_modes;
