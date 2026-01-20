-- ==================================================================================
-- TRUST ENGINE: BEHAVIORAL GOVERNANCE SCHEMA
-- ==================================================================================

-- Estado actual del usuario (Sincronizado desde Redis)
ALTER TABLE public.user_profiles 
ADD COLUMN IF NOT EXISTS trust_score INTEGER DEFAULT 100,
ADD COLUMN IF NOT EXISTS risk_tier TEXT DEFAULT 'LOW'; -- 'LOW' (>=70), 'MEDIUM' (30-69), 'HIGH' (<30)

-- Historial Inmutable (La "Caja Negra" para Compliance)
CREATE TABLE IF NOT EXISTS public.trust_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL, -- Link a auth.users
    
    event_type TEXT NOT NULL, -- 'PII_VIOLATION', 'PROMPT_INJECTION', 'DAILY_HEAL', 'POLICY_HIT'
    change_amount INTEGER NOT NULL, -- Ej: -10, +1
    new_score INTEGER NOT NULL, -- El score resultante en ese momento
    reason TEXT,
    metadata JSONB DEFAULT '{}',
    
    trace_id TEXT, -- Link al chat específico para Replay Forense
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para reportes rápidos de "Usuarios más arriesgados"
CREATE INDEX IF NOT EXISTS idx_trust_events_user ON public.trust_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trust_events_tenant ON public.trust_events(tenant_id);
