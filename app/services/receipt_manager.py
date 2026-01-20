# app/services/receipt_manager.py
import json
import hashlib
import time
import base64
from datetime import datetime, timezone
from app.services.crypto_signer import sign_data
from app.db import supabase
from app.schema import AgentShieldContext  # Importamos el nuevo contexto

async def create_receipt(
    ctx: AgentShieldContext,
    transaction_details: dict,
    governance_details: dict
) -> dict:
    """
    Genera un recibo forense firmado digitalmente.
    Sigue el estándar 'AgentShield Evidence Protocol'.
    """
    
    # 1. Obtener Hash Anterior (Cadena de Bloques simplificada)
    # Buscamos el último recibo de este tenant para encadenarlo
    try:
        last_receipt = supabase.table("receipts") \
            .select("signature") \
            .eq("tenant_id", ctx.tenant_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        previous_hash = "GENESIS_BLOCK"
        if last_receipt.data and len(last_receipt.data) > 0:
            # Hash de la firma anterior sirve como enlace
            prev_sig = last_receipt.data[0]['signature']
            previous_hash = hashlib.sha256(prev_sig.encode()).hexdigest()
    except Exception:
        previous_hash = "UNKNOWN_LINK"

    # 2. Construir Payload Canónico (Ordenado para firma consistente)
    # User Hash para privacidad (GDPR friendly logs)
    user_hash = hashlib.sha256(ctx.email.encode()).hexdigest()

    receipt_data = {
      "receipt_id": f"rcpt_{ctx.request_id}",
      "timestamp_utc": datetime.now(timezone.utc).isoformat(),
      
      "context": {
        "tenant_id": ctx.tenant_id,
        "user_hash": user_hash, 
        "dept_id": ctx.dept_id,
        "cost_center": "default_cost_center" # TODO: Sacar de Dept details
      },

      "transaction": {
        "model_requested": transaction_details.get("model_requested"),
        "model_delivered": transaction_details.get("model_delivered"),
        "tokens": { 
            "input": transaction_details.get("input_tokens", 0), 
            "output": transaction_details.get("output_tokens", 0) 
        },
        "cost_usd": transaction_details.get("cost_usd", 0.0),
        "latency_ms": transaction_details.get("latency_ms", 0)
      },

      "governance": {
        "policy_version_hash": governance_details.get("policy_hash", "no_policy"),
        "decision": governance_details.get("decision", "ALLOW"),
        "pii_redacted": governance_details.get("pii_redacted", False),
        "redaction_count": governance_details.get("redaction_count", 0),
        "pii_types": governance_details.get("pii_types", [])
      },

      "integrity": {
        "previous_receipt_hash": previous_hash,
        "signature_algorithm": "RSA-SHA256"
      }
    }

    # 3. Firmar Digitalmente
    # Serializamos igual que como se verificará en el frontend
    payload_str = json.dumps(receipt_data, sort_keys=True)
    signature = sign_data(payload_str)

    # 4. Ensamblar Recibo Final
    final_receipt = receipt_data.copy()
    final_receipt["signature"] = signature

    # 5. Persistir en DB (Evidence Vault)
    # Background task idealmente, pero aquí lo hacemos inline por simplicidad del ejemplo
    try:
        supabase.table("receipts").insert({
            "id": receipt_data["receipt_id"],
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "model": transaction_details.get("model_delivered"),
            "tokens": transaction_details.get("input_tokens", 0) + transaction_details.get("output_tokens", 0),
            "cost": transaction_details.get("cost_usd", 0.0),
            "full_receipt": final_receipt, # Guardamos JSON completo
            "signature": signature
        }).execute()
    except Exception as e:
        print(f"Failed to persist receipt: {e}")

    return final_receipt

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
class ReceiptManager:
    async def create_and_sign_receipt(
        self,
        tenant_id: str,
        user_id: str,
        request_data: dict,
        response_data: Any,
        metadata: dict
    ):
        """
        Enterprise Forensics: Creates and signs a receipt in background.
        """
        # Mapeamos a la lógica forense existente
        transaction_data = {
            "model_requested": metadata.get("original_model"),
            "model_delivered": metadata.get("effective_model"),
            "cost_usd": 0.0, # TODO: Calculate real cost
            "tokens": {"input": 0, "output": 0},
            "decision": "ALLOW",
            "redactions_count": metadata.get("pii_redacted", 0)
        }
        
        await create_forensic_receipt(
            tenant_id=tenant_id,
            user_email=user_id, # Usamos ID como identificador
            transaction_data=transaction_data,
            policy_snapshot={"trust_score": metadata.get("trust_score_snapshot")}
        )

receipt_manager = ReceiptManager()
