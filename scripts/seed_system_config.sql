-- 1. Crear Tabla de Configuración del Sistema (si no existe)
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Ensure description column exists (Schema Evolution)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='system_config' AND column_name='description') THEN
        ALTER TABLE system_config ADD COLUMN description TEXT;
    END IF;
END $$;

-- 2. Insertar Configuración de Cadenas de Modelos (Model Chains)
INSERT INTO system_config (key, value, description)
VALUES (
    'model_chains',
    '{
        "agentshield-smart": [
            {"provider": "openai", "model": "gpt-4o", "timeout": 20},
            {"provider": "azure", "model": "gpt-4o", "timeout": 20},
            {"provider": "anthropic", "model": "claude-3-opus-20240229", "timeout": 30}
        ],
        "agentshield-fast": [
            {"provider": "openai", "model": "gpt-4o-mini", "timeout": 10},
            {"provider": "anthropic", "model": "claude-3-haiku-20240307", "timeout": 10},
            {"provider": "openai", "model": "gpt-3.5-turbo", "timeout": 10}
        ]
    }'::jsonb,
    'Definición dinámica de rutas de fallback para tiers de IA'
)
ON CONFLICT (key) DO UPDATE 
SET value = EXCLUDED.value, updated_at = NOW();

-- 3. Definir Políticas Dinámicas (Relational Aware)

-- 3.1 Asegurar que la herramienta 'stripe_charge' existe (para la demo)
INSERT INTO tool_definitions (tenant_id, name, description, cost_per_execution, risk_level)
SELECT 
  id as tenant_id, 
  'stripe_charge' as name, 
  'Process payment logic' as description, 
  0.00 as cost_per_execution, 
  'HIGH' as risk_level
FROM tenants
WHERE NOT EXISTS (
    SELECT 1 FROM tool_definitions WHERE name = 'stripe_charge' AND tenant_id = tenants.id
);

-- 3.2 Insertar Política vinculando por tool_id (FK correcta)
-- Bloquear stripe_charge > 500
-- FIX: Usamos JOIN implícito porque tool_policies usa tool_id, no tool_name
INSERT INTO tool_policies (tenant_id, tool_id, action, argument_rules, priority, is_active)
SELECT 
    t.id, 
    td.id, 
    'REQUIRE_APPROVAL', 
    '{"amount": {"gt": 500}}'::jsonb, 
    10, 
    TRUE
FROM tenants t
JOIN tool_definitions td ON td.tenant_id = t.id AND td.name = 'stripe_charge'
WHERE NOT EXISTS (
    -- Evitar duplicados si ya hay una política para esta herramienta
    SELECT 1 FROM tool_policies tp WHERE tp.tool_id = td.id AND tp.tenant_id = t.id
)
LIMIT 1;
