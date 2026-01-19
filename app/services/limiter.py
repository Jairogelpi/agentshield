# app/services/limiter.py
from app.db import redis_client
from app.services.identity import VerifiedIdentity
import logging

logger = logging.getLogger("agentshield.limiter")

async def check_hierarchical_budget(identity: VerifiedIdentity, cost_estimated: float) -> tuple[bool, str]:
    """
    Verifica la solvencia en 3 niveles simultáneos:
    1. Wallet de Empresa (Tenant)
    2. Wallet de Departamento (Cost Center)
    3. Wallet Personal (User Allowance)
    
    Returns: (Allowed: bool, Reason: str)
    """
    # Claves de Redis para los 3 niveles
    # Nota: Asegurarse de que estas claves se inicializan/syncronizan con la DB
    keys = {
        "tenant": f"wallet:tenant:{identity.tenant_id}",
        "dept":   f"wallet:dept:{identity.dept_id}",
        "user":   f"wallet:user:{identity.user_id}"
    }
    
    try:
        # Obtenemos los saldos actuales en una sola llamada (Pipeline)
        # Esto es ultra-rápido (< 2ms)
        raw_balances = await redis_client.mget(keys["tenant"], keys["dept"], keys["user"])
        
        # Convertimos a float (si es None asumimos 0.0 o INFINITO dependiende de la logica de negocio)
        # Para seguridad ZER O TRUST, asumimos 0.0 si no existe.
        # TODO: Implementar un "Fallback" que cargue de DB si Redis está vacío para evitar falsos negativos al inicio.
        
        def parse_balance(val):
            return float(val) if val is not None else 0.0

        bal_tenant = parse_balance(raw_balances[0])
        bal_dept   = parse_balance(raw_balances[1])
        bal_user   = parse_balance(raw_balances[2])
        
        # LA REGLA DE HIERRO (The Waterfall Check)
        errors = []
        if bal_tenant < cost_estimated:
            errors.append("Corporate funds exhausted")
        if bal_dept < cost_estimated:
            errors.append(f"Department '{identity.dept_id}' budget exceeded")
        if bal_user < cost_estimated:
            errors.append(f"Personal allowance for {identity.email} exhausted")
            
        if errors:
            # Logueamos el intento fallido para auditoría
            logger.warning(f"💸 Budget Block for {identity.email} (Est: ${cost_estimated:.4f}): {', '.join(errors)}")
            return False, errors[0] # Devolvemos la razón más específica

        return True, "OK"
        
    except Exception as e:
        logger.error(f"Limiter Error: {e}")
        # Fail safe? O Fail close?
        # Zero Trust dice Fail Close.
        return False, "Internal Budget Check Error"

async def charge_hierarchical_wallets(identity: VerifiedIdentity, cost_real: float):
    """
    Descuenta el dinero de los 3 niveles atómicamente.
    """
    try:
        p = redis_client.pipeline()
        p.decrbyfloat(f"wallet:tenant:{identity.tenant_id}", cost_real)
        p.decrbyfloat(f"wallet:dept:{identity.dept_id}", cost_real)
        p.decrbyfloat(f"wallet:user:{identity.user_id}", cost_real)
        await p.execute()
        # logger.info(f"💰 Charged ${cost_real:.6f} to {identity.email} hierarchy")
    except Exception as e:
        logger.error(f"Wallet Charge Error: {e}")
        # Aquí deberíamos tener una cola de reintento o inserción directa en DB 'wallet_transactions'
        # para consistencia eventual.
