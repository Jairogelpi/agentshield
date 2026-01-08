from fastapi import FastAPI
from app.routers import authorize, receipt 

app = FastAPI(title="AgentShield API", version="1.0.0")

# Conectar el router de autorización real (el que verifica API Keys y Policies)
app.include_router(authorize.router)
app.include_router(receipt.router)

# Endpoint de salud para Render (ping)
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agentshield-core"}