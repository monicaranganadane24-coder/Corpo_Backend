from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
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
def register(data: PlayerCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):

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

    # Envoi du mail en arrière-plan — ne bloque pas la réponse
    background_tasks.add_task(
        send_confirmation_email,
        to_email=data.email,
        subject="Bienvenue chez Corpo! 🎮",
        content=f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;padding:20px;border:1px solid #eee;border-radius:8px;">
            <h1 style="color:#c0392b;margin-bottom:20px;">Bienvenue dans l'Open-Space ! 🎉</h1>
            <p>Bonjour <strong>{data.pseudo}</strong>,</p>
            <p>Félicitations, ton processus d'onboarding est validé. Ton badge virtuel et ton accès à la machine à café sont désormais actifs !</p>
            <p>Toi aussi, tu frôles le burn-out rien qu'en lisant un compte-rendu de réunion ? Parfait. Il est temps de saboter tes collègues ou de licencier tes managers toxiques avant qu'ils ne te virent.</p>
            <p style="margin-top:20px;"><strong>Ton premier meeting t'attend... Ne sois pas en retard (ça fait mauvais genre).</strong></p>
            <br>
            <hr style="border:none;border-top:1px solid #eee;">
            <p style="color:#888;font-size:12px;margin-top:15px;">Cordialement,<br><strong>La Direction de Corpo!</strong><br><span style="font-style:italic;">"Travailler plus pour trahir plus."</span></p>
        </div>
        """
    )

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