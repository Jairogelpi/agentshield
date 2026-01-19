-- ==============================================================================
-- AGENTSHIELD: ZERO TRUST & WATERFALL BUDGETING SCHEMA
-- ==============================================================================

-- 1. WALLETS HIERARCHY
-- Stores balances for Tenants (Company), Departments (Cost Centers), and Users.
CREATE TABLE IF NOT EXISTS wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    department_id UUID, -- Null if type='tenant'
    user_id UUID,       -- Null if type='tenant' or type='dept'
    
    type TEXT NOT NULL CHECK (type IN ('tenant', 'dept', 'user')),
    balance DECIMAL(20, 4) DEFAULT 0.0000,
    currency TEXT DEFAULT 'USD',
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints to ensure data integrity
    CONSTRAINT uniq_tenant_wallet UNIQUE NULLS NOT DISTINCT (tenant_id, type) WHERE (type = 'tenant'),
    CONSTRAINT uniq_dept_wallet UNIQUE NULLS NOT DISTINCT (department_id, type) WHERE (type = 'dept'),
    CONSTRAINT uniq_user_wallet UNIQUE NULLS NOT DISTINCT (user_id, type) WHERE (type = 'user')
);

-- Index for fast lookup during the "Waterfall Check"
CREATE INDEX idx_wallets_lookup ON wallets(tenant_id, department_id, user_id);

-- 2. WALLET TRANSACTIONS (AUDIT TRAIL / LEDGER)
-- Immutable ledger of every credit/debit.
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id UUID NOT NULL REFERENCES wallets(id),
    
    amount DECIMAL(20, 4) NOT NULL, -- Negative for spend, Positive for top-up
    balance_after DECIMAL(20, 4) NOT NULL,
    
    transaction_type TEXT NOT NULL, -- 'spend', 'topup', 'refund', 'adjustment'
    reference_id TEXT, -- e.g. Request ID, Stripe Payment ID
    description TEXT,
    metadata JSONB DEFAULT '{}'::JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_wallet_tx_wallet_id ON wallet_transactions(wallet_id);

-- 3. DIGITAL NOTARY (FORENSIC RECEIPTS)
-- Criptograf√≠a Asim√©trica + Encadenamiento de Hashes
CREATE TABLE IF NOT EXISTS receipts (
    id UUID PRIMARY KEY, -- Generado en Python
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    
    -- El contenido inmutable (Evidence Payload)
    content_json JSONB NOT NULL,
    
    -- La Criptograf√≠a
    signature TEXT NOT NULL, -- Firma RSA Base64
    hash TEXT NOT NULL,      -- Hash SHA256 de este registro (Current Hash)
    
    -- Metadatos para b√∫squedas
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- √çndice para verificar la cadena r√°pidamente (Chain Continuity Check)
CREATE INDEX idx_receipts_chain ON receipts(tenant_id, created_at DESC);


-- 4. TRIGGERS
-- Automatically update 'updated_at'
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_wallets_modtime
    BEFORE UPDATE ON wallets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 5. RLS POLICIES (Example for Supabase)
ALTER TABLE wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;

-- Tenants can view their own hierarchy wallets
CREATE POLICY "Tenants view own wallets" ON wallets
    FOR SELECT
    USING (auth.uid() = user_id OR EXISTS (
        SELECT 1 FROM tenants WHERE id = wallets.tenant_id AND owner_id = auth.uid()
    ));

-- Tenants can view their own receipts (Evidence)
CREATE POLICY "Tenants view own receipts" ON receipts
    FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM tenants WHERE id = receipts.tenant_id AND owner_id = auth.uid()
    ));

-- Only System Service (Service Role) can update balances directly
-- (Or implemented via Database Functions / Stored Procedures)

-- 6. DYNAMIC POLICIES (Shadow Mode Engine)
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,         -- Ej: 'Bloquear CÛdigo Fuera de IT'
    description TEXT,
    
    -- La LÛgica (Declarativa)
    target_dept TEXT,           -- 'Marketing', '*'
    target_role TEXT,           -- 'intern', '*'
    condition_json JSONB,       -- { 'intent': 'coding', 'cost_gt': 5 }
    
    -- La AcciÛn
    action TEXT NOT NULL,       -- 'BLOCK', 'REDACT', 'DOWNGRADE', 'FLAG'
    
    -- EL INTERRUPTOR M¡GICO
    mode TEXT DEFAULT 'SHADOW', -- 'ENFORCE' (Activo) o 'SHADOW' (Silencioso)
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_policies_tenant ON policies(tenant_id);

-- ==============================================================================
-- 7. THE NEURAL HIVE (Corporate Vector Memory)
-- ==============================================================================

-- Habilita la extensiÛn vectorial (si Supabase la tiene disponible)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS hive_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_email TEXT, -- El 'Autor' de la soluciÛn (para Royalties/Badge)
    
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    
    -- Embeddings (OpenAI text-embedding-3-small = 1536 dim)
    embedding vector(1536),
    
    upvotes INT DEFAULT 1,
    verified_by_human BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Metadata adicional (modelo usado, coste ahorrado, etc)
    metadata JSONB DEFAULT '{}'::JSONB
);

-- Index for IVFFlat (Approximate Nearest Neighbor) - Opcional para performance
-- CREATE INDEX ON hive_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Busqueda Semantica (RPC para llamarla desde Python)
CREATE OR REPLACE FUNCTION match_hive_interactions (
  query_embedding vector(1536),
  match_threshold float,
  match_count int,
  filter_tenant uuid
)
RETURNS TABLE (
  id uuid,
  response text,
  user_email text,
  similarity float
)
LANGUAGE plpgsql
AS c:\Users\jairo\Desktop\agentshield
BEGIN
  RETURN QUERY
  SELECT
    hive_memory.id,
    hive_memory.response,
    hive_memory.user_email,
    1 - (hive_memory.embedding <=> query_embedding) AS similarity
  FROM hive_memory
  WHERE 1 - (hive_memory.embedding <=> query_embedding) > match_threshold
  AND hive_memory.tenant_id = filter_tenant
  ORDER BY hive_memory.embedding <=> query_embedding
  LIMIT match_count;
END;
c:\Users\jairo\Desktop\agentshield;
