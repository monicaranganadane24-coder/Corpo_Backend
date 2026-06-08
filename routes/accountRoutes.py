from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal
from models.playerModel import Player
from models.playerSchema import PlayerCreate
from utils.hashPassword import hash_password, verify_password
from utils.sendEmail import send_confirmation_email

router = APIRouter(prefix="/account", tags=["Account"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 🔥 INSCRIPTION
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

    # Hash du mot de passe
    hashed_pw = hash_password(data.password)

    # Création du joueur
    new_player = Player(
        pseudo=data.pseudo,
        email=data.email,
        password=hashed_pw,
        confirmed=False
    )

    db.add(new_player)
    db.commit()
    db.refresh(new_player)

    # Envoi d'un email simple
    subject = "Votre compte a bien été créé !"
    content = f"""
    <h2>Bienvenue {data.pseudo} 🎉</h2>
    <p>Votre compte a bien été créé sur <strong>Corpo – Le Jeu</strong>.</p>
    <p>Vous pouvez maintenant vous connecter et commencer à jouer !</p>
    """

    await send_confirmation_email(data.email, subject, content)

    return {"message": "Compte créé ! Un email de confirmation a été envoyé."}


# 🔥 CONNEXION
@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    pseudo = data.get("pseudo")
    password = data.get("password")

    # Vérifier si le joueur existe
    player = db.query(Player).filter(Player.pseudo == pseudo).first()
    if not player:
        raise HTTPException(status_code=404, detail="Pseudo introuvable")

    # Vérifier le mot de passe
    if not verify_password(password, player.password):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect")

    return {
        "message": "Connexion réussie",
        "pseudo": player.pseudo
    }
