-- ==============================================================================
-- MÓDULO FACTURACIÓN: Auditoría Financiera de Doble Entrada
-- ==============================================================================

-- 1. Enriquecer Recibos con datos de Arbitraje y Ahorro (Gross vs Net)
ALTER TABLE public.receipts
ADD COLUMN IF NOT EXISTS cost_real numeric(10, 6) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS cost_gross numeric(10, 6) DEFAULT 0.0, -- Coste teórico baseline
ADD COLUMN IF NOT EXISTS savings_usd numeric(10, 6) DEFAULT 0.0, -- Ahorro calculado
ADD COLUMN IF NOT EXISTS model_requested text,                   -- Lo que pidió el usuario
ADD COLUMN IF NOT EXISTS model_effective text,                   -- Lo que se ejecutó
ADD COLUMN IF NOT EXISTS co2_gross_g numeric(10, 4) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS co2_actual_g numeric(10, 4) DEFAULT 0.0;

-- 2. Índices para reportes mensuales rápidos
CREATE INDEX IF NOT EXISTS idx_receipts_billing ON public.receipts(tenant_id, cost_center_id, created_at);
