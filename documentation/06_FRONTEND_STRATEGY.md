# 06. Estrategia Frontend: AgentShield OS (Dual Interface)

Para el usuario final, AgentShield no es una API, es un producto unificado. Nuestra estrategia de frontend es dual: separamos la experiencia de "Consumo" (Chat) de la experiencia de "Control" (Dashboard), pero las conectamos fluida.

## 1. La Cara del Empleado: "El Chat Inteligente" (OpenWebUI)
**Objetivo**: Eliminar fricción. Que parezca ChatGPT, pero seguro.

Esta interfaz es una instancia personalizada de **OpenWebUI** que consume nuestra API.

### Características Clave (Configuración)
-   **Sin Configuración de Usuario**: El empleado entra con SSO. No gestiona API Keys. Nuestra API inyecta su identidad (Identity Envelope) invisiblemente.
-   **Alias de Modelos**: El usuario no ve "gpt-4-turbo" o "claude-3-opus". Ve alias comerciales definidos por la empresa:
    -   `AgentShield Auto` (Arbitraje automático)
    -   `AgentShield Eco` (Modelos baratos/locales)
    -   `AgentShield Secure` (Modelos sin retención de datos)
-   **HUD en Tiempo Real**: Al final de cada respuesta, el proxy inyecta metadatos educativos:
    -   Trust Score
    -   Dinero Ahorrado
    -   Huella de CO2

## 2. La Cara del Admin/Jefe: "El Tablero de Control" (Next.js Dashboard)
**Objetivo**: Evidencia, Auditoría y Finanzas.

Este es el desarrollo propietario (carpeta `agentshield_frontend`). Es donde se visualiza el valor que genera la plataforma.

### A. Visualización Financiera ("Money View")
**Componente**: `src/components/charts/spending-chart.tsx`
-   Muestra gráficos en tiempo real del consumo.
-   **Diferenciador**: Resalta el "Gasto Evitado" (Ahorro) vs el "Gasto Real", demostrando el ROI del sistema de arbitraje.

### B. Auditoría Forense ("Legal View")
**Ruta**: `src/app/(dashboard)/dashboard/receipts/page.tsx`
-   Explorador de "Recibos Forenses".
-   Permite a los auditores (CFO/Legal) inspeccionar cada transacción.
-   **Verificación**: Botón para validar la firma criptográfica (RSA) y la integridad de la cadena de hashes contra la clave pública.

### C. Economía de Conocimiento ("Futuristic View")
**Componente**: `src/components/3d/market-scene.tsx`
-   Visualización 3D (Three.js/Fiber) del flujo de datos en tiempo real.
-   Representa cómo los diferentes departamentos "comercian" con conocimiento (Royalties), haciendo tangible la economía interna de datos.

### D. Sostenibilidad ("ESG View")
**Ruta**: `src/app/(dashboard)/dashboard/sustainability/page.tsx`
-   Panel de impacto ambiental.
-   Visualiza los gramos de CO2 ahorrados gracias al uso de modelos optimizados (menor cómputo) o energía verde, alimentado por el backend (`carbon.py`).

## Flujo de Usuario Unificado
1.  Empleado usa el Chat (OpenWebUI) -> Genera logs y recibos.
2.  Empleado ve botón "📊 Mi Panel de Impacto".
3.  Clic redirige al Dashboard (Next.js) con SSO.
4.  Empleado ve sus propios recibos firmados y su contribución al ahorro de la empresa.
