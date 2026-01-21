import logging
import os

import resend

logger = logging.getLogger("agentshield.email")

# Configurar API Key
resend.api_key = os.getenv("RESEND_API_KEY")

# Configuración del Remitente (Domain Authentication)
# 1. En Desarrollo (sin dominio): Usa "onboarding@resend.dev" (solo envía a tu propio email)
# 2. En Producción: Configura la variable de entorno RESEND_FROM_EMAIL = "AgentShield <noreply@getagentshield.com>"
SENDER_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")


async def send_welcome_email(to_email: str, name: str = "Agent"):
    """
    Envía el correo de bienvenida oficial de AgentShield.
    """
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set. Skipping email.")
        return False

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #09090b; color: #e4e4e7; margin: 0; padding: 40px 20px; }}
        .container {{ max-width: 480px; margin: 0 auto; background-color: #18181b; border: 1px solid #27272a; border-radius: 12px; overflow: hidden; }}
        .header {{ background-color: #000000; padding: 24px; text-align: center; border-bottom: 1px solid #27272a; }}
        .logo {{ font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px; text-decoration: none; }}
        .content {{ padding: 32px 24px; }}
        h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 16px; color: #ffffff; }}
        p {{ font-size: 14px; line-height: 1.6; margin: 0 0 24px; color: #a1a1aa; }}
        .btn {{ display: block; width: 100%; background-color: #ffffff; color: #000000; padding: 12px 0; text-align: center; border-radius: 6px; font-weight: 600; font-size: 14px; text-decoration: none; transition: opacity 0.2s; }}
        .btn:hover {{ opacity: 0.9; }}
        .footer {{ padding: 24px; text-align: center; font-size: 11px; color: #52525b; border-top: 1px solid #27272a; background-color: #09090b; line-height: 1.5; }}
        .link {{ color: #71717a; text-decoration: underline; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <span class="logo">🛡️ AgentShield</span>
        </div>
        <div class="content">
          <h1>Welcome to the Elite, {name}</h1>
          <p>Your workspace is ready. You have taken the first step towards a Secure, Governed, and Auditable Artificial Intelligence infrastructure.</p>
          <p>Your <strong>Zero-Trust Architecture</strong> is now active and monitoring.</p>
          
          <a href="https://agentshield.ai/dashboard" class="btn">Launch Dashboard</a>
          
        </div>
        <div class="footer">
          <p>&copy; 2026 AgentShield Inc. All rights reserved.<br>
          This is an automated security message. Please do not reply.</p>
          <p><a href="https://getagentshield.com/legal/privacy" class="link">Privacy Policy</a> • <a href="https://getagentshield.com/legal/terms" class="link">Terms of Service</a></p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        r = resend.Emails.send(
            {
                "from": SENDER_EMAIL,
                "to": to_email,
                "subject": "🛡️ Bienvenido a AgentShield OS",
                "html": html_content,
            }
        )
        logger.info(f"Welcome email sent to {to_email}: {r}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return False
