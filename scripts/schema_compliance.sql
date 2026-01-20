-- ==============================================================================
-- MÓDULO COMPLIANCE: DPO & Certification
-- ==============================================================================

-- 1. Registro de Acciones de Compliance (Audit Log)
CREATE TABLE IF NOT EXISTS public.compliance_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    actor_id UUID REFERENCES auth.users(id), -- Quién ejecutó la acción (DPO/Admin)
    target_user_id UUID, -- El usuario afectado (si aplica)
    
    action_type TEXT NOT NULL, -- 'RIGHT_TO_FORGET', 'DATA_EXPORT', 'SYSTEM_AUDIT'
    status TEXT DEFAULT 'COMPLETED',
    
    details JSONB DEFAULT '{}', -- Qué se borró, qué se conservó
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Certificados Emitidos (El PDF que descarga el auditor)
CREATE TABLE IF NOT EXISTS public.compliance_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    action_id UUID REFERENCES public.compliance_actions(id),
    
    certificate_hash TEXT NOT NULL, -- SHA256 del PDF para inmutabilidad
    storage_path TEXT NOT NULL, -- Ruta en S3/Supabase Storage
    
    valid_until TIMESTAMPTZ, -- Para certificaciones periódicas
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Índices por Tenant para performance multi-tenant
CREATE INDEX IF NOT EXISTS idx_compliance_tenant ON public.compliance_actions(tenant_id);
