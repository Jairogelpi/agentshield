-- Add security_config to tenants for global security settings
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='security_config') THEN
        ALTER TABLE public.tenants ADD COLUMN security_config JSONB DEFAULT '{
            "ai_mode": "LOCAL" 
        }'::jsonb;
    END IF;
END $$;
