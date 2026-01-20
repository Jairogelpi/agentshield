# app/routers/embeddings.py
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks, UploadFile
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from litellm import embedding
import time
import logging

# Logger
logger = logging.getLogger("agentshield.embeddings")

router = APIRouter()

# Import the vault service for file ingestion
from app.services.vault import vault

@router.post("/v1/embeddings")
async def proxy_embeddings(
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Endpoint crítico para RAG. 
    Intercepta la vectorización de documentos para cobrar y auditar.
    """
    try:
        body = await request.json()
        input_text = body.get("input")
        model = body.get("model", "text-embedding-3-small") # Default barato

        if not input_text:
            raise HTTPException(status_code=400, detail="Missing input text")

        # 1. Validación de Presupuesto
        char_count = 0
        if isinstance(input_text, str):
            char_count = len(input_text)
        elif isinstance(input_text, list):
            char_count = sum(len(s) for s in input_text if isinstance(s, str))
            
        est_tokens = char_count / 4
        
        logger.info(f"🧠 RAG Request from {ctx.email}: ~{est_tokens:.0f} tokens via {model}")

        # 2. Ejecución (Usando LiteLLM)
        from litellm import aembedding
        start = time.time()
        response = await aembedding(model=model, input=input_text)
        duration = time.time() - start

        # 3. Auditoría y Cobro
        usage = response.usage
        total_tokens = usage.total_tokens
        
        cost = (total_tokens / 1000) * 0.00002 
        
        logger.info(f"✅ Embeddings generated: {total_tokens} toks (${cost:.6f}) in {duration:.2f}s")
        
        # Devolvemos formato OpenAI standard
        return response

    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/v1/files")
async def upload_file(
    file: UploadFile,
    # Use VerifiedIdentity explicitly for consistency with vault service type hinting
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Ingesta segura de archivos PDF/TXT desde la UI (AgentShield Vault).
    """
    try:
        # 0. FileGuardian Inspection (Block Sensitive Content)
        from app.services.file_guardian import file_guardian
        await file_guardian.inspect_and_filter(
            file=file, 
            user_id=identity.user_id, 
            tenant_id=identity.tenant_id, 
            dept_id=getattr(identity, 'dept_id', None) # Asumimos que VerifiedIdentity pronto tendrá dept_id
        )

        content = await file.read()
        # Simple decode, for PDFs use pypdf or similar in real impl
        # Assuming text files for this MVP step
        text = content.decode("utf-8", errors="ignore") 
        
        doc_id = await vault.ingest_document(
            identity=identity,
            filename=file.filename,
            text_content=text,
            classification="INTERNAL" # Default
        )
        
        return {"id": str(doc_id), "status": "securely_indexed", "filename": file.filename}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/v1/files")
async def list_files(
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Lista los documentos del Vault visibles para el usuario.
    """
    try:
        from app.db import supabase
        # Consulta segura: Solo docs del tenant
        res = supabase.table("vault_documents")\
            .select("id, filename, classification, created_at, owner_dept_id")\
            .eq("tenant_id", identity.tenant_id)\
            .order("created_at", desc=True)\
            .execute()
            
        return res.data
    except Exception as e:
        logger.error(f"List files failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
