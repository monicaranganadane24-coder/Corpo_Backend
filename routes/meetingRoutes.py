import code

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.connection import get_db, SessionLocal
from models.playerModel import Player
from models.partyModel import Party
from websocket_manager import broadcast, next_turn, send_to_player
import json
import asyncio

router = APIRouter(prefix="/meeting", tags=["Meeting"])

ORDER_MEETING_1 = [
    "Cindy", "Denis",
    "Fabien", "Claire", "Tiff", "Pascal", "Stéphane", "Abdel"
]


ORDER_MEETING_2PLUS = [
    "Cindy", "Denis",
    "Fabien", "Claire", "Tiff", "Pascal", "Stéphane", "Abdel"
]

# Dictionnaire pour tracker les tâches de timer par room
# { "CODE": asyncio.Task }
turn_timers = {}


async def auto_advance_turn(code: str, expected_turn: int, delay: int = 25):
    """
    Attend `delay` secondes puis force le passage au tour suivant
    si le current_turn n'a pas encore changé (le joueur n'a pas agi).
    """
    await asyncio.sleep(delay)

    db = SessionLocal()
    try:
        party = db.query(Party).filter(Party.code == code).first()
        if not party or party.meeting_phase != "meeting":
            return
        # Si le tour n'a pas encore avancé → forcer
        if party.current_turn == expected_turn:
            print(f"⏱️ Auto-avance forcée pour room {code} (tour {expected_turn})")
            await next_turn(code, party, db)
    finally:
        db.close()


async def start_meeting(code: str, db: Session):
    """Appelé depuis partyRoutes après attribution des rôles."""
    party = db.query(Party).filter(Party.code == code.strip()).first()
    if not party:
        return

    players = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True
    ).all()

    if not players:
        return

    roles_present = {p.role: p for p in players}
    ordre_officiel = ORDER_MEETING_1 if party.meeting_number == 1 else ORDER_MEETING_2PLUS
    ordre_meeting  = [role for role in ordre_officiel if role in roles_present]

    if not ordre_meeting:
        return

    turn_order = [roles_present[role].id for role in ordre_meeting]

    party.turn_order   = json.dumps(turn_order)
    party.current_turn = 0
    party.meeting_phase = "meeting"
    # Reset des flags de victime pour ce nouveau meeting
    for p in players:
        p.victim_of_managers = False
        p.victim_of_claire   = False
    db.commit()

    await broadcast(code, "phase:meeting_start")
    await asyncio.sleep(3)

    # 🔥 On envoie l’ordre complet du meeting au front
    await broadcast(code, "meeting_order:" + ",".join(ordre_meeting))
    
    # 🔥 Pouvoir de Cindy : vérifier si un voisin est manager
    if "Cindy" in ordre_meeting:
        idx = ordre_meeting.index("Cindy")
        left_role  = ordre_meeting[(idx - 1) % len(ordre_meeting)]
        right_role = ordre_meeting[(idx + 1) % len(ordre_meeting)]

        left_player  = roles_present[left_role]
        right_player = roles_present[right_role]

        info = "yes" if left_player.is_manager or right_player.is_manager else "no"

    # Envoyer l’info UNIQUEMENT à Cindy
        from websocket_manager import send_to_player
        await send_to_player(code, roles_present["Cindy"].id, f"cindy_voisin:{'oui' if info == 'yes' else 'non'}")


    first_player = roles_present[ordre_meeting[0]]
    print(f"🎯 Premier joueur : {first_player.role}")
    await broadcast(code, f"role:{first_player.role}")

    # Lancer le timer auto pour le premier tour
    _schedule_turn_timer(code, 0)


def _schedule_turn_timer(code: str, turn_index: int, delay: int = 25):
    """Lance une tâche asyncio qui force l'avance si le joueur ne répond pas."""
    # Annuler l'ancien timer s'il existe
    if code in turn_timers and not turn_timers[code].done():
        turn_timers[code].cancel()

    task = asyncio.create_task(auto_advance_turn(code, turn_index, delay))
    turn_timers[code] = task


# ---------------------------------------------------------
# ROUTE HTTP : passer au tour suivant manuellement (appelée
# par le WebSocket handler après réception d'une action)
# On expose aussi cette route pour les tests.
# ---------------------------------------------------------
@router.post("/next_turn/{code}")
async def http_next_turn(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code.strip()).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    current_index = party.current_turn

    # Annuler le timer auto avant de passer la main
    if code in turn_timers and not turn_timers[code].done():
        turn_timers[code].cancel()

    await next_turn(code, party, db)

    # Si le meeting continue, programmer le timer du prochain tour
    party = db.query(Party).filter(Party.code == code).first()
    if party and party.meeting_phase == "meeting":
        _schedule_turn_timer(code, party.current_turn)

    return {"message": "Tour suivant"}


# ---------------------------------------------------------
# ROUTE : passer en phase VOTE ou DÉFI après le feedback
# Appelée par feedback.html quand le host clique "Passer au vote"
# ---------------------------------------------------------
@router.post("/phase/vote/{code}")
async def set_phase_vote(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code.strip()).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    # Y a-t-il une victime restante du meeting (managers ou claire) ?
    victim = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True
    ).filter(
        (Player.victim_of_managers == True) | (Player.victim_of_claire == True)
    ).first()

    if victim:
        party.last_eliminated_id = victim.id
        party.meeting_phase      = "feedback_defi"
        party.defi_sub_phase     = "decision"
        db.commit()
        print(f"⚠️ Victime du meeting vers défi : {victim.pseudo}")
        await broadcast(code, "phase:defi_decision")
        return {"message": f"Victime {victim.pseudo} → défi", "has_victim": True}

    # Pas de victime → vote global
    party.meeting_phase  = "vote"
    party.defi_sub_phase = None
    db.commit()
    await broadcast(code, "phase:vote")
    return {"message": "Phase vote déclenchée", "has_victim": False}


# ---------------------------------------------------------
# ROUTE : récupérer la victime du meeting
# ---------------------------------------------------------
@router.get("/victim/{code}")
def get_meeting_victim(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code.strip()).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    if party.last_eliminated_id:
        victim = db.query(Player).filter(Player.id == party.last_eliminated_id).first()
        if victim:
            return {
                "victim": {
                    "id":       victim.id,
                    "player_id": victim.id,
                    "pseudo":   victim.pseudo,
                    "role":     victim.role
                }
            }

    return {"victim": None}