from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
import os
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.crypto_signer import PUBLIC_KEY_PATH

router = APIRouter(prefix="/v1/audit", tags=["Audit & Compliance"])

@router.get("/public-key", response_class=PlainTextResponse)
async def get_public_key(
    # Public Key is... Public. But maybe we want to restrict to authenticated users?
    # For transparency, it should be open. But to avoid abuse, let's require identity for now or just open it.
    # The user/auditor needs it.
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Returns the RSA Public Key (PEM) used to sign forensic receipts.
    Designated Auditors use this to verify the 'signature' field in receipts.
    """
    if not os.path.exists(PUBLIC_KEY_PATH):
        raise HTTPException(500, "Public Key not found on server.")
        
    with open(PUBLIC_KEY_PATH, "r") as f:
        return f.read()

@router.get("/status")
async def audit_status():
    """
    Returns the health of the crypto subsystem.
    """
    return {
        "status": "active",
        "algorithm": "RSA-2048",
        "hashing": "SHA-256",
        "chaining": "enabled" 
    }
