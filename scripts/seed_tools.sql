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
