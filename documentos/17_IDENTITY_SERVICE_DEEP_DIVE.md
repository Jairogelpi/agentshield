# 🪪 El Pasaporte Digital: Identity Service (Deep Dive)

La identidad es el cimiento de la seguridad Zero Trust en AgentShield. El `IdentityService` es el responsable de transformar un simple Token JWT en un **Contexto de Identidad Enriquecido** (`VerifiedIdentity`) que el resto del sistema utiliza para aplicar políticas.

---

## 🎯 El Problema: El Token "Mudo"
Un JWT estándar suele contener solo un ID de usuario. Para que AgentShield tome decisiones inteligentes (ej. "¿Tiene este usuario presupuesto para el departamento de IT?"), necesitamos saber mucho más en cada milisegundo.

El `IdentityService` resuelve esto mediante el **Aislamiento de Tenencia (Multi-tenancy)** y el **Enriquecimiento Dinámico**.

---

## 💎 Características "God Tier"

### 1. El Sobre de Identidad Virtual (`VerifiedIdentity`)
No pasamos datos sueltos por el código. Creamos un objeto que contiene:
- **Tenant ID:** La empresa a la que pertenece el usuario (aislamiento total de datos).
- **Dept ID:** El centro de coste departamental para el control de presupuestos.
- **Role:** El nivel de privilegio (Admin, Manager, User).

### 2. Resolución Híbrida de Identidad
Para mantener una latencia ultra-baja (<ms), el sistema utiliza tres niveles de resolución:
1.  **JWT Metadata:** Recuperación instantánea de datos básicos del token.
2.  **Redis Cache:** Si el usuario está activo, su perfil completo vive en memoria RAM (Sincronizado cada 5 min).
3.  **Supabase Fallback:** Si no hay caché, realizamos una consulta thread-safe a la base de datos con un **timeout de seguridad de 2.0s**.

### 3. Resiliencia y Fallbacks Inteligentes
Si la base de datos está lenta o bajo carga, el servicio intenta deducir la identidad del usuario por defecto usando la información del token y el primer departamento disponible del Tenant, asegurando que el Proxy nunca se detenga.

---

## 🛠️ Cómo funciona bajo el capó (`app/services/identity.py`)

La función `verify_identity_envelope` es la encargada de la magia:

```python
async def verify_identity_envelope(authorization: str) -> VerifiedIdentity:
    # 1. Decodificar Firma Digital
    payload = jwt.decode(token, SECRET_KEY)
    
    # 2. Búsqueda en Memoria (Redis)
    cached_profile = await redis_client.get(f"identity:{user_id}")
    if cached_profile: return VerifiedIdentity(**json.loads(cached_profile))

    # 3. Resolución y Enriquecimiento
    profile = await resolve_full_profile_from_db(user_id)
    return VerifiedIdentity(profile)
```

---

## 📈 Valor para el Negocio
- **Multi-tenancy Nativo:** Garantiza que los datos de la Empresa A nunca sean visibles por la Empresa B.
- **Auditoría Forense Precisa:** Cada log en AgentShield está vinculado a una identidad real, no solo a un ID anónimo.
- **Velocidad Extrema:** La arquitectura de caché asegura que la verificación de identidad no degrade la experiencia de chat.

**Identity Service es el ancla que vincula cada token de IA con una persona y una política real.**
