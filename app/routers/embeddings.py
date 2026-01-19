# app/routers/embeddings.py
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from app.services.identity import verify_identity_envelope
from app.schema import AgentShieldContext
from litellm import embedding
import time
import logging

# Logger
logger = logging.getLogger("agentshield.embeddings")

router = APIRouter()

# Placeholder para billing (podemos importarlo si existe o usar lógica ad-hoc)
# from app.services import billing

@router.post("/v1/embeddings")
async def proxy_embeddings(
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: AgentShieldContext = Depends(verify_identity_envelope)
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

        # 1. Validación de Presupuesto (¿Puede este usuario vectorizar 10MB?)
        # Estimar tokens (aprox 1 token = 4 chars de media en inglés, varía)
        # Input puede ser str o list[str]
        char_count = 0
        if isinstance(input_text, str):
            char_count = len(input_text)
        elif isinstance(input_text, list):
            char_count = sum(len(s) for s in input_text if isinstance(s, str))
            
        est_tokens = char_count / 4
        
        # TODO: Lógica de limiter.check_budget(ctx, est_tokens) iría aquí...
        # Por ahora solo logueamos la intención
        logger.info(f"🧠 RAG Request from {ctx.email}: ~{est_tokens:.0f} tokens via {model}")

        # 2. Ejecución (Usando LiteLLM)
        # embedding() is sync in litellm usually, wrapping might be needed if blocking.
        # But litellm might handle async with separate function `aembedding`.
        # Assuming sync for simplicity or wrap in run_in_executor if needed.
        # To be safe with async server, let's use aembedding if available or assume fast response.
        
        from litellm import aembedding
        start = time.time()
        response = await aembedding(model=model, input=input_text)
        duration = time.time() - start

        # 3. Auditoría y Cobro
        usage = response.usage
        total_tokens = usage.total_tokens
        
        # Calcular coste real (Embeddings son baratos, pero el volumen es alto)
        # USD prices: text-embedding-3-small ~ $0.00002 / 1k tokens
        cost = (total_tokens / 1000) * 0.00002 
        
        logger.info(f"✅ Embeddings generated: {total_tokens} toks (${cost:.6f}) in {duration:.2f}s")
        
        # Registrar el gasto igual que un chat (Mock)
        # background_tasks.add_task(billing.charge, ctx, cost)
        
        # Devolvemos formato OpenAI standard
        return response

    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
