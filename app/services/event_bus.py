# app/services/event_bus.py
import json
import logging

import httpx

from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.siem")


class EventBus:
    async def publish(
        self,
        tenant_id: str,
        event_type: str,
        severity: str,
        details: dict,
        actor_id: str = None,
        trace_id: str = None,
    ):
        """
        Publica un evento en el sistema.
        Dispara: Persistencia -> Notificaciones -> Automatización.
        """
        # 1. PERSISTENCIA (Audit Log)
        try:
            event_data = {
                "tenant_id": str(tenant_id),
                "event_type": event_type,
                "severity": severity,
                "details": details,
                "actor_id": actor_id,
                "trace_id": trace_id,
            }
            supabase.table("system_events").insert(event_data).execute()
        except Exception as e:
            logger.error(f"Failed to persist event: {e}")

        # 2. DISPATCH (Webhooks / Slack)
        await self._dispatch_notifications(tenant_id, event_type, event_data)

        # 3. PLAYBOOKS (Reacción Automática)
        if severity in ["WARNING", "CRITICAL"]:
            await self._execute_playbooks(tenant_id, event_type, event_data)

    async def _dispatch_notifications(self, tenant_id, event_type, payload):
        """Envía alertas a los canales configurados."""
        try:
            destinations = (
                supabase.table("event_destinations")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("is_active", True)
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to fetch event destinations: {e}")
            return

        async with httpx.AsyncClient() as client:
            for dest in destinations.data:
                filters = dest.get("filter_events", []) or []
                if event_type not in filters and "*" not in filters:
                    continue

                try:
                    url = dest["config"].get("url")
                    if not url:
                        continue

                    if dest["channel_type"] == "SLACK":
                        msg = {
                            "text": f"🚨 *AgentShield Alert* [{payload['severity']}]\n*Event:* {event_type}\n*User:* {payload['actor_id']}\n*Trace:* `{payload['trace_id']}`"
                        }
                        await client.post(url, json=msg)
                    else:
                        await client.post(url, json=payload)

                except Exception as e:
                    logger.warning(f"Failed to send alert to {dest['name']}: {e}")

    async def _execute_playbooks(self, tenant_id, event_type, payload):
        """El Sistema Inmunológico: Ejecuta acciones correctivas automáticas."""
        from app.services.trust_system import trust_system

        try:
            rules = (
                supabase.table("automation_rules")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("trigger_event", event_type)
                .eq("is_active", True)
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to fetch automation rules: {e}")
            return

        for rule in rules.data:
            logger.info(f"⚡ Executing Playbook: {rule['name']}")
            action = rule["action_type"]
            user_id = payload["actor_id"]

            try:
                if action == "DEGRADE_MODEL" and user_id:
                    # Bajamos el Trust Score forzosamente
                    await trust_system.adjust_score(
                        tenant_id,
                        user_id,
                        delta=-20,
                        reason=f"Playbook Trigger: {rule['name']}",
                        event_type="AUTOMATED_RESPONSE",
                    )

                elif action == "FREEZE_WALLET":
                    # Podríamos bloquear el acceso en Redis
                    if user_id:
                        await redis_client.setex(f"lock:user:{user_id}", 3600, "frozen")

            except Exception as e:
                logger.error(f"Playbook execution failed: {e}")


event_bus = EventBus()
