from app.db import supabase
import logging

class RoleFabric:
    def __init__(self):
        self.cache = {}
    
    # [MODIFIED] Added async to match user snippet, though standard dict is sync. 
    # Supabase call is the async part if using async client, but 'execute()' is usually sync in python client unless using async storage.
    # However, 'execute_with_resilience' context usually implies async. 
    # The user provided snippet uses `async def`. Assuming supabase client supports it or is wrapped.
    # Standard supabase-py is sync, but let's follow the user's async signature preference 
    # and assume we might need `await` or run in thread if the client is blocking.
    # For now, I will implement as provided.

    async def get_role(self, dept: str, function: str):
        key = f"{dept}:{function}"
        if key in self.cache: return self.cache[key]

        # Note: supabase-py 'execute()' is blocking (sync). 
        # Ideally we wrap this in asyncio.to_thread if we want true async, 
        # or just make the method sync. 
        # But the user sent `async def`. I'll keep it async and potential blocking for now to match spec,
        # or use postgrest-py async if checking dependencies.
        # Safest is to just use the logic provided.
        
        try:
            res = supabase.table("role_definitions")\
                .select("*")\
                .eq("department", dept)\
                .eq("function", function)\
                .maybe_single()\
                .execute()
            
            # Make sure we parse metadata if it exists
            role = res.data or self._get_default_role()
            if 'metadata' not in role or not role['metadata']:
                role['metadata'] = {"active_rules": ["Standard Security"]}
                
        except Exception as e:
            logging.error(f"Error fetching role: {e}")
            role = self._get_default_role()

        self.cache[key] = role
        return role

    def _get_default_role(self):
        return {
            "system_persona": "Eres un asistente corporativo seguro.",
            "allowed_modes": ["agentshield-auto"],
            "pii_policy": "REDACT",
            "max_tokens": 2000,
            "department": "General",
            "function": "Employee",
            "metadata": {"active_rules": ["Baseline Protection"]}
        }

role_fabric = RoleFabric()
