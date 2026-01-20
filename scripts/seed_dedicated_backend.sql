-- Add backend_api_url to tenants for Dedicated SaaS routing
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='tenants' AND column_name='backend_api_url') THEN
        ALTER TABLE public.tenants ADD COLUMN backend_api_url TEXT DEFAULT NULL;
    END IF;
END $$;
