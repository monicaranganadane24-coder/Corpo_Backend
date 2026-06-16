from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database.connection import Base

class Party(Base):
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)
    host_id = Column(Integer, nullable=False)
    name = Column(String(100), nullable=True)
    is_private = Column(Boolean, default=False)
    status = Column(String(20), default="waiting")  # "waiting", "started", "revelation", "ended"
    last_activity = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    meeting_number = Column(Integer, default=1)

    # 🔄 Gestion du tour par tour dans le meeting
    turn_order = Column(Text, nullable=True)  # Stocke la liste des IDs sous forme de chaîne JSON ex: "[3, 7, 12]"
    current_turn = Column(Integer, default=0)

    # 📌 Phase globale du jeu
    meeting_phase = Column(String(30), default="waiting")
    # Valeurs possibles : "waiting", "meeting", "feedback", "vote"

    # 🎯 Système de file d'attente pour les défis (Gestion du "un par un" et des ex-æquo)
    last_eliminated_id = Column(Integer, nullable=True)  # ID du joueur actuellement "sur la sellette" pour son défi
    
    defi_sub_phase = Column(String(30), nullable=True)
    # Valeurs possibles : 
    # "decision" (10s pour choisir d'utiliser sa carte Corpo), 
    # "running" (15s pour faire le défi), 
    # "validation" (Vote du groupe pour valider le défi)

    # 🎯 Défi Corpo actuel
    current_defi_id = Column(Integer, nullable=True)  # ID du défi en cours

    # 🎯 Tiffany — mots interdits
    tiff_mots_actifs   = Column(Text, nullable=True)  # Mots interdits en cours
    tiff_mots_utilises = Column(Text, nullable=True)  # Tous les mots déjà proposés

    # 👥 Relation avec les joueurs
    players = relationship(
        "Player",
        back_populates="party",
        cascade="all, delete-orphan"
    )