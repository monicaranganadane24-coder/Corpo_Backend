from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database.connection import Base

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)

    # 🔥 Partie COMPTE
    pseudo = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    confirmed = Column(Boolean, default=False)

    # 🔥 Partie JEU
    role = Column(String(50), nullable=True)
    last_role = Column(String(50), nullable=True)

    is_alive = Column(Boolean, default=True)
    has_used_power = Column(Boolean, default=False)
    has_drawn_corpocard = Column(Boolean, default=False)

    victim_of_managers = Column(Boolean, default=False)
    victim_of_claire = Column(Boolean, default=False)
    virus_from_abdel = Column(Boolean, default=False)

    left_neighbor_id = Column(Integer, nullable=True)
    right_neighbor_id = Column(Integer, nullable=True)

    is_manager = Column(Boolean, default=False)
    revealed_to = Column(Integer, nullable=True)

    last_seen = Column(DateTime, default=datetime.utcnow)

    party_id = Column(Integer, ForeignKey("parties.id"), nullable=True)
    party = relationship("Party", back_populates="players")
