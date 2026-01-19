-- Semilla para herramientas multimodales
-- Ejecutar en Supabase SQL Editor

INSERT INTO tool_definitions (tenant_id, name, description, cost_per_execution, risk_level)
SELECT 
  id as tenant_id, 
  'web_search' as name, 
  'Busca información en tiempo real en Google/Bing' as description, 
  0.01 as cost_per_execution, 
  'LOW' as risk_level
FROM tenants
WHERE NOT EXISTS (
    SELECT 1 FROM tool_definitions WHERE name = 'web_search' AND tenant_id = tenants.id
);

INSERT INTO tool_definitions (tenant_id, name, description, cost_per_execution, risk_level)
SELECT 
  id as tenant_id, 
  'python_interpreter' as name, 
  'Ejecuta código Python para análisis de datos y gráficas' as description, 
  0.05 as cost_per_execution, 
  'HIGH' as risk_level
FROM tenants
WHERE NOT EXISTS (
    SELECT 1 FROM tool_definitions WHERE name = 'python_interpreter' AND tenant_id = tenants.id
);

INSERT INTO tool_definitions (tenant_id, name, description, cost_per_execution, risk_level)
SELECT 
  id as tenant_id, 
  'image_generation' as name, 
  'Crea imágenes artísticas o realistas (DALL-E)' as description, 
  0.04 as cost_per_execution, 
  'MEDIUM' as risk_level
FROM tenants
WHERE NOT EXISTS (
    SELECT 1 FROM tool_definitions WHERE name = 'image_generation' AND tenant_id = tenants.id
);

-- Precios Dinámicos (Model Prices)
-- La app usa estos valores en lugar de hardcoded floats
-- Fallback mechanism: Si LiteLLM no tiene el precio, mira esta tabla.

CREATE TABLE IF NOT EXISTS model_prices (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    model text NOT NULL,
    price_in numeric DEFAULT 0,
    price_out numeric DEFAULT 0,
    is_active boolean DEFAULT true
    -- UNIQUE(model) -- Removed inline to handle existing tables gracefully
);

-- Ensure Unique Constraint Exists (Idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'model_prices_model_key') THEN
        ALTER TABLE model_prices ADD CONSTRAINT model_prices_model_key UNIQUE (model);
    END IF;
END $$;

-- Seed de precios base para multimodalidad
-- NOW INCLUDING PROVIDER (REQUIRED BY SCHEMA)
INSERT INTO model_prices (provider, model, price_in, price_out) VALUES
('openai', 'dall-e-3-standard', 0.040, 0.0),
('openai', 'dall-e-3-hd', 0.080, 0.0),
('openai', 'dall-e-2', 0.020, 0.0),
('agentshield', 'vision-image-avg', 0.003825, 0.0)
ON CONFLICT (model) DO UPDATE SET 
price_in = EXCLUDED.price_in,
price_out = EXCLUDED.price_out;
