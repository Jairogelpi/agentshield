# app/services/vault.py
import os

def get_secret(key: str, default: str = None) -> str:
    """
    Abstracción del Gestor de Secretos (Vault/Infisical).
    En producción, esto se conecta a Infisical u otro gestor.
    En este despliegue (Render), leemos de variables de entorno inyectadas.
    """
    return os.getenv(key, default)
