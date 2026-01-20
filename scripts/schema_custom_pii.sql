-- ==============================================================================
-- MÓDULO CUSTOM PII: Reglas de Protección Definidas por el Usuario
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.custom_pii_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL, -- Cada tenant tiene sus propias reglas
    
    name TEXT NOT NULL, -- Ej: "Project Codes"
    description TEXT, -- El prompt original del usuario: "Protege códigos tipo PRJ-1234"
    
    regex_pattern TEXT NOT NULL, -- El regex generado por el Copilot: r'PRJ-\d{4}'
    risk_score INTEGER DEFAULT 50, -- 0-100, qué tan sensible es esto
    
    action TEXT DEFAULT 'REDACT', -- 'BLOCK', 'REDACT', 'ALERT'
    is_active BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para búsqueda rápida en tiempo real (cache-miss fallback)
CREATE INDEX IF NOT EXISTS idx_custom_pii_tenant ON public.custom_pii_rules(tenant_id) WHERE is_active = TRUE;
