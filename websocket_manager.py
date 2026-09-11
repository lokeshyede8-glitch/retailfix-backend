import logging
import json
import asyncio
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Store connections as dict: {"websocket": WebSocket, "user_id": str, "role": str, "username": str}
        self.active_connections: list[dict] = []

    async def connect(self, websocket: WebSocket, user_id: str, role: str, username: str, session_id: str = ""):
        """Accept a new websocket connection.

        If a previous connection exists for the same session_id, close it to prevent duplicate connections
        from the same client/session. This avoids duplicate event delivery and resource leaks.
        """
        await websocket.accept()

        # Close previous connections with same session_id to prevent duplicates
        if session_id:
            to_close = [c for c in list(self.active_connections) if c.get("session_id") == session_id]
            for conn in to_close:
                try:
                    await conn["websocket"].close(code=4003, reason="Duplicate session - replaced by new connection")
                except Exception:
                    pass
                try:
                    self.disconnect(conn["websocket"])
                except Exception:
                    pass

        self.active_connections.append({
            "websocket": websocket,
            "user_id": user_id or "",
            "role": role or "",
            "username": username or "",
            "session_id": session_id or ""
        })
        logger.info(f"WebSocket connected: {username} ({role}) - ID: {user_id} - Session: {session_id}. Active: {len(self.active_connections)}")

    async def disconnect_session(self, session_id: str):
        to_close = [c for c in self.active_connections if c.get("session_id") == session_id]
        for conn in to_close:
            try:
                await conn["websocket"].close(code=4001, reason="Session revoked")
            except Exception:
                pass
            self.disconnect(conn["websocket"])

    async def disconnect_user(self, user_id: str):
        to_close = [c for c in self.active_connections if c.get("user_id") == user_id]
        for conn in to_close:
            try:
                await conn["websocket"].close(code=4001, reason="User revoked")
            except Exception:
                pass
            self.disconnect(conn["websocket"])

    def disconnect(self, websocket: WebSocket):
        self.active_connections = [c for c in self.active_connections if c["websocket"] != websocket]
        logger.info(f"WebSocket disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        await self.broadcast_to_all(message)

    async def broadcast_to_all(self, message: str):
        for conn in self.active_connections:
            try:
                await conn["websocket"].send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to all: {e}")

    async def broadcast_to_role(self, message: str, role: str):
        for conn in self.active_connections:
            if conn["role"].lower() == role.lower():
                try:
                    await conn["websocket"].send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to role {role}: {e}")

    async def broadcast_to_user(self, message: str, user_id: str):
        for conn in self.active_connections:
            if conn["user_id"] == user_id:
                try:
                    await conn["websocket"].send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to user {user_id}: {e}")

    def validate_user(self, user_id: str, role: str) -> bool:
        from database import SessionLocal
        import models
        db = SessionLocal()
        try:
            if not role or not user_id:
                return False
            role_lower = role.lower()
            if role_lower == "admin":
                # Check if user exists in User table with admin role, or in Admin table
                u = db.query(models.User).filter(models.User.id == user_id, models.User.role == "admin").first()
                if not u:
                    u = db.query(models.Admin).filter(models.Admin.id == user_id).first()
                return u is not None
            elif role_lower == "salesman":
                s = db.query(models.Salesman).filter(models.Salesman.id == user_id).first()
                return s is not None
            elif role_lower == "telecaller":
                t = db.query(models.Telecaller).filter(models.Telecaller.id == user_id).first()
                return t is not None
            return False
        except Exception as e:
            logger.error(f"Error validating user: {e}")
            return False
        finally:
            db.close()

    async def broadcast_by_event_type(self, event_type: str, data: dict):
        payload = json.dumps({
            "type": event_type,
            "data": data
        })

        for conn in self.active_connections:
            role = conn["role"].lower()
            user_id = conn["user_id"]
            
            should_send = False
            
            if role == "admin":
                should_send = True
            elif role == "salesman":
                # Salesman gets their own leads, followups, remarks, notifications, visits
                if event_type in ["lead_created", "lead_updated", "lead_deleted", "remark_added", "status_changed", "followup_changed", "visit_note_added", "visit_history_updated", "lead_media_updated", "salesman_activity"]:
                    lead_salesman_id = data.get("salesman_id") or data.get("lead", {}).get("salesman_id")
                    lead_assigned_to = data.get("assigned_to") or data.get("lead", {}).get("assigned_to")
                    if lead_salesman_id == user_id or lead_assigned_to == user_id:
                        should_send = True
                elif event_type == "notification_created":
                    if data.get("user_id") == user_id or data.get("salesman_id") == user_id:
                        should_send = True
                elif event_type == "salesman_updated":
                    if data.get("id") == user_id:
                        should_send = True
            elif role == "telecaller":
                # Telecaller gets online leads (no salesman assigned) or leads assigned to them,
                # followups assigned to them, remarks, notifications, visits
                if event_type in ["lead_created", "lead_updated", "lead_deleted", "remark_added", "status_changed", "followup_changed", "visit_note_added", "visit_history_updated", "lead_media_updated", "telecaller_activity"]:
                    lead_salesman_id = data.get("salesman_id") or data.get("lead", {}).get("salesman_id")
                    lead_assigned_to = data.get("assigned_to") or data.get("lead", {}).get("assigned_to")
                    lead_current_owner = data.get("current_owner") or data.get("lead", {}).get("current_owner")
                    lead_created_by = data.get("created_by") or data.get("lead", {}).get("created_by")
                    lead_source = data.get("lead_source") or data.get("lead", {}).get("lead_source")
                    if (
                        not lead_salesman_id or
                        lead_assigned_to == conn["username"] or
                        lead_current_owner == conn["username"] or
                        lead_created_by == conn["username"] or
                        lead_source == "Salesman"
                    ):
                        should_send = True
                elif event_type == "notification_created":
                    if data.get("user_id") == user_id or data.get("telecaller_id") == user_id:
                        should_send = True
                elif event_type == "telecaller_updated":
                    if data.get("id") == user_id:
                        should_send = True

            if should_send:
                try:
                    await conn["websocket"].send_text(payload)
                except Exception as e:
                    logger.error(f"Error sending event {event_type} to user {user_id}: {e}")

ws_manager = ConnectionManager()

def broadcast_event(event_type: str, data: dict):
    """Schedule a WebSocket broadcast from synchronous or asynchronous code safely."""
    loop = getattr(ws_manager, 'main_loop', None)
    if not loop:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast_by_event_type(event_type, data), loop)
    else:
        try:
            asyncio.run(ws_manager.broadcast_by_event_type(event_type, data))
        except Exception as e:
            logger.error(f"Failed to broadcast event {event_type} (no event loop): {e}")
