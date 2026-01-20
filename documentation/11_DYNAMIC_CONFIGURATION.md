# 11. Configuración Dinámica ("No Hardcoding")

> **Estado**: ✅ Implementado
> **Versión**: 1.0 (Zero-Code Config)
> **Motivación**: Convertir AgentShield en un SaaS multi-tenant donde ningún cambio de lógica de negocio requiera redespliegue de código.

## 1. El Manifiesto "Datos sobre Código"
Hemos refactorizado los tres pilares del sistema para que lean su "cerebro" desde PostgreSQL y Redis, no desde constantes en Python.

### A. Gateway de Modelos (`llm_gateway.py`)
**Antes**: Diccionario `MODEL_CHAINS = {...}` hardcodeado.
**Ahora**:
1.  Busca la key `model_chains` en Redis.
2.  Si no está, consulta la tabla `system_config` (Key: `model_chains`) en Supabase.
3.  Solo usa hardcode como fallback de emergencia absoluta.

**Cómo Cambiar Modelos**:
```sql
UPDATE system_config SET value = '{
  "agentshield-smart": [{"provider": "azure", "model": "gpt-4-turbo", "timeout": 25}]
}' WHERE key = 'model_chains';
```

### B. Gobernador de Herramientas (`tool_governor.py`)
**Antes**: `if tool_name == "transfer_funds" and amount > 500: ...`
**Ahora**: Motor de reglas agnóstico que lee `tool_policies`.

**Estructura de Regla Dinámica**:
```json
{
  "tool_name": "stripe_charge",
  "action": "REQUIRE_APPROVAL",
  "argument_rules": {
    "amount": { "gt": 500 },
    "currency": "USD"
  }
}
```

### C. Oráculo Financiero (`market_oracle.py`)
**Antes**: Pesos `0.7/0.3` y URLs fijas.
**Ahora**: Variables de entorno para calibración del mercado (" knobs").
*   `ORACLE_WEIGHT_FAST`: Sensibilidad a cambios rápidos.
*   `ORACLE_VOLATILITY_BUFFER`: Margen de seguridad sobre el precio FX.

---

## 2. Guía de Administración

### Sembrar la Configuración Inicial
Para activar este sistema, ejecuta el script SQL maestro:
`scripts/seed_system_config.sql`

Este script crea:
1.  La tabla `system_config`.
2.  La configuración JSON default para `model_chains`.
3.  La tabla `tool_policies` y una regla de ejemplo.

### Cómo inyectar nuevas reglas (Sin SQL)
(Próximamente en Dashboard) -> Por ahora via Supabase SQL Editor o `POST /v1/admin/config`.

---

## 3. Seguridad y Rendimiento
*   **Caché en Redis**: La configuración se cachea por 5 minutos (`setex 300`) para evitar latencia de DB en cada petición de chat.
*   **Fail-Open/Fail-Close**:
    *   Si Gateway falla al leer config -> Usa Default (Fail-Open para disponibilidad).
    *   Si Policies falla al leer config -> Bloquea Herramienta (Fail-Close para seguridad).
