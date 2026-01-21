-- ==============================================================================
-- AUTOMATIC WELCOME EMAIL TRIGGER (CORREGIDO)
-- ==============================================================================
-- Requirement: pg_net extension enabled in Supabase/Postgres.
-- create extension if not exists pg_net;

create extension if not exists pg_net;

-- 1. Create the Function that calls our Python Backend
CREATE OR REPLACE FUNCTION public.trigger_welcome_email()
RETURNS TRIGGER AS $$
DECLARE
    -- ✅ URL CORRECTA DE PRODUCCIÓN
    api_url text := 'https://api.getagentshield.com/v1/webhooks/auth/user-created';
    
    -- 🔐 SECRETO COMPARTIDO (Debe coincidir con la env var WEBHOOK_SECRET en Render)
    -- He generado uno seguro para ti, pero puedes cambiarlo si quieres.
    secret text := '8f4b2c9d1e3a5f7608b9c4d2e1a3f567'; 
    
    payload jsonb;
BEGIN
    -- Construir el payload JSON que espera nuestro endpoint (WebhookPayload)
    payload := jsonb_build_object(
        'type', TG_OP,
        'table', TG_TABLE_NAME,
        'schema', TG_TABLE_SCHEMA,
        'record', row_to_json(NEW),
        'old_record', null
    );

    -- Hacer la petición POST asíncrona (Fire & Forget)
    -- Usamos net.http_post de la extensión pg_net
    PERFORM net.http_post(
        url := api_url,
        body := payload,
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Webhook-Secret', secret
        )
    );

    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    -- Si falla el webhook, NO fallamos el registro del usuario (Graceful Degradation)
    RAISE WARNING 'Welcome email webhook failed: %', SQLERRM;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 2. Create the Trigger
DROP TRIGGER IF EXISTS on_auth_user_created_welcome ON auth.users;

CREATE TRIGGER on_auth_user_created_welcome
AFTER INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.trigger_welcome_email();

-- 3. Comments
COMMENT ON FUNCTION public.trigger_welcome_email IS 'Calls agentshield-core to send welcome email via Resend.';
