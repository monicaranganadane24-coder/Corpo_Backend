from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal
from models.playerModel import Player
from models.playerSchema import PlayerCreate

router = APIRouter(prefix="/account", tags=["Account"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 🔥 INSCRIPTION SANS MOT DE PASSE
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

    # Création du joueur SANS mot de passe
    new_player = Player(
        pseudo=data.pseudo,
        email=data.email,
        password="",   # plus de mot de passe
        confirmed=True
    )

    db.add(new_player)
    db.commit()
    db.refresh(new_player)

    return {"message": "Compte créé avec succès !"}


# 🔥 CONNEXION AVEC EMAIL UNIQUEMENT
@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    email = data.get("email")

    # Vérifier si le joueur existe
    player = db.query(Player).filter(Player.email == email).first()
    if not player:
        raise HTTPException(status_code=404, detail="Email introuvable")

    return {
        "message": "Connexion réussie",
        "pseudo": player.pseudo,
        "email": player.email
    }
