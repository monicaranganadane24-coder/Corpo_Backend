import json
import asyncio
from database.connection import SessionLocal
from models.partyModel import Party
from models.playerModel import Player

# Structure : { "CODE": { player_id_int: websocket_obj } }
connections = {}


# ---------------------------------------------------------
# Broadcast avec nettoyage des WS morts
# ---------------------------------------------------------
async def broadcast(code: str, message: str):
    if code not in connections:
        print(f"⚠️ Broadcast ignoré : room {code} inexistante")
        return
    dead = []
    for player_id, ws in list(connections[code].items()):
        try:
            await ws.send_text(message)
        except:
            dead.append(player_id)
    for pid in dead:
        connections[code].pop(pid, None)
    print(f"📢 Broadcast [{code}] → '{message}' ({len(connections[code])} clients)")


# ---------------------------------------------------------
# Envoi privé à un seul joueur
# ---------------------------------------------------------
async def send_to_player(code: str, player_id: int, message: str):
    if code in connections and player_id in connections[code]:
        try:
            await connections[code][player_id].send_text(message)
        except:
            connections[code].pop(player_id, None)


# ---------------------------------------------------------
# Déconnexion
# ---------------------------------------------------------
async def disconnect(code: str, websocket):
    if code in connections:
        to_remove = [pid for pid, ws in connections[code].items() if ws == websocket]
        for pid in to_remove:
            connections[code].pop(pid, None)
    print(f"❌ Déconnexion room {code} → {len(connections.get(code, {}))} clients restants")


# ---------------------------------------------------------
# Notifier début de partie
# ---------------------------------------------------------
async def notify_party_start(code: str):
    await broadcast(code, "start")


# ---------------------------------------------------------
# Passer au joueur suivant (ou terminer le meeting)
# ---------------------------------------------------------
async def next_turn(code: str, party, db):
    turn_order = json.loads(party.turn_order or "[]")
    current = party.current_turn

    next_index = current + 1
    while next_index < len(turn_order):
        p = db.query(Player).filter(Player.id == turn_order[next_index]).first()
        if p and p.is_alive:
            break
        next_index += 1

    if next_index < len(turn_order):
        party.current_turn = next_index
        db.commit()
        next_player = db.query(Player).filter(Player.id == turn_order[next_index]).first()
        print(f"➡️ Prochain joueur : {next_player.role}")
        await broadcast(code, f"role:{next_player.role}")
    else:
        # Fin du meeting
        victim = db.query(Player).filter(
            Player.party_id == party.id,
            Player.is_alive == True
        ).filter(
            (Player.victim_of_managers == True) | (Player.victim_of_claire == True)
        ).first()

        if victim:
            party.last_eliminated_id = victim.id
            party.meeting_phase = "defi"
            victim.is_alive = False
            victim.victim_of_managers = False
            victim.victim_of_claire = False
            db.commit()
            print(f"⚠️ Victime du meeting : {victim.pseudo} ({victim.role})")
            await broadcast(code, f"meeting_victim:{victim.id}:{victim.pseudo}:{victim.role}")
        else:
            party.meeting_phase = "feedback"
            party.current_turn = 0
            db.commit()
            print(f"🔄 Phase feedback pour {code}")
            await broadcast(code, "phase:feedback")


# ---------------------------------------------------------
# Gestion des messages entrants WebSocket
# ---------------------------------------------------------
async def handle_message(code: str, websocket, message: str):
    try:
        data = json.loads(message)
    except:
        return

    msg_type = data.get("type")
    print(f"📨 [{code}] type={msg_type}")

    # CLIENT PRÊT
    if msg_type == "ready":
        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if not party:
                return
            if party.meeting_phase == "meeting" and party.turn_order:
                turn_order = json.loads(party.turn_order)
                current_player = db.query(Player).filter(
                    Player.id == turn_order[party.current_turn]
                ).first()
                if current_player:
                    await websocket.send_text("phase:meeting_start")
                    await websocket.send_text(f"role:{current_player.role}")
            elif party.meeting_phase == "feedback":
                await websocket.send_text("phase:feedback")
            elif party.meeting_phase == "vote":
                await websocket.send_text("phase:vote")
        finally:
            db.close()
        return

    # ACTION
    if msg_type == "action":
        action    = data.get("action")
        player_id = int(data.get("playerId", 0))
        target_id = data.get("target_id")

        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if not party or not party.turn_order:
                return

            if action == "manager_victim" and target_id:
                db.query(Player).filter(Player.party_id == party.id).update({"victim_of_managers": False})
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    target.victim_of_managers = True
                    db.commit()

            elif action == "claire_save":
                claire = db.query(Player).filter(Player.id == player_id).first()
                if claire and not claire.has_used_power:
                    db.query(Player).filter(Player.party_id == party.id, Player.victim_of_managers == True).update({"victim_of_managers": False})
                    claire.has_used_power = True
                    db.commit()

            elif action == "claire_fire" and target_id:
                claire = db.query(Player).filter(Player.id == player_id).first()
                if claire and not claire.has_used_power:
                    db.query(Player).filter(Player.party_id == party.id, Player.victim_of_managers == True).update({"victim_of_managers": False})
                    target = db.query(Player).filter(Player.id == int(target_id)).first()
                    if target:
                        target.victim_of_claire = True
                    claire.has_used_power = True
                    db.commit()

            elif action == "pascal_inspect" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    result = "true" if target.is_manager else "false"
                    try:
                        await websocket.send_text(f"pascal_result:{result}:{target.pseudo}")
                    except:
                        pass
                # Pascal envoie "done" ensuite
                return

            elif action == "stephane_reveal" and target_id:
                stephane = db.query(Player).filter(Player.id == player_id).first()
                target   = db.query(Player).filter(Player.id == int(target_id)).first()
                if stephane and target:
                    try:
                        await websocket.send_text(f"stephane_result:{target.role}:{target.pseudo}")
                    except:
                        pass
                    await send_to_player(code, int(target_id), f"stephane_reveal_target:{stephane.role}:{stephane.pseudo}")
                    if target.role == "Claire":
                        stephane.is_alive = False
                        db.commit()
                        await broadcast(code, f"player_fired:{stephane.pseudo}")
                # Stéphane envoie "done" ensuite
                return

            elif action == "plante_water" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    await broadcast(code, f"plante_arroseur:{target.pseudo}")

            elif action == "denis_swap" and target_id:
                denis  = db.query(Player).filter(Player.id == player_id).first()
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if denis and target:
                    denis.role, target.role             = target.role, denis.role
                    denis.is_manager, target.is_manager = target.is_manager, denis.is_manager
                    db.commit()
                    await send_to_player(code, player_id,      f"new_role:{denis.role}")
                    await send_to_player(code, int(target_id), f"new_role:{target.role}")

            elif action == "corentin_swap" and target_id:
                corentin    = db.query(Player).filter(Player.id == player_id).first()
                dead_player = db.query(Player).filter(Player.id == int(target_id)).first()
                if corentin and dead_player:
                    corentin.role       = dead_player.role
                    corentin.is_manager = dead_player.is_manager
                    db.commit()
                    try:
                        await websocket.send_text(f"new_role:{corentin.role}")
                    except:
                        pass

            elif action == "abdel_virus" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    target.virus_from_abdel = True
                    db.commit()

            await next_turn(code, party, db)
        finally:
            db.close()
        return

    # CHAT
    if msg_type == "chat":
        pseudo       = data.get("pseudo", "?")
        message_text = data.get("message", "").strip()
        if not message_text:
            return

        MOTS_INTERDITS = [
            "putain", "merde", "connard", "connasse", "salope", "enculé",
            "enculer", "encule", "fils de pute", "fdp", "pute", "bâtard",
            "batard", "nique", "niquer", "bite", "couille", "bordel",
            "fuck", "shit", "bitch", "asshole", "bastard", "cunt",
            "motherfucker", "abruti", "imbécile", "imbecile", "crétin",
            "cretin", "débile", "debile", "ntr"
        ]
        texte_lower = message_text.lower()
        for mot in MOTS_INTERDITS:
            if mot in texte_lower:
                db = SessionLocal()
                try:
                    player = db.query(Player).filter(Player.pseudo == pseudo).first()
                    if player and code in connections and player.id in connections[code]:
                        await connections[code][player.id].send_text(
                            "chat_warning:⚠️ Message bloqué : mot interdit détecté."
                        )
                finally:
                    db.close()
                return

        # Vérifier mots Tiffany
        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if party and party.tiff_mots_actifs:
                mots_actifs = json.loads(party.tiff_mots_actifs or "[]")
                mot_trouve = next((m for m in mots_actifs if m.lower() in texte_lower), None)
                if mot_trouve:
                    coupable = db.query(Player).filter(Player.pseudo == pseudo).first()
                    if coupable and coupable.is_alive:
                        await broadcast(code, f"chat:{pseudo} : {message_text}")
                        await broadcast(code, f"mot_interdit:{pseudo}:{mot_trouve}")
                        if not coupable.has_drawn_corpocard:
                            coupable.victim_of_managers = True
                            party.last_eliminated_id = coupable.id
                            party.meeting_phase = "vote_defi"
                            party.defi_sub_phase = "running_from_vote"
                            party.turn_order = json.dumps([coupable.id])
                            party.current_turn = 0
                            db.commit()
                            await asyncio.sleep(2)
                            await broadcast(code, "phase:defi_decision")
                        else:
                            coupable.is_alive = False
                            db.commit()
                            await broadcast(code, f"player_eliminated_direct:{coupable.pseudo}:{coupable.role}")
                            alive = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
                            if not [p for p in alive if p.is_manager]:
                                await broadcast(code, "game_over:victoire_collabs")
                            elif not [p for p in alive if not p.is_manager]:
                                await broadcast(code, "game_over:victoire_managers")
                    return
        finally:
            db.close()

        await broadcast(code, f"chat:{pseudo} : {message_text}")
        return

    # DEFI DONE → tout le monde vers resultat_defi
    if msg_type == "defi_done":
        print(f"🎯 DÉFI DONE room {code}")
        await broadcast(code, "defi_done")
        return

    # GO FEEDBACK
    if msg_type == "go_feedback":
        await broadcast(code, "go_feedback")
        return

    # GO SALLE MORTS
    if msg_type == "go_salle_morts":
        await broadcast(code, "go_salle_morts")
        return

    # GO DÉFI
    if msg_type == "go_defi":
        await broadcast(code, "go_defi")
        return