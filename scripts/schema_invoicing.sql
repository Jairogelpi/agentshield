-- ==============================================================================
-- MÓDULO FACTURACIÓN: Campos de Auditoría Financiera
-- ==============================================================================

-- 1. Enriquecer Recibos con datos de Arbitraje y Ahorro
-- Esto permite calcular el ROI exacto: "Te ahorré $0.50 en esta query".
ALTER TABLE public.receipts
ADD COLUMN IF NOT EXISTS cost_real numeric(10, 6) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS cost_gross numeric(10, 6) DEFAULT 0.0, -- Coste teórico del modelo solicitado
ADD COLUMN IF NOT EXISTS savings_usd numeric(10, 6) DEFAULT 0.0, -- Gross - Real
ADD COLUMN IF NOT EXISTS model_requested text,                   -- Lo que pidió el usuario
ADD COLUMN IF NOT EXISTS model_effective text;                   -- Lo que ejecutamos realmente

-- 2. Índices para reportes mensuales rápidos (Evitar Full Table Scans)
CREATE INDEX IF NOT EXISTS idx_receipts_billing ON public.receipts(tenant_id, cost_center_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ledger_seller ON public.ledger_settlements(seller_wallet_id, created_at);
-- CREATE INDEX IF NOT EXISTS idx_carbon_ledger_dept ON public.carbon_ledger(department_id, created_at);
