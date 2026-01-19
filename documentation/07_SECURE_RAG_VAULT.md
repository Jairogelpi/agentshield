# 🔐 07. Secure RAG Vault (Defense in Depth)

> **"La Cámara Acorazada de Datos Corporativos"**
>
> Cómo AgentShield implementa RAG (Retrieval Augmented Generation) sin que los datos sensibles se filtren jamás, usando una estrategia de defensa en profundidad.

---

## 1. El Problema: "El RAG Ingenuo"
La mayoría de implementaciones de RAG (Chats con PDFs) cometen errores fatales de seguridad:
1.  **Vectorizan PII**: Si subes un contrato con una tarjeta de crédito, el vector "recuerda" ese número.
2.  **Todo es Plano**: Si el CEO sube la nómina, cualquiera que pregunte "¿Cuánto gana el CEO?" obtendrá la respuesta porque el vector es similiar.
3.  **Filtración por Diseño**: La base de datos vectorial no suele respetar los permisos (RBAC) de la aplicación original.

## 2. La Solución: AgentShield Vault Architecture

Implementamos **4 Capas de Seguridad** que actúan como compuertas lógicas.

### Capa 1: Limpieza Pre-Ingesta (Sanitization)
**Ubicación**: `app/services/vault.py` -> `pii_guard.py`
Antes de que un documento toque la base de datos (incluso antes de partirlo en trozos), AgentShield escanea el texto en busca de PII (Emails, Tarjetas, Teléfonos).
*   **Acción**: Reemplaza el dato real por `[REDACTED]`.
*   **Resultado**: El vector generado representa el *concepto* ("El usuario tiene una deuda"), pero no el *dato* ("La deuda es de 500€").

### Capa 2: Clasificación Automática de Riesgo
**Ubicación**: `app/services/vault.py`
Si el motor de PII detecta alta densidad de datos sensibles, el documento se etiqueta automáticamente como `CONFIDENTIAL`, sobrescribiendo la elección del usuario si intentó marcarlo como `PUBLIC`.

### Capa 3: Row Level Security (RLS) - El Cortafuegos SQL
**Ubicación**: PostgreSQL / Supabase
No confiamos en el código Python para filtrar. La seguridad está en el motor de base de datos.
```sql
CREATE POLICY tenant_isolation_docs ON vault_documents
    USING (tenant_id = (current_setting('app.current_tenant')::uuid));
```
*   **Efecto**: Si un hacker logra inyectar SQL, **la base de datos le devuelve 0 filas** porque su sesión no tiene el `tenant_id` correcto. Es seguridad física.

### Capa 4: Búsqueda Semántica con Permisos (RPC)
**Ubicación**: `secure_vault_search` (SQL Function)
La búsqueda cruza tres factores:
1.  **Similitud Semántica**: (El estándar vector search).
2.  **Dept ID**: ¿Eres de RRHH? Entonces ves docs de RRHH. Si eres de Ventas, NO los ves.
3.  **Clasificación**: ¿Eres Admin? Ves `CONFIDENTIAL`. ¿Eres Becario? Solo ves `PUBLIC` e `INTERNAL`.

---

## 3. Flujo de Datos (Data Flow)

1.  **Upload**: Usuario sube `estrategia_2026.pdf` vía OpenWebUI.
2.  **Intercept**: AgentShield `/v1/files` captura el archivo.
3.  **Scrub**: `pii_guard` elimina secretos.
4.  **Tag**: Se marca como `INTERNAL` y propiedad del Depto `MARKETING`.
5.  **Store**: Se guarda en `vault_chunks` (Vectores).
6.  **Query**: Usuario pregunta "¿Cuál es la estrategia?".
7.  **Filter**: PostgreSQL verifica si el usuario es de Marketing.
    *   Si SÍ: Devuelve el chunk.
    *   Si NO: Devuelve vacío (silencio absoluto).

---

## 4. Ventaja Competitiva
Vendes **"RAG Corporativo Seguro"**.
> "AgentShield garantiza matemáticamente que un documento de Recursos Humanos jamás aparecerá en una búsqueda realizada por un empleado de Ventas, y que ninguna Tarjeta de Crédito será vectorizada."

Esto desbloquea clientes de **Banca, Seguros y Gobierno** que no pueden usar soluciones RAG estándar.
