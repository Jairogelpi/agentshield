import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.crypto_signer import PUBLIC_KEY_PATH
from app.services.identity import VerifiedIdentity, verify_identity_envelope

router = APIRouter(prefix="/v1/audit", tags=["Audit & Compliance"])


@router.get("/public-key", response_class=PlainTextResponse)
async def get_public_key(
    # Public Key is... Public. But maybe we want to restrict to authenticated users?
    # For transparency, it should be open. But to avoid abuse, let's require identity for now or just open it.
    # The user/auditor needs it.
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Returns the RSA Public Key (PEM) used to sign forensic receipts.
    Designated Auditors use this to verify the 'signature' field in receipts.
    """
    if not os.path.exists(PUBLIC_KEY_PATH):
        raise HTTPException(500, "Public Key not found on server.")

    with open(PUBLIC_KEY_PATH) as f:
        return f.read()


@router.get("/status")
async def audit_status():
    """
    Returns the health of the crypto subsystem.
    """
        "chaining": "enabled",
    }


@router.get("/replay/{trace_id}")
async def forensic_replay(
    trace_id: str,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Forensic Replay (God Tier Observability).
    Reconstructs the full timeline of a request from the immutable Ledger.
    Only for Auditors/Admins.
    """
    if identity.role not in ["admin", "auditor", "dpo"]:
        raise HTTPException(status_code=403, detail="Forensic Access Denied")

    # Lazy import to avoid circular deps if any
    from app.db import supabase
    
    # 1. Fetch Primary Audit Record
    res = supabase.table("ai_act_audit_log").select("*").eq("trace_id", trace_id).execute()
    if not res.data:
        raise HTTPException(404, "Trace ID not found in Immutable Ledger")
    
    record = res.data[0]
    
    # 2. Reconstruct Timeline
    return {
        "meta": {
            "trace_id": trace_id,
            "timestamp": record.get("created_at"),
            "actor": record.get("user_id"),
            "risk_score": record.get("risk_score", 0),
        },
        "forensics": {
            "input_hash": record.get("prompt_hash"),
            "input_snapshot": record.get("content_snapshot", {}).get("prompt", "REDACTED"),
            "output_snapshot": record.get("content_snapshot", {}).get("response", "REDACTED"),
        },
        "compliance": {
            "eu_risk_category": record.get("risk_category"),
            "pii_detected": record.get("pii_detected", False),
            "policy_verdict": "APPROVED" if not record.get("blocked") else "BLOCKED"
        },
        "chain_of_custody": {
            "signature": record.get("signature"),
            "prev_hash": record.get("prev_hash")
        }
    }
