# app/services/crypto_signer.py
import base64
import hashlib
import json
import logging
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger("agentshield.crypto")

# En producción, estas claves deben cargarse desde variables de entorno seguras (AWS Secrets / Vault)
# Para este MVP, generamos o cargamos desde directorio 'certs' local.
CERT_DIR = "certs"
PRIVATE_KEY_PATH = os.path.join(CERT_DIR, "private_key.pem")
PUBLIC_KEY_PATH = os.path.join(CERT_DIR, "public_key.pem")


def load_private_key():
    """
    Carga la clave privada del servidor.
    Prioridad:
    1. Variable de Entorno (Producción/Render)
    2. Archivo Local (Desarrollo)
    """
    # 1. Intentar cargar desde ENV (Para Render/Vercel)
    env_key = os.getenv("PRIVATE_KEY_PEM")
    if env_key:
        try:
            # Si viene como string en una línea (sin saltos), hay que formatearlo o asumirlo válido
            # Normalmente en Render se puede pegar el contenido multilínea.
            # Convertimos a bytes
            key_bytes = env_key.encode("utf-8")
            logger.info("✅ Loaded Private Key from Environment")
            return serialization.load_pem_private_key(key_bytes, password=None)
        except Exception as e:
            logger.error(f"❌ Failed to load key from ENV: {e}")
            # Fallback to local file

    # 2. Fallback: Archivo Local (Desarrollo)
    if not os.path.exists(PRIVATE_KEY_PATH):
        logger.info("🔑 Generating new RSA 2048 Keypair for Digital Notary...")
        # Generar una si no existe (Solo para setup inicial)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # Guardar en disco (¡Protege este archivo!)
        os.makedirs(CERT_DIR, exist_ok=True)
        with open(PRIVATE_KEY_PATH, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        # Generar pública también para el auditor
        public_key = private_key.public_key()
        with open(PUBLIC_KEY_PATH, "wb") as f:
            f.write(
                public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
        logger.info(f"✅ Keys generated in {CERT_DIR}/")
        return private_key

    with open(PRIVATE_KEY_PATH, "rb") as key_file:
        return serialization.load_pem_private_key(key_file.read(), password=None)


# Singleton loader
_signer_key = load_private_key()


def sign_payload(payload: dict) -> str:
    """
    Firma un diccionario JSON. Devuelve la firma en Base64.
    Garantiza: Autenticidad (Fuiste tú) e Integridad (No se modificó ni un bit).
    """
    # 1. Canonicalizar el JSON (ordenar keys para que el hash sea estable)
    # separators=(',', ':') elimina espacios en blanco para consistencia estricta
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # 2. Firmar con SHA256 + RSA PSS (Probabilistic Signature Scheme - Recommended)
    signature = _signer_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )

    return base64.b64encode(signature).decode("utf-8")


def hash_content(data: dict) -> str:
    """Crea un Hash SHA256 del contenido (Huella digital)."""
    payload_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


def get_public_key_pem() -> str:
    """
    Retorna la clave pública en formato PEM para adjuntar en paquetes de evidencia.
    """
    # 1. Intentar desde ENV
    en_pub = os.getenv("PUBLIC_KEY_PEM")
    if en_pub:
        return en_pub

    # 2. Intentar desde archivo
    if os.path.exists(PUBLIC_KEY_PATH):
        with open(PUBLIC_KEY_PATH, "r") as f:
            return f.read()

    # 3. Extraer del objeto signer (fallback final)
    if _signer_key:
        public_key = _signer_key.public_key()
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    return "-----BEGIN PUBLIC KEY-----\nKEY_NOT_CONFIGURED\n-----END PUBLIC KEY-----"
