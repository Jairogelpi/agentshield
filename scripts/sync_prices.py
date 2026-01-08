# agentshield_core/scripts/sync_prices.py
import requests
import os
import sys

# Add parent directory to path to allow imports if needed, 
# but this script mainly uses standalone env vars.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

# Configuración
# Asegúrate de cargar las variables de entorno antes de ejecutar este script
# o usar python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: SUPABASE_URL or SUPABASE_SERVICE_KEY not set.")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_latest_prices():
    """
    Descarga precios frescos de una fuente confiable (OpenRouter o similar)
    y actualiza tu base de datos 'Source of Truth'.
    """
    print("🔄 Iniciando sincronización de precios...")
    
    # OPCIÓN A: Usar OpenRouter (Tienen todos los modelos y precios al día)
    try:
        url = "https://openrouter.ai/api/v1/models"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        
        updates = []
        for model in data:
            # Normalizar datos
            # OpenRouter ID: "openai/gpt-4o" -> provider="openai", model="gpt-4o"
            full_id = model.get("id", "")
            parts = full_id.split("/")
            if len(parts) == 2:
                provider = parts[0]
                m_id = parts[1]
            else:
                provider = "openrouter"
                m_id = full_id

            pricing = model.get("pricing", {})
            
            try:
                p_in = float(pricing.get("prompt", 0))
                p_out = float(pricing.get("completion", 0))
            except ValueError:
                continue
            
            # Solo actualizamos si tenemos precios válidos
            if p_in >= 0: # Permitimos 0 para free models
                updates.append({
                    "provider": provider,
                    "model": m_id,
                    "price_in": p_in,
                    "price_out": p_out,
                    "is_active": True,
                    "updated_at": "now()"
                })

        # Upsert masivo en Supabase (tabla model_prices que creamos en el SQL)
        if updates:
            print(f"📦 Detectados {len(updates)} modelos.")
            # Supabase upsert puede fallar con listas muy grandes si supera el payload size.
            # Lo hacemos por lotes de 100 si es necesario, pero OpenRouter tiene ~100-200 modelos.
            # Intento directo:
            data = supabase.table("model_prices").upsert(updates, on_conflict="provider, model").execute()
            print(f"✅ Precios actualizados exitosamente.")
            
    except Exception as e:
        print(f"❌ Error actualizando precios: {e}")

if __name__ == "__main__":
    fetch_latest_prices()
