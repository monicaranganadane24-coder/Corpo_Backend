import json
import asyncio
from database.connection import SessionLocal
from models.partyModel import Party
from models.playerModel import Player

# Structure : { "CODE": { player_id_int: websocket_obj } }
connections = {}

# Timers auto par room : { "CODE": asyncio.Task }
turn_timers = {}

TURN_TIMEOUT = 25  # secondes avant forçage auto


# ---------------------------------------------------------
# Broadcast avec nettoyage des WS morts
# ---------------------------------------------------------
async def broadcast(code: str, message: str):
    if code not in connections:
        return
    dead = []
    for player_id, ws in list(connections[code].items()):
        try:
            await ws.send_text(message)
        except:
            dead.append(player_id)
    for pid in dead:
        connections[code].pop(pid, None)
    print(f"📢 [{code}] → '{message}' ({len(connections[code])} clients)")


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


# ---------------------------------------------------------
# Notifier début de partie
# ---------------------------------------------------------
async def notify_party_start(code: str):
    await broadcast(code, "start")


# ---------------------------------------------------------
# Timer auto : si le joueur ne répond pas dans TURN_TIMEOUT s
# → on force le passage au tour suivant
# ---------------------------------------------------------
def schedule_turn_timer(code: str, expected_turn: int):
    """Lance un timer asyncio qui force next_turn si le joueur ne répond pas."""
    if code in turn_timers and not turn_timers[code].done():
        turn_timers[code].cancel()
    task = asyncio.create_task(_auto_advance(code, expected_turn))
    turn_timers[code] = task


async def _auto_advance(code: str, expected_turn: int):
    await asyncio.sleep(TURN_TIMEOUT)
    db = SessionLocal()
    try:
        party = db.query(Party).filter(Party.code == code).first()
        if not party or party.meeting_phase != "meeting":
            return
        if party.current_turn == expected_turn:
            print(f"⏱️ Timeout tour {expected_turn} room {code} → forçage")
            await next_turn(code, party, db)
    finally:
        db.close()


# ---------------------------------------------------------
# Passer au joueur suivant (ou terminer le meeting)
# ---------------------------------------------------------
async def next_turn(code: str, party, db):
    """Avance au prochain joueur vivant ou termine le meeting."""

    # Annuler le timer en cours
    if code in turn_timers and not turn_timers[code].done():
        turn_timers[code].cancel()

    turn_order = json.loads(party.turn_order or "[]")
    current    = party.current_turn

    # Chercher le prochain joueur vivant
    next_index = current + 1
    while next_index < len(turn_order):
        p = db.query(Player).filter(Player.id == turn_order[next_index]).first()
        if p and p.is_alive:
            break
        next_index += 1

    if next_index < len(turn_order):
        # Il reste des joueurs → avancer
        party.current_turn = next_index
        db.commit()
        next_player = db.query(Player).filter(Player.id == turn_order[next_index]).first()
        print(f"➡️ Prochain tour : {next_player.role}")
        await broadcast(code, f"role:{next_player.role}")
        # Programmer le timer pour ce nouveau tour
        schedule_turn_timer(code, next_index)
    else:
        # Meeting terminé → chercher une victime
        print(f"🏢 Fin du meeting room {code}")
        _end_meeting(code, party, db)


def _end_meeting(code: str, party, db):
    """Détermine s'il y a une victime et route vers la bonne phase (via tâche asyncio)."""
    asyncio.create_task(_end_meeting_async(code, party.id))


async def _end_meeting_async(code: str, party_id: int):
    db = SessionLocal()
    try:
        party = db.query(Party).filter(Party.id == party_id).first()
        if not party:
            return

        # Priorité Claire > Managers
        victim = db.query(Player).filter(
            Player.party_id == party_id,
            Player.victim_of_claire == True,
            Player.is_alive == True
        ).first()
        if not victim:
            victim = db.query(Player).filter(
                Player.party_id == party_id,
                Player.victim_of_managers == True,
                Player.is_alive == True
            ).first()

        if victim:
            # Chercher toutes les victimes du meeting
            all_victims = db.query(Player).filter(
                Player.party_id == party_id,
                Player.is_alive == True
            ).filter(
                (Player.victim_of_managers == True) | (Player.victim_of_claire == True)
            ).all()

            import json as _json

            # 🔥 Séparer : joker dispo vs joker déjà utilisé
            victims_with_joker    = [v for v in all_victims if not v.has_drawn_corpocard]
            victims_without_joker = [v for v in all_victims if v.has_drawn_corpocard]

            # Éliminer directement ceux sans joker
            for v in victims_without_joker:
                v.is_alive = False
                print(f"⛔ {v.pseudo} éliminé directement (joker déjà utilisé)")
            db.commit()

            if victims_without_joker:
                for v in victims_without_joker:
                    await broadcast(code, f"player_eliminated_direct:{v.pseudo}:{v.role}")
                await asyncio.sleep(2)

            # Vérif fin de partie après éliminations directes
            alive_check = db.query(Player).filter(
                Player.party_id == party_id, Player.is_alive == True
            ).all()
            if not [p for p in alive_check if p.is_manager]:
                await broadcast(code, "game_over:victoire_collabs")
                return
            if not [p for p in alive_check if not p.is_manager]:
                await broadcast(code, "game_over:victoire_managers")
                return

            if victims_with_joker:
                # Victimes avec joker → défi à tour de rôle
                victim_ids = [v.id for v in victims_with_joker]
                party.last_eliminated_id = victim_ids[0]
                party.meeting_phase      = "feedback_defi"
                party.defi_sub_phase     = "running_from_meeting"
                party.turn_order         = _json.dumps(victim_ids)
                party.current_turn       = 0
                db.commit()
                print(f"🚨 Victimes avec joker : {[v.pseudo for v in victims_with_joker]}")
                await broadcast(code, "phase:defi_decision")
            else:
                # Toutes éliminées directement → feedback
                party.meeting_phase      = "feedback"
                party.last_eliminated_id = None
                party.defi_sub_phase     = None
                party.turn_order         = None
                party.current_turn       = 0
                db.commit()
                print("🟢 Toutes victimes éliminées directement → feedback")
                await broadcast(code, "phase:feedback:pre_vote")
        else:
            party.meeting_phase      = "feedback"
            party.last_eliminated_id = None
            party.current_turn       = 0
            db.commit()
            print("🟢 Pas de victime → feedback direct")
            await broadcast(code, "phase:feedback:pre_vote")
    finally:
        db.close()


# ---------------------------------------------------------
# Gestion des messages entrants WebSocket
# ---------------------------------------------------------

async def _launch_next_meeting_ws(code: str, party_id: int):
    """Lance le meeting suivant depuis websocket_manager (sans session DB active)."""
    import json as _json
    db = SessionLocal()
    try:
        party = db.query(Party).filter(Party.id == party_id).first()
        if not party:
            return
        party.meeting_number += 1
        party.meeting_phase   = "waiting"
        party.defi_sub_phase  = None
        party.turn_order      = None
        party.current_turn    = 0
        party.last_eliminated_id = None
        db.query(Player).filter(Player.party_id == party_id).update({
            "victim_of_managers": False,
            "victim_of_claire":   False
        })
        db.commit()
        await broadcast(code, f"next_meeting:{party.meeting_number}")
        await asyncio.sleep(4)

        from routes.meetingRoutes import start_meeting as _start
        db2 = SessionLocal()
        try:
            await _start(code, db2)
        finally:
            db2.close()
    finally:
        db.close()


async def handle_message(code: str, websocket, message: str):
    try:
        data = json.loads(message)
    except:
        return

    msg_type = data.get("type")

    # ---------------------------------------------------------
    # CLIENT PRÊT → renvoyer l'état actuel de la phase
    # ---------------------------------------------------------
    if msg_type == "ready":
        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if not party:
                return
            phase = party.meeting_phase

            if phase == "meeting" and party.turn_order:
                turn_order   = json.loads(party.turn_order)
                current_player = db.query(Player).filter(
                    Player.id == turn_order[party.current_turn]
                ).first()
                if current_player:
                    await websocket.send_text("phase:meeting_start")
                    await websocket.send_text(f"role:{current_player.role}")

            elif phase in ("feedback_defi",):
                await websocket.send_text("phase:defi_decision")
            elif phase == "defi_corpo":
                await websocket.send_text("phase:defi_corpo")
            elif phase == "feedback":
                await websocket.send_text("phase:feedback")
            elif phase == "vote":
                await websocket.send_text("phase:vote")
        finally:
            db.close()
        return

    # ---------------------------------------------------------
    # ACTION d'un joueur pendant son tour
    # ---------------------------------------------------------
    if msg_type == "action":
        action    = data.get("action")
        player_id = int(data.get("playerId", 0))
        role      = data.get("role", "")
        target_id = data.get("target_id")

        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if not party or not party.turn_order:
                return

            # Vérifier que c'est bien le tour de ce joueur
            turn_order = json.loads(party.turn_order)
            if party.current_turn < len(turn_order):
                expected_id = turn_order[party.current_turn]
                if int(player_id) != int(expected_id):
                    print(f"⚠️ Action ignorée : pas le tour de {player_id} (attendu: {expected_id})")
                    return

            print(f"🎯 ACTION: {action} | joueur {player_id} ({role}) → cible {target_id}")

            # --- FABIEN : victime des managers ---
            if action == "manager_victim" and target_id:
                db.query(Player).filter(Player.party_id == party.id).update({
                    "victim_of_managers": False
                })
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    target.victim_of_managers = True
                    db.commit()
                    print(f"💀 Victime managers : {target.pseudo}")

            # --- CLAIRE : sauver ---
            elif action == "claire_save":
                claire = db.query(Player).filter(Player.id == player_id).first()
                if claire and not claire.has_used_power:
                    db.query(Player).filter(
                        Player.party_id == party.id,
                        Player.victim_of_managers == True
                    ).update({"victim_of_managers": False})
                    claire.has_used_power = True
                    db.commit()
                    print("💚 Claire a sauvé la victime")

            # --- CLAIRE : licencier quelqu'un ---
            elif action == "claire_fire" and target_id:
                claire = db.query(Player).filter(Player.id == player_id).first()
                if claire and not claire.has_used_power:
                    db.query(Player).filter(
                        Player.party_id == party.id,
                        Player.victim_of_managers == True
                    ).update({"victim_of_managers": False})
                    target = db.query(Player).filter(Player.id == int(target_id)).first()
                    if target:
                        target.victim_of_claire = True
                    claire.has_used_power = True
                    db.commit()
                    print(f"🔴 Claire licencie : {target.pseudo if target else '?'}")

            # --- PASCAL : inspecter ---
            # next_turn est appelé quand Pascal envoie "done" après l'alerte
            elif action == "pascal_inspect" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    result = "true" if target.is_manager else "false"
                    try:
                        await websocket.send_text(f"pascal_result:{result}:{target.pseudo}")
                    except:
                        pass
                # ⚠️ Pas de next_turn ici — Pascal envoie "done" après l'alerte
                return

            # --- STÉPHANE : révélation mutuelle ---
            # next_turn est appelé quand Stéphane envoie "done" après l'alerte
            elif action == "stephane_reveal" and target_id:
                stephane = db.query(Player).filter(Player.id == player_id).first()
                target   = db.query(Player).filter(Player.id == int(target_id)).first()
                if stephane and target:
                    try:
                        await websocket.send_text(f"stephane_result:{target.role}:{target.pseudo}")
                    except:
                        pass
                    await send_to_player(code, int(target_id),
                        f"stephane_reveal_target:{stephane.role}:{stephane.pseudo}")
                    if target.role == "Claire":
                        stephane.is_alive = False
                        db.commit()
                        await broadcast(code, f"player_fired:{stephane.pseudo}")
                # ⚠️ Pas de next_turn ici — Stéphane envoie "done" après l'alerte
                return

            # --- LA PLANTE : arroseur ---
            elif action == "plante_water" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    await broadcast(code, f"plante_arroseur:{target.pseudo}")

            # --- DENIS : échange d'identité ---
            elif action == "denis_swap" and target_id:
                denis  = db.query(Player).filter(Player.id == player_id).first()
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if denis and target:
                    denis.role, target.role             = target.role, denis.role
                    denis.is_manager, target.is_manager = target.is_manager, denis.is_manager
                    db.commit()
                    await send_to_player(code, player_id,     f"new_role:{denis.role}")
                    await send_to_player(code, int(target_id), f"new_role:{target.role}")

            # --- CORENTIN : récupérer le rôle d'un éliminé ---
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

            # --- ABDEL : contaminer ---
            elif action == "abdel_virus" and target_id:
                target = db.query(Player).filter(Player.id == int(target_id)).first()
                if target:
                    target.virus_from_abdel = True
                    db.commit()

            # Tous les cas (dont "done") → passer au tour suivant
            await next_turn(code, party, db)

        finally:
            db.close()
        return

    # ---------------------------------------------------------
    # DÉCISION DU DÉFI (depuis feedback_defi.html)
    # ---------------------------------------------------------
    if msg_type == "defi_decision":
        player_id = int(data.get("player_id", 0))
        accepted  = data.get("accepted", True)

        db = SessionLocal()
        try:
            party = db.query(Party).filter(Party.code == code).first()
            if not party:
                return

            if accepted:
                # 🔥 On mémorise l'origine dans defi_sub_phase avant d'écraser meeting_phase
                # "running_from_vote" = défi venant du vote → après : next_meeting
                # "running_from_meeting" = défi venant du meeting → après : feedback
                origine = "running_from_vote" if party.meeting_phase == "vote_defi" else "running_from_meeting"
                party.meeting_phase  = "defi_corpo"
                party.defi_sub_phase = origine
                db.commit()
                await broadcast(code, "phase:defi_corpo")
            else:
                # Refus → éliminer directement
                victim = db.query(Player).filter(Player.id == player_id).first()
                if victim:
                    victim.is_alive              = False
                    victim.victim_of_managers    = False
                    victim.victim_of_claire      = False
                    victim.has_drawn_corpocard   = True
                    db.commit()

                # Vérif fin de partie
                alive = db.query(Player).filter(
                    Player.party_id == party.id,
                    Player.is_alive == True
                ).all()
                managers = [p for p in alive if p.is_manager]
                collabs  = [p for p in alive if not p.is_manager]

                if not managers:
                    await broadcast(code, "game_over:victoire_collabs")
                    return
                if not collabs:
                    await broadcast(code, "game_over:victoire_managers")
                    return

                # Pas de fin → feedback
                # Lire l'origine avant de modifier
                came_from_vote = party.defi_sub_phase == "running_from_vote"
                party.defi_sub_phase = None

                if came_from_vote:
                    party.meeting_phase = "vote_defi"
                    db.commit()
                    await _launch_next_meeting_ws(code, party.id)
                else:
                    party.meeting_phase = "feedback"
                    db.commit()
                    await broadcast(code, "phase:feedback:pre_vote")
        finally:
            db.close()
        return

    # ---------------------------------------------------------
    # CHAT avec filtre de mots vulgaires
    # ---------------------------------------------------------
    if msg_type == "chat":
        pseudo  = data.get("pseudo", "?")
        texte   = data.get("message", "").strip()

        if not texte:
            return

        # Liste de mots interdits (insensible à la casse)
        MOTS_INTERDITS = [
            "putain", "merde", "connard", "connasse", "salope", "enculé",
            "enculer", "encule", "fils de pute", "fdp", "pute", "bâtard",
            "batard", "pd", "nique", "niquer", "ta gueule", "tg", "con",
            "conne", "bite", "couille", "couilles", "chier", "chieur",
            "bordel", "ostie", "câlice", "crisse", "tabarnak", "viarge",
            "fuck", "shit", "bitch", "asshole", "bastard", "cunt",
            "motherfucker", "damn", "idiot", "idiot", "abruti", "imbécile",
            "imbecile", "crétin", "cretin", "débile", "debile"
        ]

        texte_lower = texte.lower()
        mot_trouve  = None
        for mot in MOTS_INTERDITS:
            if mot in texte_lower:
                mot_trouve = mot
                break

        if mot_trouve:
            # Prévenir uniquement l'expéditeur
            try:
                # Trouver le player_id de l'expéditeur
                db = SessionLocal()
                player = db.query(Player).filter(Player.pseudo == pseudo).first()
                if player and code in connections and player.id in connections[code]:
                    await connections[code][player.id].send_text(
                        f"chat_warning:⚠️ Message bloqué : mot interdit détecté."
                    )
                db.close()
            except:
                pass
            return

        # 🔥 Vérifier les mots interdits de Tiffany
        db_tiff = SessionLocal()
        try:
            party_tiff = db_tiff.query(Party).filter(Party.code == code).first()
            if party_tiff and party_tiff.tiff_mots_actifs:
                import json as _json
                mots_actifs = _json.loads(party_tiff.tiff_mots_actifs or "[]")
                texte_lower = texte.lower()
                mot_interdit_trouve = None
                for mot in mots_actifs:
                    if mot.lower() in texte_lower:
                        mot_interdit_trouve = mot
                        break

                if mot_interdit_trouve:
                    # Trouver le joueur qui a envoyé ce message
                    coupable = db_tiff.query(Player).filter(Player.pseudo == pseudo).first()
                    if coupable and coupable.is_alive:
                        print(f"🚫 {pseudo} a dit le mot interdit '{mot_interdit_trouve}' → licencié !")
                        await broadcast(code, f"chat:{pseudo} : {texte}")  # Afficher quand même le message

                        if not coupable.has_drawn_corpocard:
                            # A encore son joker → défi, puis RETOUR au feedback
                            coupable.victim_of_managers = True
                            party_tiff.last_eliminated_id = coupable.id
                            party_tiff.meeting_phase = "vote_defi"
                            party_tiff.defi_sub_phase = "running_from_meeting"  # 🔥 feedback après, pas meeting suivant
                            party_tiff.turn_order = _json.dumps([coupable.id])
                            party_tiff.current_turn = 0
                            db_tiff.commit()
                            await broadcast(code, f"mot_interdit:{pseudo}:{mot_interdit_trouve}")
                            await asyncio.sleep(2)
                            await broadcast(code, "phase:defi_decision")
                        else:
                            # Joker déjà utilisé → élimination directe
                            coupable.is_alive = False
                            db_tiff.commit()
                            await broadcast(code, f"player_eliminated_direct:{coupable.pseudo}:{coupable.role}")

                            # Vérif fin de partie
                            alive = db_tiff.query(Player).filter(
                                Player.party_id == party_tiff.id, Player.is_alive == True
                            ).all()
                            if not [p for p in alive if p.is_manager]:
                                await broadcast(code, "game_over:victoire_collabs")
                            elif not [p for p in alive if not p.is_manager]:
                                await broadcast(code, "game_over:victoire_managers")
                        db_tiff.close()
                        return
        finally:
            try: db_tiff.close()
            except: pass

        await broadcast(code, f"chat:{pseudo} : {texte}")
        return