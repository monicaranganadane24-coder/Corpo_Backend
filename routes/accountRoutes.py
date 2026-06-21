from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database.connection import SessionLocal
from models.playerModel import Player
from models.playerSchema import PlayerCreate
import os
from utils.sendEmail import send_confirmation_email


router = APIRouter(prefix="/account", tags=["Account"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------
# Vérifier si un email existe déjà
# ---------------------------------------------------------
class CheckEmailRequest(BaseModel):
    email: str

@router.post("/check_email")
def check_email(request: CheckEmailRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.email == request.email).first()
    if player:
        return {
            "exists":    True,
            "pseudo":    player.pseudo,
            "player_id": player.id
        }
    return {"exists": False}


# ---------------------------------------------------------
# INSCRIPTION
# ---------------------------------------------------------
@router.post("/register")
async def register(data: PlayerCreate, db: Session = Depends(get_db)):

    # Vérifier si email existe déjà
    existing = db.query(Player).filter(Player.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    # Vérifier si pseudo existe déjà
    existing_pseudo = db.query(Player).filter(Player.pseudo == data.pseudo).first()
    if existing_pseudo:
        raise HTTPException(status_code=400, detail="Pseudo déjà utilisé")

    # Création du joueur
    new_player = Player(
        pseudo=data.pseudo,
        email=data.email,
        password="",
        confirmed=True
    )
    db.add(new_player)
    db.commit()
    db.refresh(new_player)

    # Envoi du mail de bienvenue
    send_confirmation_email(
    to_email=data.email,
    subject="Bienvenue chez Corpo! 🎮",
    content=f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;padding:20px;">
        <h1 style="color:#c0392b;">Bienvenue chez Corpo! 🎉</h1>
        <p>Bonjour <strong>{data.pseudo}</strong>,</p>
        <p>Votre compte a été créé avec succès !</p>
        <p>Vous pouvez maintenant rejoindre ou créer des meetings et jouer avec vos collègues.</p>
        <br>
        <p style="color:#888;font-size:12px;">L'équipe Corpo!</p>
    </div>
    """
)
        # On ne bloque pas la création si le mail échoue

    return {
        "message":   "Compte créé avec succès !",
        "player_id": new_player.id,
        "pseudo":    new_player.pseudo
    }


# ---------------------------------------------------------
# CONNEXION
# ---------------------------------------------------------
@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    email = data.get("email")
    player = db.query(Player).filter(Player.email == email).first()
    if not player:
        raise HTTPException(status_code=404, detail="Email introuvable")
    return {
        "message":   "Connexion réussie",
        "pseudo":    player.pseudo,
        "player_id": player.id,
        "email":     player.email
    }