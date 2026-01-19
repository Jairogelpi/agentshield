import asyncio
from app.db import supabase
import os

# Tenant principal (podemos sacarlo de una query o usar 'default' para este script)
# Para este script asumimos que queremos insertarlo para el tenant de demo o globalmente si el sistema lo soporta.
# Como el campo es tenant_id, consultaremos el primer tenant existente.

async def seed_tools():
    print("🌱 Seeding Multimodal Tools...")
    
    # 1. Obtener un tenant válido
    res = supabase.table("tenants").select("id").limit(1).execute()
    if not res.data:
        print("❌ No tenants found. Create a tenant first.")
        return
        
    tenant_id = res.data[0]['id']
    print(f"🎯 Targeting Tenant: {tenant_id}")
    
    tools = [
        {
            "name": "web_search",
            "description": "Busca información en tiempo real en Google/Bing",
            "cost_per_execution": 0.01,
            "risk_level": "LOW"
        },
        {
            "name": "python_interpreter",
            "description": "Ejecuta código Python para análisis de datos y gráficas",
            "cost_per_execution": 0.05,
            "risk_level": "HIGH"
        },
        {
            "name": "image_generation",
            "description": "Crea imágenes artísticas o realistas (DALL-E)",
            "cost_per_execution": 0.04,
            "risk_level": "MEDIUM"
        }
    ]
    
    for t in tools:
        # Check if exists
        existing = supabase.table("tool_definitions").select("id").eq("name", t["name"]).eq("tenant_id", tenant_id).execute()
        if not existing.data:
            data = t.copy()
            data["tenant_id"] = tenant_id
            try:
                supabase.table("tool_definitions").insert(data).execute()
                print(f"✅ Inserted: {t['name']}")
            except Exception as e:
                print(f"⚠️ Failed to insert {t['name']}: {e}")
        else:
            print(f"⏭️ Skipped (Exists): {t['name']}")

    print("✨ Tool Seed Complete.")

if __name__ == "__main__":
    asyncio.run(seed_tools())
