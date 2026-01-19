# app/services/negotiator.py
from app.services.llm_gateway import execute_with_resilience
import logging

logger = logging.getLogger("agentshield.negotiator")

async def negotiate_budget(user_prompt: str, requested_model: str, user_balance: float):
    """
    Un Agente IA pequeño (Haiku/GPT-3.5) juzga si la petición del usuario merece
    romper el límite de presupuesto.
    """
    # Si el usuario tiene saldo, pase. (Este check suele hacerse fuera, pero por seguridad)
    if user_balance > 0:
        return True, "Approved (Balance Sufficient)"

    # Si no tiene saldo, EL JUEZ ENTRA EN ACCIÓN
    judge_prompt = [
        {"role": "system", "content": """
         Eres el Director Financiero IA de AgentShield.
         El usuario no tiene presupuesto, pero quiere usar un modelo caro.
         Analiza su prompt.
         - Si es una tarea CRÍTICA, COMPLEJA o DE NEGOCIO -> APRUEBA (Devuelve 'YES', seguido de razón).
         - Si es una tarea TRIVIAL, HOLA MUNDO o CHISTES -> DENIEGA (Devuelve 'NO', seguido de razón).
         Sé estricto pero justo. Prioriza el ROI del negocio.
         """},
        {"role": "user", "content": f"Request: {user_prompt}\nModel Requested: {requested_model}"}
    ]
    
    try:
        # Usamos un modelo barato ("agentshield-fast") para juzgar al caro
        # user_id="system_cfo" para que no cuente contra el usuario (o sí?) -> "system"
        verdict = await execute_with_resilience("agentshield-fast", judge_prompt, "system_cfo")
        decision_text = verdict['choices'][0]['message']['content'].strip()
        
        if decision_text.upper().startswith("YES"):
            reason = decision_text[3:].strip() or "Strategic Alignment Verified"
            return True, f"Emergency Credit Granted: {reason}"
        else:
            reason = decision_text[2:].strip() or "Task not critical enough."
            return False, f"Request denied: {reason}"
            
    except Exception as e:
        logger.error(f"Negotiation failed: {e}")
        return False, "Negotiation Service Unavailable"
