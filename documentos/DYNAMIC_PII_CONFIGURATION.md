# Dynamic PII Configuration System

El sistema de configuración dinámica PII permite a cada tenant/departamento/usuario definir patrones personalizados de datos sensibles, con asistencia de LLM para generar automáticamente expresiones regulares desde lenguaje natural.

## Características Principales

### 1. Jerarquía de Patrones
- **Tenant-level**: Aplica a todos los usuarios del tenant
- **Department-level**: Aplica a usuarios del departamento (override tenant)
- **User-level**: Aplica solo al usuario específico (override department)

### 2. Generación Asistida por LLM
Usa GPT-4 para convertir descripciones en lenguaje natural a patrones regex precisos.

**Ejemplo**:
```
Input: "contraseñas de empleado"
Output: (?i)(employee[_-]?password|emp[_-]?pwd)\s*[:=]\s*[^\s]{6,}
Confidence: 0.94
```

### 3. Detección Universal
- 25+ patrones pre-configurados (passwords, API keys, crypto wallets, etc.)
- Patrones dinámicos ilimitados por tenant
- Detección de evasión (Base64, ROT13, leetspeak)
- Soporte internacional (CURP, DNI, CPF, NHS, Aadhaar)

## API Endpoints

### Generar Patrón con LLM
```http
POST /pii/patterns/generate
Content-Type: application/json

{
  "data_type_description": "códigos de proyecto internos",
  "context": "Formato: PROJ-XXXX-YYYY",
  "language": "es"
}
```

**Respuesta**:
```json
{
  "regex_pattern": "PROJ-[A-Z0-9]{4}-[A-Z0-9]{4}",
  "confidence": 0.94,
  "test_examples": ["PROJ-A1B2-C3D4", "PROJ-1234-5678"],
  "rationale": "Matches project code format with 4-char alphanumeric segments",
  "pattern_type": "CUSTOM_ID"
}
```

### Crear Patrón Personalizado
```http
POST /pii/patterns
Content-Type: application/json

{
  "pattern_name": "Códigos de Proyecto",
  "pattern_type": "PROJECT_CODE",
  "regex_pattern": "PROJ-[A-Z0-9]{4}-[A-Z0-9]{4}",
  "redaction_strategy": "FULL",
  "tenant_id": "uuid-tenant",
  "generated_by_llm": true,
  "confidence_score": 0.94,
  "test_examples": ["PROJ-A1B2-C3D4"]
}
```

### Listar Patrones
```http
GET /pii/patterns?tenant_id=<uuid>&active_only=true
```

### Actualizar Patrón
```http
PUT /pii/patterns/{pattern_id}
Content-Type: application/json

{
  "is_active": false
}
```

### Eliminar Patrón
```http
DELETE /pii/patterns/{pattern_id}
```

### Probar Patrón
```http
POST /pii/patterns/test
Content-Type: application/json

{
  "regex_pattern": "PROJ-[A-Z0-9]{4}-[A-Z0-9]{4}",
  "test_strings": [
    "Mi código es PROJ-A1B2-C3D4",
    "Proyecto normal sin código",
    "PROJ-INVALID-FORMAT"
  ]
}
```

## Arquitectura

### Base de Datos
Tabla: `custom_pii_patterns`
- Jerarquía: tenant_id, department_id, user_id
- Row-Level Security para aislamiento multi-tenant
- Full-text search en nombres de patrones
- Índices optimizados para queries jerárquicas

### Componentes

1. **LLM Pattern Generator** (`llm_pattern_generator.py`)
   - Genera regex desde lenguaje natural
   - Valida patrones generados
   - Proporciona ejemplos de test

2. **API Router** (`pii_config.py`)
   - CRUD completo para patrones
   - Integración con LLM
   - Validación de scope jerárquico

3. **PII Guard** (`pii_guard.py`)
   - Carga dinámica de patrones por tenant/dept/user
   - Resolución jerárquica (user > dept > tenant)
   - Integración en pipeline multi-pass

## Flujo de Uso

### Escenario: Admin Define Patrón Empresarial

1. **Admin escribe descripción**:
   ```
   "códigos de empleado internos con formato EMP-XXXXXXX"
   ```

2. **Sistema genera patrón con LLM**:
   ```javascript
   POST /pii/patterns/generate
   // Respuesta automática con regex optimizado
   ```

3. **Admin revisa y guarda**:
   ```javascript
   POST /pii/patterns
   // Pattern scope: tenant_id (aplica a toda la organización)
   ```

4. **Aplicación automática**:
   - Todos los requests del tenant usan el nuevo patrón
   - Detección en tiempo real
   - Zero configuración adicional

## Estrategias de Redacción

```python
"FULL"    # <PATTERN_TYPE_REDACTED>
"PARTIAL" # <PHONE_LAST_4:1234>
"HINT"    # <USERNAME_HINT:jo***>
```

## Seguridad

- **Row-Level Security**: Usuarios solo ven patrones de su scope
- **Validación**: Regex probados antes de guardar
- **Audit Trail**: created_by, created_at, updated_at
- **Confidence Scoring**: LLM proporciona score 0-1

## Métricas en HUD

Cuando se detectan patrones dinámicos:
```
PII Risk: €450K 🥇 GOLD Conf: 100% 🚨 Rec: 3
Dynamic Patterns: 2 matched
```

## Migración

```sql
-- ./supabase/migrations/20260128_custom_pii_patterns.sql
-- Ejecutar una sola vez
```

## Ejemplos de Patrones

### Contraseñas de Empleado
```
Pattern: (?i)(employee[_-]?password|emp[_-]?pwd)\s*[:=]\s*[^\s]{6,}
Type: PASSWORD
Strategy: FULL
```

### Códigos de Cliente
```
Pattern: CLI-\d{6}-[A-Z]{2}
Type: CLIENT_CODE
Strategy: PARTIAL (preserva últimos 2 caracteres)
```

### Direcciones Internas
```
Pattern: \d+\s+[A-Za-z\s]+,\s+Floor\s+\d+,\s+Building\s+[A-Z]
Type: INTERNAL_ADDRESS
Strategy: PARTIAL (preserva building)
```

## Mejores Prácticas

1. **Usa LLM**: Deja que GPT-4 genere los patrones iniciales
2. **Prueba primero**: Usa `/patterns/test` antes de guardar
3. **Scope adecuado**: Tenant para reglas globales, User para excepciones
4. **Documenta**: Usa nombres descriptivos y agrega ejemplos
5. **Monitorea**: Revisa métricas de detección en HUD

## Troubleshooting

### Patrón no detecta
- Verifica scope (tenant/dept/user)
- Prueba con `/patterns/test`
- Revisa `is_active = true`

### Falsos positivos
- Ajusta regex para ser más específico
- Usa anchors (`\b` para word boundaries)
- Reduce confidence threshold

### Performance
- Evita regex ultra-complejos
- Usa anchors para early exit
- Considera consolidar patrones similares
