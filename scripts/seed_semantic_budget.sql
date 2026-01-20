-- ==============================================================================
-- MÓDULO SEMANTIC BUDGETING & TIME-TRAVEL FORENSICS
-- ==============================================================================

-- 1. Catálogo Dinámico de Intenciones (El usuario puede añadir 'BioTech' o 'Gaming' mañana)
CREATE TABLE IF NOT EXISTS public.intent_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id),
    name text NOT NULL, -- 'CODING', 'LEGAL', 'CREATIVE', 'FINANCE'
    description text,   -- Prompt para el clasificador: "Queries related to python, rust..."
    created_at timestamp with time zone DEFAULT now(),
    UNIQUE(tenant_id, name)
);

-- 2. Matriz de Presupuesto Semántico (CFO Rules)
CREATE TABLE IF NOT EXISTS public.semantic_budgets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    department_id uuid REFERENCES public.departments(id), -- Si es NULL, aplica a toda la empresa
    intent_id uuid NOT NULL REFERENCES public.intent_definitions(id),
    
    -- Configuración Financiera
    monthly_limit numeric(10, 2) DEFAULT -1, -- -1 = Ilimitado
    
    -- Política de Desviación (Qué pasa si no es mi área)
    -- 'ALLOW': Permitir normal
    -- 'BLOCK': Bloquear
    -- 'PENALTY': Cobrar extra (Surcharge)
    -- 'APPROVAL': Requiere aprobación humana
    out_of_scope_action text DEFAULT 'ALLOW', 
    
    penalty_multiplier numeric(5, 2) DEFAULT 1.0, -- Ej: 2.0 = Cobrar doble si Marketing usa Código
    
    is_active boolean DEFAULT true,
    UNIQUE(department_id, intent_id)
);

-- 3. Snapshots de Configuración (Para Time-Travel Forense)
-- Guardamos el hash y el contenido real de la configuración en ese momento
CREATE TABLE IF NOT EXISTS public.config_snapshots (
    hash text PRIMARY KEY, -- SHA256 del JSON de configuración
    tenant_id uuid NOT NULL,
    snapshot_type text, -- 'POLICY', 'MODEL', 'ROUTING'
    content jsonb NOT NULL, -- La regla exacta como estaba ese día
    created_at timestamp with time zone DEFAULT now()
);

-- Índices para búsqueda rápida
CREATE INDEX IF NOT EXISTS idx_snapshots_tenant ON config_snapshots(tenant_id);
