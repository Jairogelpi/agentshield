# agentshield_core/scripts/sync_prices.py
import requests
import os
import sys

# Add parent directory to path to allow imports if needed, 
# but this script mainly uses standalone env vars.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
import redis

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
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)

def fetch_latest_prices():
    """
    Descarga precios frescos de una fuente confiable (OpenRouter o similar)
    y actualiza tu base de datos 'Source of Truth'.
    """
    print("🔄 Iniciando sincronización masiva...")
    
    try:
        url = "https://openrouter.ai/api/v1/models"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        
        updates = []
        for model in data:
            # Normalizar datos
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
            
            if p_in >= 0:
                updates.append({
                    "provider": provider,
                    "model": m_id,
                    "price_in": p_in,
                    "price_out": p_out,
                    "is_active": True,
                    "updated_at": "now()"
                })

        if updates:
            print(f"📦 Escribiendo {len(updates)} registros en Supabase...")
            # Upsert por lotes (Batching)
            batch_size = 500
            for i in range(0, len(updates), batch_size):
                supabase.table("model_prices").upsert(updates[i:i+batch_size], on_conflict="provider, model").execute()
            
            print("⚡ Invalidando caché de Redis (Non-Blocking)...")
            
            # LÓGICA SCAN_ITER + UNLINK (Evita bucles infinitos y bloqueos)
            batch_keys = []
            total_deleted = 0
            
            for key in redis_client.scan_iter(match="price:*", count=1000):
                batch_keys.append(key)
                if len(batch_keys) >= 1000:
                    redis_client.unlink(*batch_keys)
                    total_deleted += len(batch_keys)
                    batch_keys = []
            
            if batch_keys:
                redis_client.unlink(*batch_keys)
                total_deleted += len(batch_keys)
                
            print(f"✅ Éxito: DB actualizada y {total_deleted} llaves purgadas en Redis.")
            
    except Exception as e:
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    fetch_latest_prices()
