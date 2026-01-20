# scripts/seed_constants.py
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import supabase

CONSTANTS = {
    "carbon_grid_intensity": {"azure-eu": 250, "openai-us": 400, "anthropic": 200, "default": 350},
    "energy_per_1k_tokens": {
        "gpt-4": 0.004,
        "gpt-4o": 0.002,
        "gpt-3.5-turbo": 0.0004,
        "claude-3-opus": 0.003,
        "claude-3-sonnet": 0.001,
        "agentshield-eco": 0.0003,
        "default": 0.001,
    },
    "pricing_fallbacks": {
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        "agentshield-fast": {"input": 0.2, "output": 0.6},
        "default": {"input": 1.0, "output": 2.0},
    },
    "governance_defaults": {
        "default_cost_center_name": "CORPORATE-LEGAL",
        "default_role": "member",
        "co2_soft_limit_g": 5000,
        "trust_threshold_supervised": 30,
    },
}


async def seed():
    print("🚀 Seeding AgentShield System Constants...")
    for key, val in CONSTANTS.items():
        try:
            res = (
                supabase.table("system_config")
                .upsert({"key": key, "value": val, "updated_at": "now()"})
                .execute()
            )
            print(f"✅ Key: {key} upserted.")
        except Exception as e:
            print(f"❌ Error upserting {key}: {e}")


if __name__ == "__main__":
    asyncio.run(seed())
