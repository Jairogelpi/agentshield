-- ==============================================================================
-- MÓDULO WHITE-LABEL & DOMAIN RESOLUTION
-- ==============================================================================

-- Actualizar tabla tenants para soportar marca blanca
DO $$
BEGIN
    -- 1. Custom Domain & Slug
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='custom_domain') THEN
        ALTER TABLE public.tenants ADD COLUMN custom_domain TEXT UNIQUE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='slug') THEN
        ALTER TABLE public.tenants ADD COLUMN slug TEXT UNIQUE;
    END IF;

    -- 2. Styling Config (Logo, Colors)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='brand_config') THEN
        ALTER TABLE public.tenants ADD COLUMN brand_config JSONB DEFAULT '{
            "logo_url": null,
            "primary_color": "#000000",
            "company_name": "AgentShield",
            "favicon_url": null
        }'::jsonb;
    END IF;

    -- 3. SSO Config (OIDC/SAML Public Info)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='sso_config') THEN
        ALTER TABLE public.tenants ADD COLUMN sso_config JSONB DEFAULT '{}'::jsonb;
    END IF;

END $$;

-- Índice para búsqueda rápida por dominio (CRÍTICO para el middleware)
CREATE INDEX IF NOT EXISTS idx_tenants_domain ON public.tenants(custom_domain);
