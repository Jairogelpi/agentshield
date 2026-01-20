-- ==============================================================================
-- MÓDULO SIEM: Event Bus & Automation
-- ==============================================================================

-- 1. El "Log Central" (Append-Only)
-- Aquí acaban todos los eventos del sistema. Es la fuente de verdad del SOC.
CREATE TABLE IF NOT EXISTS public.system_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    trace_id TEXT, -- Link al chat request
    
    event_type TEXT NOT NULL, -- 'PII_BLOCKED', 'TRUST_DROP', 'BUDGET_CAP'
    severity TEXT CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    
    actor_id UUID, -- Quién causó el evento (User)
    details JSONB DEFAULT '{}', -- Metadatos (ej: "score_before": 80, "score_after": 40)
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Canales de Notificación (Webhooks externos)
CREATE TABLE IF NOT EXISTS public.event_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name TEXT NOT NULL, -- 'Canal Seguridad Slack', 'PagerDuty Critical'
    
    channel_type TEXT CHECK (channel_type IN ('WEBHOOK', 'SLACK', 'TEAMS', 'EMAIL')),
    config JSONB NOT NULL, -- { "url": "https://hooks.slack.com/..." }
    
    filter_events TEXT[], -- ['PII_BLOCKED', 'TRUST_DROP'] (Array de eventos suscritos)
    is_active BOOLEAN DEFAULT TRUE
);

-- 3. Reglas de Automatización (Playbooks)
-- "Si pasa X, ejecuta la acción Y"
CREATE TABLE IF NOT EXISTS public.automation_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name TEXT NOT NULL, -- 'Freeze Wallet on High PII'
    
    trigger_event TEXT NOT NULL, -- 'PII_BLOCKED'
    condition_logic JSONB DEFAULT '{}', -- { "severity": "CRITICAL" }
    
    action_type TEXT NOT NULL, -- 'FREEZE_WALLET', 'DEGRADE_MODEL', 'NOTIFY_ADMIN'
    action_config JSONB DEFAULT '{}', -- { "duration_hours": 24 }
    
    is_active BOOLEAN DEFAULT TRUE
);

-- Índices para búsqueda rápida en tiempo real
CREATE INDEX IF NOT EXISTS idx_events_tenant_type ON public.system_events(tenant_id, event_type);
CREATE INDEX IF NOT EXISTS idx_system_events_created ON public.system_events(created_at);
