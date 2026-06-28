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
    asyncio.create_task(cleanup_loop())

async def cleanup_loop():
    while True:
        await asyncio.sleep(60)  # vérifier toutes les 60 secondes
        db = SessionLocal()
        try:
            limite_inactivite = datetime.utcnow() - timedelta(minutes=2)
            limite_joueur = datetime.utcnow() - timedelta(seconds=30)

            parties = db.query(Party).filter(Party.status == "waiting").all()
            for party in parties:
                players = db.query(Player).filter(
                    Player.party_id == party.id
                ).all()

                # Joueurs actifs = ceux qui ont envoyé un heartbeat récemment
                active_players = [
                    p for p in players
                    if p.last_seen and p.last_seen > limite_joueur
                ]

                empty = len(active_players) == 0
                inactive = party.last_activity and party.last_activity < limite_inactivite

                if empty or inactive:
                    for p in players:
                        p.party_id = None
                    db.flush()
                    db.delete(party)
                    db.flush()
                    print(f"🗑️ Partie {party.code} supprimée (vide={empty} inactive={inactive})")

            db.commit()
        except Exception as e:
            print(f"⚠️ Erreur cleanup : {e}")
        finally:
            db.close()

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