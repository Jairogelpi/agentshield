# app/logic.py
import os
import time
from jose import jwt

# Estas variables DEBEN estar en tu entorno de Render (.env)
SECRET_KEY = os.getenv("ASARL_SECRET_KEY") 
if not SECRET_KEY:
    raise ValueError("FATAL: ASARL_SECRET_KEY not set in environment")

ALGORITHM = "HS256"

def create_aut_token(data: dict):
    to_encode = data.copy()
    # Expire en 10 minutos (tiempo suficiente para ejecutar el prompt y volver)
    expire = time.time() + 600 
    to_encode.update({"exp": expire, "iss": "spendshield-core"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def sign_receipt(receipt_data: dict):
    # Firma inmutable del recibo
    return jwt.encode(receipt_data, SECRET_KEY, algorithm=ALGORITHM)

def check_policy(policy_rules, request_data, current_spend, monthly_limit):
    # 1. Check presupuesto
    if (current_spend + request_data.max_amount) > monthly_limit:
        return False, "Budget Exceeded"
    
    # 2. Check Max Request (ejemplo simple)
    if request_data.max_amount > policy_rules.get("max_per_request", 100):
        return False, "Request limit exceeded"
        
    return True, "Approved"