# agentshield_core/scripts/generate_pki.py
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime

def generate_cert():
    print("🔐 Generando Autoridad de Certificación (PKI) para AgentShield...")
    
    # 1. Generar Llave Privada (RSA 2048) - ESTA ES LA JOYA DE LA CORONA
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # 2. Generar Certificado X.509 (Auto-firmado para este MVP)
    # En producción real, enviarías una CSR (Certificate Signing Request) a DigiCert o similar.
    subject = issuer = x509.Name([
        x509.NameAttribute(x509.NameOID.COUNTRY_NAME, u"ES"),
        x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, u"Madrid"),
        x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, u"AgentShield Trust Network"),
        x509.NameAttribute(x509.NameOID.COMMON_NAME, u"AgentShield Root CA"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        # Válido por 10 años
        datetime.datetime.utcnow() + datetime.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True,
    ).sign(private_key, hashes.SHA256(), default_backend())

    # 3. Exportar a PEM (Texto)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    print("\n--- COPIA ESTO EN TUS VARIABLES DE ENTORNO (Render) ---\n")
    print(f"AS_C2PA_PRIVATE_KEY=\n{key_pem.decode()}")
    print("\n-------------------------------------------------------\n")
    print(f"AS_C2PA_PUBLIC_CERT=\n{cert_pem.decode()}")
    print("\n-------------------------------------------------------\n")
    print("✅ ¡Listo! Ahora AgentShield es una entidad criptográfica real.")

if __name__ == "__main__":
    generate_cert()
