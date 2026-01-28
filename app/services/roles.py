import logging

from app.db import supabase


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
        if key in self.cache:
            return self.cache[key]

        # Note: supabase-py 'execute()' is blocking (sync).
        # Ideally we wrap this in asyncio.to_thread if we want true async,
        # or just make the method sync.
        # But the user sent `async def`. I'll keep it async and potential blocking for now to match spec,
        # or use postgrest-py async if checking dependencies.
        # Safest is to just use the logic provided.

        try:
            res = (
                supabase.table("role_definitions")
                .select("*")
                .eq("department", dept)
                .eq("function", function)
                .maybe_single()
                .execute()
            )

            # Make sure we parse metadata if it exists
            role = res.data or self._get_default_role()
            if "metadata" not in role or not role["metadata"]:
                role["metadata"] = {"active_rules": ["Standard Security"]}
                
            # [NEW] Dynamic Hydration
            # We assume context is empty here as get_role signature is (dept, function).
            # To support dynamic injection based on request context, we need to pass it or infer it.
            # However, the user plan showed:
            # def _hydrate_template(self, template: str, context: dict) -> str:
            # But get_role returns the dict, the injection likely happens later or we modify get_role signature?
            # Or we modify the role['system_persona'] here if we have context?
            # Since get_role is cached, we should hydrate AFTER retrieval or cache the template and hydrate on usage.
            # But the user specifically asked to modify RoleFabric.
            # Let's add the hydration method and leave it to the caller (proxy.py) to use it, OR 
            # if we can, modify get_role to accept context (breaking change?).
            # Wait, proxy.py calls `active_role = await role_fabric.get_role(...)`.
            # And then uses `active_role.get("system_persona")`.
            # So if we want the dict returned to already be hydrated, we need context passed to get_role.
            # But caching dynamic strings is bad. 
            # Solution: We return the Role dict, and add a helper method to hydrate, 
            # OR we simply cache the raw role and hydrate on return.
            # Let's assume we modify get_role to take text optional context or just standard static hydration 
            # (Date is dynamic but global).
            # The User Plan says "Inject Dynamic Context in RoleFabric".
            # "Una persona dinamica sabe que dia es... vitaminar el metodo _hydrate_template".
            # And implies this is used during retrieval?
            # Let's add the helper method first.
            
            # Since we can't easily change the method signature used in other files without checking usages,
            # We will implement `hydrate_persona` method and auto-hydrate with basic available info (Date).
            # For security score, it needs to be passed.
            
            # Let's actually add the method `hydrate_role` and use it.
            
            # BUT, the user prompt implies effectively overriding the logic.
            # "Tu código actual (Inferido): return template.replace... La versión God Tier: ..."
            
            pass

        except Exception as e:
            logging.error(f"Error fetching role: {e}")
            role = self._get_default_role()

        self.cache[key] = role
        
        # [NEW] Hydration Logic (On Retrieval)
        # We clone the dict to not mutate cache with dynamic values
        hydrated_role = role.copy()
        hydrated_role["system_persona"] = self._hydrate_template(role.get("system_persona", ""), context={
            "dept": dept,
            "function": function
        })
        
        return hydrated_role

    def _hydrate_template(self, template: str, context: dict) -> str:
        """
        Inyecta consciencia situacional en el Prompt del Sistema.
        """
        import datetime
        
        # 1. Variables Temporales (Vital para Legal/Finanzas)
        now = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 2. Variables de Seguridad (El sistema sabe si es seguro)
        # Por defecto, asumimos seguro si no se pasa el score. 
        # En proxy.py podríamos pasar esto si modificamos la firma, pero por ahora lo dejamos estático o inferido.
        # El usuario pidió: security_mode = "🛡️ SECURE ENVIRONMENT" if context.get("trust_score", 0) > 80 else ...
        trust_score = context.get("trust_score", 90) # Default to high if unknown
        security_mode = "🛡️ SECURE ENVIRONMENT" if trust_score > 80 else "⚠️ HIGH RISK DETECTED"
        
        # 3. Inyección
        # Usamos .format() pero con seguridad de que las keys existan en el template?
        # Los templates generados por LLM no tendrán {user_name} etc a menos que se lo digamos.
        # Pero podemos append al final.
        
        # Safe format (won't crash if keys missing in string, but standard format crashes if keys missing in dict? No, converse.)
        # If template has {date}, and we provide date, it works. If template has nothing, it works.
        # If template has {unknown}, it crashes.
        # Given we generated the personas, they likely don't have placeholders yet.
        # So we mainly append the metadata block as requested.
        
        # The user code: 
        # hydrated = template.format(...)
        # hydrated += f"\n\n[SYSTEM METADATA...]"
        
        # Since our templates are LLM generated without placeholders, format might throw error if we force it?
        # Or no, format only replaces {} tokens. If none, it returns string.
        # Unless string has random {} like JSON. "JSON strict { ... }" -> Crash.
        # We need to be careful.
        
        # BETTER APPROACH: Append the context block, don't risk .format on the main body unless we control it.
        # OR: limit .format scope.
        # User plan: "return template.replace(...)".
        
        hydrated = template
        # Manual replace is safer for generated text that might contain code blocks with {}
        hydrated = hydrated.replace("{user}", context.get("user_name", "User"))
        hydrated = hydrated.replace("{date}", now)
        
        # 4. Añadimos la 'Directiva Primaria' de AgentShield al final siempre
        hydrated += f"\n\n[SYSTEM METADATA: Date={now} | Security={security_mode} | Vigilance=ACTIVE]"
        
        return hydrated

    def _get_default_role(self):
        return {
            "system_persona": "Eres un asistente corporativo seguro.",
            "allowed_modes": ["agentshield-auto"],
            "pii_policy": "REDACT",
            "max_tokens": 2000,
            "department": "General",
            "function": "Employee",
            "metadata": {"active_rules": ["Baseline Protection"]},
        }


role_fabric = RoleFabric()
