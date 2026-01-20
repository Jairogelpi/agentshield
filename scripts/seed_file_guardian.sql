-- ==============================================================================
-- FILE GUARDIAN: TABLAS Y DATOS INICIALES
-- ==============================================================================

-- 1. Tabla de Políticas Unificadas (Si no existe)
-- Reemplaza la necesidad de tablas fragmentadas.
CREATE TABLE IF NOT EXISTS public.policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name TEXT NOT NULL,
    mode TEXT DEFAULT 'ENFORCE' CHECK (mode IN ('ENFORCE', 'SHADOW')),
    action TEXT NOT NULL, -- 'BLOCK_UPLOAD', 'BLOCK_PROMPT', 'REDACT'
    target_dept_id UUID, -- NULL = Aplica a todos
    target_role TEXT,    -- NULL = Aplica a todos
    rules JSONB DEFAULT '{}', -- Flexibilidad total: { "block_categories": ["INVOICE"] }
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index para búsqueda rápida en el proxy
CREATE INDEX IF NOT EXISTS idx_policies_lookup ON public.policies(tenant_id, action, is_active);

-- 2. Tabla de Eventos de Política (Auditoría centralizada)
CREATE TABLE IF NOT EXISTS public.policy_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    policy_id UUID REFERENCES public.policies(id),
    event_type TEXT NOT NULL, -- 'FILE_UPLOAD_ATTEMPT', 'PROMPT_INJECTION'
    action_taken TEXT NOT NULL, -- 'BLOCKED', 'LOGGED', 'ALLOWED'
    metadata JSONB DEFAULT '{}',
    user_id UUID, -- Opcional, para linkear con user_profiles
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Insertar Política de Ejemplo (Idempotente)
-- Bloquear Facturas para el departamento de Marketing
DO $$
DECLARE
    v_tenant_id UUID;
    v_dept_id UUID;
BEGIN
    -- Obtener un tenant de ejemplo (el primero)
    SELECT id INTO v_tenant_id FROM public.tenants LIMIT 1;
    
    -- Si no hay tenant, salimos
    IF v_tenant_id IS NOT NULL THEN
        -- Crear Dept Marketing Dummy si no existe, o tomar cualquiera
        -- Para el ejemplo intentamos buscar uno, si no, lo dejamos NULL (Aplica a todos)
        SELECT id INTO v_dept_id FROM public.departments WHERE tenant_id = v_tenant_id LIMIT 1;

        -- Insertar Policy FileGuardian
        INSERT INTO public.policies (
            tenant_id, name, mode, action, target_dept_id, rules, priority
        ) 
        SELECT 
            v_tenant_id,
            'Bloqueo de Datos Financieros',
            'ENFORCE',
            'BLOCK_UPLOAD',
            v_dept_id, -- Aplica a este departamento (o NULL si no hay depts)
            '{
                "block_categories": ["INVOICE", "FINANCIAL_REPORT", "PAYSLIP"],
                "allowed_extensions": ["pdf", "docx", "txt"],
                "max_size_mb": 10
            }'::jsonb,
            100
        WHERE NOT EXISTS (
            SELECT 1 FROM public.policies WHERE name = 'Bloqueo de Datos Financieros' AND tenant_id = v_tenant_id
        );
    END IF;
END $$;
