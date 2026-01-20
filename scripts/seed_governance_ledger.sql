-- ==================================================================================
-- 1. MOTOR DE RIESGO Y CONFIANZA (Risk Engine)
-- ==================================================================================
-- Perfiles de usuario con reputación
ALTER TABLE public.user_profiles 
ADD COLUMN IF NOT EXISTS trust_score INTEGER DEFAULT 100 CHECK (trust_score BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS risk_tier TEXT DEFAULT 'LOW' CHECK (risk_tier IN ('LOW', 'MEDIUM', 'HIGH'));

-- Ledger de eventos de reputación
CREATE TABLE IF NOT EXISTS public.reputation_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    change_amount INT NOT NULL, -- Ej: -10 (Fuga PII), +1 (Feedback útil)
    reason TEXT NOT NULL,
    new_score INT NOT NULL, -- El score después del cambio
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================================================================================
-- 2. ACTIVOS DE CONOCIMIENTO (Sovereign Knowledge Assets)
-- ==================================================================================
-- Define el precio y licencia de cada documento o colección RAG
CREATE TABLE IF NOT EXISTS public.knowledge_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    owner_dept_id UUID NOT NULL,
    name TEXT NOT NULL,
    base_price_per_query NUMERIC(10, 4) DEFAULT 0.00,
    license_type TEXT DEFAULT 'FULL' CHECK (license_type IN ('FULL', 'SUMMARY', 'CITATION')),
    audience_rules JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================================================================================
-- 3. LIBRO MAYOR DE LIQUIDACIÓN (Settlement Ledger)
-- ==================================================================================
-- Transferencias internas entre carteras (Wallets)
CREATE TABLE IF NOT EXISTS public.internal_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    
    sender_wallet_id UUID NOT NULL, -- Quien preguntó
    receiver_wallet_id UUID NOT NULL, -- Quien proveyó el dato
    amount NUMERIC(10, 6) NOT NULL,
    
    asset_id UUID REFERENCES public.knowledge_assets(id),
    status TEXT DEFAULT 'SETTLED',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==================================================================================
-- 4. FORENSE (Forensic Proofs)
-- ==================================================================================
-- Sustitución o extensión de forensic_receipts para incluir Decision Graph
CREATE TABLE IF NOT EXISTS public.forensic_receipts_v2 (
    trace_id TEXT PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_email TEXT NOT NULL,
    
    -- Hashes de Estado (Time-Travel)
    policy_hash TEXT NOT NULL, -- Hash SHA256 de las reglas activas
    decision_graph_log JSONB, -- { "risk": "PASS", "budget": "PASS", "intent": "CODING" }
    
    -- Firma Criptográfica
    digital_signature TEXT NOT NULL, -- RSA Signature
    created_at TIMESTAMPTZ DEFAULT NOW()
);
