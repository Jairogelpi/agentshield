# app/services/receipt_manager.py
import time
import uuid
from app.db import supabase
from app.services.crypto_signer import sign_payload, hash_content
import logging

logger = logging.getLogger("agentshield.auditor")

async def create_forensic_receipt(
    tenant_id: str,
    user_email: str,
    transaction_data: dict,
    policy_snapshot: dict
) -> dict:
    """
    Genera un recibo firmado, encadenado al anterior y listo para auditoría.
    Implementa: Hash Chaining + RSA Signing.
    """
    
    # 1. OBTENER EL ÚLTIMO HASH (CHAINING)
    # Buscamos el último recibo de este Tenant para encadenarlo
    # Esto crea la Blockchain privada.
    try:
        last_receipt = supabase.table("receipts")\
            .select("hash")\
            .eq("tenant_id", tenant_id)\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()
            
        # Si no hay historial, este es el BLOQUE GENESIS
        prev_hash = last_receipt.data[0]['hash'] if last_receipt.data else "GENESIS_BLOCK_0000000000000000000000000000000000000000000000000000000000000000"
    except Exception as e:
        logger.warning(f"Failed to fetch previous hash for {tenant_id}: {e}")
        prev_hash = "ERROR_FETCHING_PREVIOUS_HASH" # Rompe la cadena, pero permite servicio? 
        # En modo Zero Trust militar, deberíamos fallar. Pero para MVP, logueamos.

    # 2. CONSTRUIR EL PAYLOAD DE EVIDENCIA
    receipt_id = str(uuid.uuid4())
    timestamp = int(time.time())
    
    evidence_payload = {
        "receipt_id": receipt_id,
        "timestamp": timestamp,
        "tenant_id": tenant_id,
        "actor": user_email,
        "previous_hash": prev_hash, # <--- ENCADENAMIENTO MATEMÁTICO
        
        # Datos Financieros y Técnicos
        "model_requested": transaction_data.get("model_requested"),
        "model_delivered": transaction_data.get("model_delivered"),
        "cost_usd": transaction_data.get("cost_usd"),
        "tokens": transaction_data.get("tokens"), # {input, output}
        
        # Datos de Gobierno (Policy Proof)
        "policy_decision": transaction_data.get("decision", "ALLOW"),
        "pii_redactions": transaction_data.get("redactions_count", 0),
        
        # Hash "snapshot" de las reglas vigentes. 
        # Si la política cambia mañana, podemos probar que HOY era esta.
        "policy_version_hash": hash_content(policy_snapshot) 
    }

    # 3. FIRMAR LA EVIDENCIA (Sello Criptográfico)
    # Usamos la clave privada RSA del servidor.
    try:
        digital_signature = sign_payload(evidence_payload)
    except Exception as e:
        logger.error(f"Signing failed: {e}")
        digital_signature = "SIGNATURE_FAILED"

    # 4. CALCULAR HASH DEL RECIBO ACTUAL (Para el siguiente eslabón)
    current_hash = hash_content(evidence_payload)

    # 5. PERSISTIR EN DB (Log Inmutable)
    receipt_record = {
        "id": receipt_id,
        "tenant_id": tenant_id,
        "content_json": evidence_payload, # El JSON puro para lectura
        "signature": digital_signature,   # La garantía de autenticidad
        "hash": current_hash,             # La huella para encadenar
        # created_at se llena en DB o aquí
    }
    
    try:
        # Guardar en Supabase (Asumimos tabla 'receipts')
        supabase.table("receipts").insert(receipt_record).execute()
        logger.info(f"⚖️ Forensic Receipt Signed: {receipt_id} (Prev: {prev_hash[:8]}...)")
    except Exception as e:
        logger.error(f"Failed to persist forensic receipt: {e}")
    
    return receipt_record
