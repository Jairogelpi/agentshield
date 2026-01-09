# scripts/billing_worker.py
import asyncio
import os
import redis.asyncio as redis
from supabase import create_client, Client
from collections import defaultdict
import logging
import signal

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("billing_worker")

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
REDIS_URL = os.getenv("REDIS_URL")

if not all([SUPABASE_URL, SUPABASE_KEY, REDIS_URL]):
    logger.error("Missing configuration values. Please set SUPABASE_URL, SUPABASE_SERVICE_KEY, and REDIS_URL.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.from_url(REDIS_URL, decode_responses=False) # Keep bytes for Streams

STREAM_KEY = "billing:stream"
GROUP_NAME = "billing_group"
CONSUMER_NAME = "worker_1"

async def setup_redis_group():
    try:
        await redis_client.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        logger.info(f"Consumer Group '{GROUP_NAME}' created.")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer Group '{GROUP_NAME}' already exists.")
        else:
            raise e

async def flush_billing_to_supabase():
    """
    Worker que agrupa transacciones (Batching) para optimizar Supabase.
    """
    logger.info("🚀 Billing Worker Started. Waiting for events...")
    await setup_redis_group()

    while True:
        try:
            # 1. Read pending events from the stream
            # We use '>' to ask for new messages that have not been delivered to other consumers in this group
            events = await redis_client.xreadgroup(
                GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=500, block=2000
            )

            if not events:
                # Sleep briefly to avoid busy loop if block returns early/empty
                await asyncio.sleep(0.1)
                continue

            # 2. AGREGACIÓN INTELIGENTE (Batching)
            batch_updates = defaultdict(float)
            event_ids = []

            # redis returns: [[stream_name, [[msg_id, {field: value, ...}], ...]]]
            for stream_name, messages in events:
                for msg_id, data in messages:
                    # Data is bytes in redis-py unless decode_responses=True (which we disabled for safety with binary data)
                    tid = data.get(b'tid').decode('utf-8')
                    cc = data.get(b'cc').decode('utf-8')
                    amt = float(data.get(b'amt').decode('utf-8'))
                    
                    key = (tid, cc)
                    batch_updates[key] += amt
                    event_ids.append(msg_id)

            if not batch_updates:
                continue

            logger.info(f"⚡ Flushing {len(event_ids)} events aggregated into {len(batch_updates)} updates.")

            # 3. Escritura masiva en Supabase (Una sola transacción SQL)
            # Prepare payload for RPC
            rpc_payload = [
                {"tid": k[0], "cc": k[1], "amt": v} 
                for k, v in batch_updates.items()
            ]

            try:
                # Execute RPC
                # We need to run this in a thread executor because supabase-py is sync (or mostly sync for HTTP)
                # But here we assume we can just await if we wrap it or if we use the async client properly (client is sync usually)
                # For safety, let's wrap in executor.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: supabase.rpc("batch_increment_spend", {"payload": rpc_payload}).execute())
                
                # 4. ACK (Acknowledge processing)
                if event_ids:
                    await redis_client.xack(STREAM_KEY, GROUP_NAME, *event_ids)
                    # Optional: Delete form stream to keep it small (or use capped stream)
                    # await redis_client.xdel(STREAM_KEY, *event_ids)
                
                logger.info("✅ Batch Flush Successful.")

            except Exception as e:
                # Observabilidad permanente: registrar fallo de sincronización
                logger.error(f"🔥 Critical Billing Sync Error: {e}")
                # Naive retry logic: We do NOT Ack, so they will be redelivered.
                # In production, check failure count to avoid poison pills.

        except Exception as outer_e:
            logger.error(f"Worker Loop Error: {outer_e}")
            await asyncio.sleep(1)

def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(flush_billing_to_supabase())

if __name__ == "__main__":
    main()
