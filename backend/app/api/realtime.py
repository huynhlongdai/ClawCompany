import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.realtime import broker
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User

router = APIRouter(tags=["realtime"])


def _extract_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

@router.websocket("/ws/events/{organization_id}")
async def org_events(websocket: WebSocket, organization_id: int):
    token = _extract_token(websocket)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        claims = decode_access_token(token)
        if int(claims.get("org_id")) != int(organization_id):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        db = SessionLocal()
        try:
            user = db.get(User, int(claims["sub"]))
            if not user or not user.is_active:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        finally:
            db.close()
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    try:
        async for event in broker.subscribe(f"org:{organization_id}"):
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        return
