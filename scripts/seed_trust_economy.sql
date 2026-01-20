-- 1. Actualizar Perfiles de Usuario (Trust Score & Risk Tier)
-- Idempotent alteration
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_profiles' AND column_name='trust_score') THEN
        ALTER TABLE user_profiles ADD COLUMN trust_score INT DEFAULT 100;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='user_profiles' AND column_name='risk_tier') THEN
        ALTER TABLE user_profiles ADD COLUMN risk_tier TEXT DEFAULT 'LOW';
    END IF;
END $$;

-- 2. Ledger de Reputación (Historial de Comportamiento)
CREATE TABLE IF NOT EXISTS reputation_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id),
    change_amount INT NOT NULL, -- Ej: -5 (Bloqueo), +1 (Buen uso)
    reason TEXT NOT NULL,       -- Ej: "Attempted PII Exfiltration", "Approved High-Value Action"
    new_score INT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Ledger Interno (Economía del Conocimiento - Royalties)
CREATE TABLE IF NOT EXISTS internal_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    
    trace_id TEXT, -- Link al chat que generó el gasto
    
    from_wallet_id UUID, -- Quien consume (Buyer)
    to_wallet_id UUID,   -- Quien proveyó el conocimiento (Seller)
    
    amount NUMERIC(15, 6) NOT NULL, -- Valor en USD o Créditos (increased precision)
    concept TEXT, -- 'KNOWLEDGE_ROYALTY', 'MODEL_USAGE_FEE'
    
    asset_id UUID, -- Link al documento del Vault que generó el royalty
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Índices para rendimiento
CREATE INDEX IF NOT EXISTS idx_reputation_user ON reputation_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_internal_ledger_seller ON internal_ledger(to_wallet_id);

-- 5. Función de Redención (Trust Healer) - Para llamar desde Worker o Cron
CREATE OR REPLACE FUNCTION heal_trust_scores()
RETURNS void AS $$
BEGIN
    UPDATE user_profiles 
    SET trust_score = LEAST(100, trust_score + 1) 
    WHERE user_id NOT IN (
        SELECT user_id FROM reputation_ledger 
        WHERE created_at > NOW() - INTERVAL '24 hours' 
        AND change_amount < 0
    );
END;
$$ LANGUAGE plpgsql;

-- 5. Función de Redención (Trust Healer) - Para llamar desde Worker o Cron
CREATE OR REPLACE FUNCTION heal_trust_scores()
RETURNS void AS $$
BEGIN
    UPDATE user_profiles 
    SET trust_score = LEAST(100, trust_score + 1) 
    WHERE user_id NOT IN (
        SELECT user_id FROM reputation_ledger 
        WHERE created_at > NOW() - INTERVAL '24 hours' 
        AND change_amount < 0
    );
END;
$$ LANGUAGE plpgsql;
