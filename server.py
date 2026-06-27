from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from database.connection import engine, Base, SessionLocal
from datetime import datetime, timedelta
import asyncio

from models.playerModel import Player
from models.partyModel import Party

# Import WebSocket manager
from websocket_manager import connections, handle_message, disconnect

app = FastAPI()

# 🔥 CORS complet — nécessaire pour Render + WebSocket
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # ← IMPORTANT : False quand allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

@app.on_event("startup")
async def startup_event():
    from websocket_manager import cleanup_inactive_parties
    asyncio.create_task(cleanup_inactive_parties())

# Import des routes
from routes.accountRoutes import router as account_router
from routes import partyRoutes
from routes import meetingRoutes

app.include_router(account_router)
app.include_router(partyRoutes.router)
app.include_router(meetingRoutes.router)

# ---------------------------------------------------------------------
# 🔥 ROUTE WEBSOCKET SÉCURISÉE (Structure par Player ID)
# ---------------------------------------------------------------------
@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str, player_id: int = Query(...)):
    """
    Le client se connecte en fournissant son ID unique :
    Exemple : wss://corpo-backend.onrender.com/ws/CODE?player_id=12
    """
    await websocket.accept()

    if code not in connections:
        connections[code] = {}

    connections[code][player_id] = websocket
    print(f"🔌 Joueur {player_id} connecté dans la room {code}")

    try:
        while True:
            try:
                message = await websocket.receive_text()
            except Exception:
                await disconnect(code, websocket)
                break

            await handle_message(code, websocket, message)

    except WebSocketDisconnect:
        await disconnect(code, websocket)