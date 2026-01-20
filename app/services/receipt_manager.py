# app/services/receipt_manager.py
import base64
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import supabase
from app.services.carbon import carbon_governor
from app.services.crypto_signer import hash_content, sign_payload
from app.services.estimator import estimate_cost

logger = logging.getLogger("agentshield.auditor")


async def create_forensic_receipt(
    tenant_id: str, user_email: str, transaction_data: dict, policy_snapshot: dict
) -> dict:
    """
    Genera un recibo firmado, encadenado al anterior y listo para auditoría.
    Implementa: Hash Chaining + RSA Signing con DATOS REALES.
    """

    # 1. OBTENER EL ÚLTIMO HASH (CHAINING)
    try:
        last_receipt = (
            supabase.table("receipts")
            .select("hash")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        prev_hash = (
            last_receipt.data[0]["hash"] if last_receipt.data else "GENESIS_BLOCK_" + "0" * 48
        )
    except Exception as e:
        logger.warning(f"Chaining Warning for {tenant_id}: {e}")
        prev_hash = "CHAIN_INTERRUPTED_RECOVERY_MODE"

    # 2. CONSTRUIR EL PAYLOAD DE EVIDENCIA
    receipt_id = str(uuid.uuid4())
    timestamp = int(time.time())

    evidence_payload = {
        "receipt_id": receipt_id,
        "timestamp": timestamp,
        "tenant_id": tenant_id,
        "actor": user_email,
        "previous_hash": prev_hash,
        "transaction": transaction_data,
        "governance": policy_snapshot,
        "integrity": {
            "signature_algorithm": "RSA-SHA256",
            "policy_version_hash": hash_content(policy_snapshot),
        },
    }

    # 3. FIRMAR LA EVIDENCIA
    try:
        digital_signature = sign_payload(evidence_payload)
    except Exception as e:
        logger.error(f"Signing failed: {e}")
        digital_signature = "SIGNATURE_FAILED"

    # 4. CALCULAR HASH DEL RECIBO ACTUAL
    current_hash = hash_content(evidence_payload)

    # 5. PERSISTIR EN DB (Log Inmutable)
    receipt_record = {
        "id": receipt_id,
        "tenant_id": tenant_id,
        "content_json": evidence_payload,
        "signature": digital_signature,
        "hash": current_hash,
    }

    try:
        supabase.table("receipts").insert(receipt_record).execute()
        logger.info(f"⚖️ Forensic Receipt Signed: {receipt_id}")
    except Exception as e:
        logger.error(f"Failed to persist forensic receipt: {e}")

    return receipt_record


class ReceiptManager:
    async def create_and_sign_receipt(
        self, tenant_id: str, user_id: str, request_data: dict, response_data: Any, metadata: dict
    ):
        """
        Enterprise Forensics: Creates and signs a receipt in background.
        Calculates REAL Net/Gross costs and CO2.
        """
        model_requested = metadata.get("requested_model", "agentshield-fast")
        model_effective = metadata.get("effective_model", model_requested)

        # 1. Usage Data Real-time
        usage = getattr(response_data, "usage", {})
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()

        prompt_t = usage.get("prompt_tokens", 0)
        compl_t = usage.get("completion_tokens", 0)
        total_t = prompt_t + compl_t

        # 2. Financial & Carbon Audit - DYNAMIC
        # cost_real y cost_gross ya no usan PRICING_TABLE, sino Market Oracle y DB Fallbacks
        cost_real = await estimate_cost(model_effective, prompt_t, compl_t)
        cost_gross = await estimate_cost(model_requested, prompt_t, compl_t)

        # Carbon tracking dinámico (API + DB)
        co2_actual = await carbon_governor.estimate_footprint(model_effective, prompt_t, compl_t)
        co2_gross = await carbon_governor.estimate_footprint(model_requested, prompt_t, compl_t)

        # 3. Transaction Metadata
        transaction_data = {
            "model_requested": model_requested,
            "model_delivered": model_effective,
            "cost_usd": cost_real,
            "savings_usd": max(0, cost_gross - cost_real),
            "tokens": {"input": prompt_t, "output": compl_t, "total": total_t},
            "carbon_g": co2_actual,
            "co2_avoided_g": max(0, co2_gross - co2_actual),
            "cost_center_id": metadata.get("dept_id"),
        }

        # 4. Sign and Persist
        receipt_record = await create_forensic_receipt(
            tenant_id=tenant_id,
            user_email=user_id,
            transaction_data=transaction_data,
            policy_snapshot={
                "trust_score": metadata.get("trust_score"),
                "intent": metadata.get("intent"),
                "risk_mode": metadata.get("risk_mode"),
                "dept_id": metadata.get("dept_id"),
            },
        )

        # 5. Enrichment
        try:
            supabase.table("receipts").update(
                {
                    "cost_real": cost_real,
                    "cost_gross": cost_gross,
                    "savings_usd": transaction_data["savings_usd"],
                    "model_requested": model_requested,
                    "model_effective": model_effective,
                    "co2_gross_g": co2_gross,
                    "co2_actual_g": co2_actual,
                    "cost_center_id": metadata.get("dept_id"),
                    "tokens": total_t,
                }
            ).eq("id", receipt_record["id"]).execute()
        except Exception as e:
            logger.error(f"Financial enrichment failed: {e}")


receipt_manager = ReceiptManager()
