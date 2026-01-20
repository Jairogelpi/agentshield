-- ==============================================================================
-- DYNAMIC SYSTEM CONSTANTS (Zero-Hardcoding)
-- ==============================================================================

-- 1. Carbon Grid Intensity (gCO2/kWh)
INSERT INTO public.system_config (key, value) VALUES (
  'carbon_grid_intensity',
  '{
    "azure-eu": 250,
    "openai-us": 400,
    "anthropic": 200,
    "default": 350
  }'::jsonb
) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 2. Energy Consumption per 1k Tokens (kWh)
INSERT INTO public.system_config (key, value) VALUES (
  'energy_per_1k_tokens',
  '{
    "gpt-4": 0.004,
    "gpt-4o": 0.002,
    "gpt-3.5-turbo": 0.0004,
    "claude-3-opus": 0.003,
    "claude-3-sonnet": 0.001,
    "agentshield-eco": 0.0003,
    "default": 0.001
  }'::jsonb
) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 3. Global Financial Fallbacks (Price per 1M tokens)
-- Used when Market Oracle fails to provide a real-time price
INSERT INTO public.system_config (key, value) VALUES (
  'pricing_fallbacks',
  '{
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "agentshield-fast": {"input": 0.2, "output": 0.6},
    "default": {"input": 1.0, "output": 2.0}
  }'::jsonb
) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 4. General Governance Defaults
INSERT INTO public.system_config (key, value) VALUES (
  'governance_defaults',
  '{
    "default_cost_center": "CORP-HQ",
    "default_role": "member",
    "co2_soft_limit_g": 5000,
    "trust_threshold_supervised": 30
  }'::jsonb
) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
