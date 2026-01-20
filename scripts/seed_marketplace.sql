-- ==============================================================================
-- MÓDULO MARKETPLACE: Sovereign Knowledge Exchange
-- ==============================================================================

-- 1. Colecciones de Conocimiento (El Producto)
CREATE TABLE IF NOT EXISTS public.knowledge_collections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id),
    owner_dept_id uuid REFERENCES public.departments(id),
    
    name text NOT NULL,
    description text,
    is_public_to_tenant boolean DEFAULT false, -- Si es false, requiere suscripción explícita
    
    created_at timestamp with time zone DEFAULT now()
);

-- Vincular Documentos a Colecciones
-- Idempotent column addition
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='vault_documents' AND column_name='collection_id') THEN
        ALTER TABLE public.vault_documents 
        ADD COLUMN collection_id uuid REFERENCES public.knowledge_collections(id);
    END IF;
END $$;

-- 2. Reglas de Acceso y Precio (El Contrato Inteligente)
CREATE TABLE IF NOT EXISTS public.marketplace_listings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id uuid NOT NULL REFERENCES public.knowledge_collections(id),
    
    -- Quién puede comprar (Targeting)
    target_dept_id uuid, -- NULL = Cualquiera en la empresa
    
    -- Modelo de Precios (Configurable)
    pricing_model text DEFAULT 'PAY_PER_QUERY', -- 'PAY_PER_QUERY', 'MONTHLY_SUBSCRIPTION'
    base_price numeric(10, 4) DEFAULT 0.0,      -- Precio fijo por acceso
    token_markup_pct numeric(5, 2) DEFAULT 0.0, -- % extra sobre el coste del LLM (Markup)
    
    -- Licencia de Uso (Data Rights)
    license_type text DEFAULT 'FULL_ACCESS', -- 'FULL_ACCESS', 'SUMMARY_ONLY', 'CITATION_ONLY'
    
    is_active boolean DEFAULT true,
    UNIQUE(collection_id, target_dept_id)
);

-- 3. Reparto de Beneficios (Revenue Share)
-- Define quién cobra cuando esta colección genera dinero.
CREATE TABLE IF NOT EXISTS public.revenue_splits (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id uuid NOT NULL REFERENCES public.knowledge_collections(id),
    
    beneficiary_user_id uuid REFERENCES auth.users(id), -- El empleado que mantiene la doc
    share_percentage numeric(5, 2) NOT NULL CHECK (share_percentage > 0 AND share_percentage <= 100),
    
    created_at timestamp with time zone DEFAULT now()
);

-- 4. Suscripciones Activas (Quién compró qué)
CREATE TABLE IF NOT EXISTS public.active_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    buyer_dept_id uuid NOT NULL,
    collection_id uuid NOT NULL,
    listing_id uuid NOT NULL,
    
    expires_at timestamp with time zone, -- NULL = Para siempre (Pay per use)
    created_at timestamp with time zone DEFAULT now()
);

-- 5. RPC para Verificación Rápida de Acceso
CREATE OR REPLACE FUNCTION check_marketplace_access(
    p_tenant_id uuid,
    p_dept_id uuid,
    p_collection_ids uuid[]
)
RETURNS TABLE (
    collection_id uuid,
    listing_id uuid,
    license_type text,
    base_price numeric,
    markup numeric,
    owner_dept uuid
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        l.collection_id,
        l.id as listing_id,
        l.license_type,
        l.base_price,
        l.token_markup_pct,
        c.owner_dept_id
    FROM marketplace_listings l
    JOIN knowledge_collections c ON l.collection_id = c.id
    WHERE 
        c.id = ANY(p_collection_ids)
        AND l.is_active = true
        AND (
            l.target_dept_id IS NULL -- Público para la empresa
            OR l.target_dept_id = p_dept_id -- Específico para mi depto
            OR EXISTS ( -- O tengo una suscripción activa
                SELECT 1 FROM active_subscriptions s 
                WHERE s.listing_id = l.id AND s.buyer_dept_id = p_dept_id
                AND (s.expires_at IS NULL OR s.expires_at > now())
            )
        )
    ORDER BY l.base_price ASC; -- Si hay varias opciones, elige la más barata por defecto
END;
$$;
