
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.db import redis_client

logger = logging.getLogger("agentshield.middleware")

class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 1. IP Blocklist Check (Basic)
        client_ip = request.client.host
        # In prod: if await redis_client.sismember("blocked_ips", client_ip): return 403
        
        # 2. Add Security Headers
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # 3. Simple Audit Log for Slow Requests
        if process_time > 2.0:
            logger.warning(f"🐢 Slow Request: {request.method} {request.url.path} took {process_time:.2f}s")
            
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Global Rate Limiter backed by Redis.
    Applies strict limits to unauthenticated endpoints.
    Authenticated endpoints have their own quota system in Pipeline.
    """
    async def dispatch(self, request: Request, call_next):
        # Skip for health checks or static
        if request.url.path == "/health" or request.method == "OPTIONS":
             return await call_next(request)
             
        client_ip = request.client.host
        key = f"rl:global:{client_ip}"
        
        try:
             # Max 100 requests per minute per IP for public endpoints
             current = await redis_client.incr(key)
             if current == 1:
                 await redis_client.expire(key, 60)
                 
             if current > 100:
                 return JSONResponse(
                     status_code=429, 
                     content={"detail": "Too Many Requests (Global Shield)"}
                 )
        except Exception:
            # Fail open if Redis is down
            pass
            
        return await call_next(request)
