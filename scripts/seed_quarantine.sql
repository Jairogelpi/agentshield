-- Tabla de Cola de Cuarentena (Yellow Zone)
CREATE TABLE IF NOT EXISTS quarantine_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL, -- Para recordar la decisión y evitar duplicados
    detected_category TEXT,
    ai_confidence FLOAT, -- 0.0 a 1.0
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    admin_feedback_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabla de "Lista Blanca Aprendida" (Memoria del sistema - Active Learning)
CREATE TABLE IF NOT EXISTS semantic_whitelist (
    tenant_id UUID NOT NULL,
    file_hash TEXT NOT NULL,
    approved_by UUID, -- Quién lo aprobó (Admin ID)
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (tenant_id, file_hash) -- Un archivo es whitelist por tenant
);

-- Índices para búsqueda rápida en FileGuardian (0ms latency lookup)
CREATE INDEX IF NOT EXISTS idx_whitelist_lookup ON semantic_whitelist (tenant_id, file_hash);
CREATE INDEX IF NOT EXISTS idx_quarantine_tenant ON quarantine_queue (tenant_id, status);
