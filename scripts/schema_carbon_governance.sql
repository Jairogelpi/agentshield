-- ==============================================================================
-- MÓDULO GREEN AI: Carbon Ledger & Budgets
-- ==============================================================================

-- 1. Contabilidad de Carbono (Auditoría ESG)
CREATE TABLE IF NOT EXISTS public.carbon_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    department_id UUID,
    user_id UUID,
    
    trace_id TEXT NOT NULL, -- Link al recibo del chat
    
    model_used TEXT NOT NULL,
    region TEXT DEFAULT 'global',
    
    grams_co2 NUMERIC(10, 4) NOT NULL, -- Emisión real
    co2_avoided NUMERIC(10, 4) DEFAULT 0.0, -- Ahorrado por Green Routing
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Presupuestos de Carbono en Departamentos
-- Ahora el CFO puede limitar no solo dinero, sino contaminación.
ALTER TABLE public.departments
ADD COLUMN IF NOT EXISTS co2_monthly_limit_grams NUMERIC(10, 2) DEFAULT 5000.00, -- 5kg por defecto
ADD COLUMN IF NOT EXISTS current_co2_spend_grams NUMERIC(10, 2) DEFAULT 0.00;

-- Índices para reportes rápidos
CREATE INDEX IF NOT EXISTS idx_carbon_ledger_dept ON public.carbon_ledger(department_id);
CREATE INDEX IF NOT EXISTS idx_carbon_ledger_tenant ON public.carbon_ledger(tenant_id);
