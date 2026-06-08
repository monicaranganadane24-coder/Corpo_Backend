from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from database.connection import engine, Base, SessionLocal
from datetime import datetime, timedelta
import asyncio

from models.playerModel import Player
from models.partyModel import Party

# Import WebSocket manager
from websocket_manager import connections, handle_message, disconnect

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

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
    Le client se connecte desormais en fournissant son ID unique :
    Exemple : ws://127.0.0.1:8000/ws/CODE?player_id=12
    """
    await websocket.accept()

    # Initialisation de la room sous forme de dictionnaire si elle n'existe pas
    if code not in connections:
        connections[code] = {}

    # Enregistrement du WebSocket associé à l'ID du joueur
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



























































