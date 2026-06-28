from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database.connection import get_db, SessionLocal
from models.playerModel import Player
from models.partyModel import Party
from utils.generatePartyCode import generate_party_code
from routes.meetingRoutes import start_meeting
from websocket_manager import notify_party_start, broadcast

from datetime import datetime, timedelta
import random
import asyncio
import json

router = APIRouter(prefix="/party", tags=["Party"])

def cleanup_parties(db: Session):
    limit = datetime.utcnow() - timedelta(minutes=5)

    parties = db.query(Party).all()

    for party in parties:
        players_count = db.query(Player).filter(
            Player.party_id == party.id
        ).count()

        if players_count == 0:
            db.delete(party)
            continue

        if party.last_activity and party.last_activity < limit:
            db.query(Player).filter(
                Player.party_id == party.id
            ).update({"party_id": None})

            db.delete(party)

    db.commit()

ALL_ROLES = [
    {
        "name": "Fabien", "title": "Manager Toxique", "team": "Managers", "image": "Fabien.png",
        "description": "Il micro-manage tout le monde en parlant de 'quick wins' et de 'croissance organique'. Quand il te félicite pour ton potentiel, tu sais que c'est ton potentiel de départ.",
        "role_meeting": "Pendant le meeting, tous les Managers ouvrent les yeux, se concertent et désignent secrètement un collaborateur à licencier.",
        "cliches": ["On priorise les quick wins !", "Il faut rester agile !", "Réalignons les ressources stratégiques.", "C'est dans notre roadmap.", "On est en mode pivot."]
    },
    {
        "name": "Claire", "title": "Responsable RH", "team": "Collaborateurs", "image": "Claire.png",
        "description": "Elle ADOOOOOOOORE l'humain mais c'est la reine des hypocrites. Quand elle dit 'On est là pour t'accompagner', ta lettre de licenciement est déjà prête.",
        "role_meeting": "Tu peux sauver la victime des Managers ou en désigner une autre. Tu ne peux utiliser ce pouvoir qu'UNE seule fois dans toute la partie.",
        "cliches": ["On va co-construire ensemble !", "Empower Human to bridge the gap.", "Je suis là pour toi.", "On a une politique de bienveillance.", "Le sondage anonyme était vraiment anonyme."]
    },

    {
        "name": "Pascal", "title": "Futur Retraité", "team": "Collaborateurs", "image": "Pascal.png",
        "description": "Il part à la retraite dans 2 ans et il est invirable. Il a fait toute sa carrière chez Corpo! et une chose est sûre : 'c'était mieux avant'.",
        "role_meeting": "Tu désignes un joueur. Le CHO t'indique si c'est un Manager ou non. Si c'est un Manager, tu peux en désigner un second (2 max par tour).",
        "cliches": ["C'était mieux avant.", "Moi j'ai connu l'époque où...", "Plus que 2 ans et je suis libre !", "De mon temps on faisait pas ça.", "J'ai vu des DG partir, j'en verrai d'autres."]
    },
    {
        "name": "Tiff", "title": "Responsable Marketing", "team": "Collaborateurs", "image": "Tiff.png",
        "description": "Elle parle de TikTok et Instagram mais ses idées finissent en posts LinkedIn gênants. 10 secondes après son post, tu reçois : 'Hello, tu peux liker stp ? :-)'",
        "role_meeting": "Tu choisis 3 mots parmi 5 proposés. Si quelqu'un prononce ces mots dans le chat du feedback, il est licencié !",
        "cliches": ["Tu peux liker mon post stp ? :-)", "On va faire un contenu viral !", "J'ai une idée disruptive pour les réseaux.", "Le reach organique c'est mort.", "On fait du storytelling authentique."]
    },
    {
        "name": "Stéphane", "title": "Commercial", "team": "Collaborateurs", "image": "Stephane.png",
        "description": "Toujours avec sa sacoche, il ne parle que de 'closer des deals'. Il improvise tout mais fait semblant de tout maîtriser.",
        "role_meeting": "Tu désignes un joueur et vous révélez mutuellement vos identités. Attention : si tu tombes sur Claire la RH, tu es licencié !",
        "cliches": ["On va closer ce deal !", "T'as mon numéro, appelle-moi.", "J'ai un afterwork ce soir, vous venez ?", "Mon variable cette année c'est du lourd.", "Je suis en mode chasseur."]
    },
    {
        "name": "Cindy", "title": "Secrétaire", "team": "Collaborateurs", "image": "Cindy.png",
        "description": "Plus ancienne que ta dernière version Word. Elle t'envoie un mail 'Avec la pièce jointe c'est mieux :-)))'. Toujours sans la pièce jointe.",
        "role_meeting": "Le CHO t'indique si l'un de tes voisins gauche/droite est Manager (sans dire lequel). Tu peux utiliser cette info pour orienter les votes.",
        "cliches": ["Comme convenu, voici la pièce jointe.", "J'ai booké la salle de réunion !", "Tu peux valider mon compte-rendu stp ?", "J'ai transféré ton mail au bon service.", "Des fois je suis un peu fofolle !"]
    },
    {
        "name": "Denis", "title": "Comptable", "team": "Collaborateurs", "image": "Denis.png",
        "description": "Discret, poli, avec un sourire énigmatique qui cache peut-être un million détourné. Il maîtrise tous les raccourcis Excel et verrouille tous ses dossiers.",
        "role_meeting": "Tu peux échanger ton identité avec un autre joueur. Vous découvrez vos nouveaux rôles en secret.",
        "cliches": ["C'est dans le budget.", "J'ai verrouillé le fichier Excel.", "Les chiffres ne mentent pas.", "Il y a des ajustements à prévoir.", "Toujours plus de CA, moins de croissance."]
    },

    {
        "name": "Abdel", "title": "Support IT", "team": "Collaborateurs", "image": "Abdel.png",
        "description": "La colonne vertébrale invisible de l'entreprise. Il règle tout avec un calme olympien. Mais t'as ouvert un ticket avant de venir le voir ?",
        "role_meeting": "À chaque meeting tu contamines secrètement un joueur avec un virus cyber. Quand tu es éliminé, tous les infectés sont licenciés instantanément !",
        "cliches": ["T'as ouvert un ticket ?", "J'ai lancé la campagne anti-phishing.", "Redémarre et rappelle-moi.", "C'est pas dans mon scope.", "Les règles sont les règles."]
    },
]

# Tous les mots Tiffany disponibles
TIFF_MOTS_DISPONIBLES = [
    "burn-out", "key take aways", "bullet-point", "autonomie",
    "red flag", "hello ça va ?", "auto-portant", "innovation",
    "bullshit", "prend un post-it", "hiring freeze", "flexoffice",
    "disruptif", "je prends un call", "pause close ?", "heure supp",
    "team work", "comme un lundi", "y a pas de fit", "cooptation",
    "reste agile", "leverager les ke", "share ta prez", "case-study",
    "anti-phishing", "pivot stratégique", "close le deal", "réactivité",
    "récap la réu", "je prends le lead", "je suis fatigué", "pain point",
    "secret santa", "vision long-terme", "ticket restau", "onboarding",
    "t'as 2min ?", "vision long-terme", "team building", "next steps",
    "transparence", "t'as lu mon mail ?", "back to basics", "brainstorm",
    "cash is king", "objectif rentabilité", "best practice", "bon week ?",
    "sois curieux", "revue des objectifs", "t'es sur mute", "home office",
    "pinte ?", "organise ton agenda", "comme tu veux", "laptop",
    "okr", "rse", "inputs", "skills",
    "8to8", "haha", "pnl", "dispo ?",
    "je suis fauché", "les croissants c'eeeest", "pour le stagios", "swot",
    "full remote", "on se fait un point ?", "allume ta cam", "formation",
    "non obstant", "culture d'entreprise", "bienveillance", "y a du tt ?",
    "vision 360°", "feedback constructif", "challengeant", "créativité",
    "big picture", "management toxique", "congé maladie", "synergies",
    "petit café ?", "croissance organique", "quel variable ?", "inclusion",
    "on va déj ?", "t'as posé ton aprem ?", "draft tes idées", "cash burn",
    "baby-foot ?", "sauf erreur de ma part", "sympa ton mug", "collègues",
    "trop junior", "l'ia c'est gamechanger", "manifestement", "benchmark",
    "trop senior", "plan de restructuration", "j'ai un meeting", "incentivé",
    "opportunity", "perspectives d'évolution", "out-of-the-box", "deep dive",
    "la direction", "rapport de performance", "rupture co stppp", "afterwork",
    "updates", "café vanille ou noisette ?", "t'as ton lunch ?", "curiosité",
    "assertif", "besoin d'aide sur des sujets ?", "mobilité interne", "trust-office",
]

    # DÉFIS INDIVIDUELS

CORPO_CARDS = [

    # ══════════════════════════════
    # 80 DÉFIS INDIVIDUELS
    # ══════════════════════════════

    {
        "id": 1, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, pitche ton augmentation salariale.",
        "instructions": "On sait tous que l'augmentation, tu ne l'auras pas. Alors bon courage !",
        "vote_label": "Mérite-t-il/elle une augmentation ?"
    },
    {
        "id": 2, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, donne 5 politiques RSE que tu mettrais en place chez Corpo!",
        "instructions": "Sois convaincant(e) ! La majorité valide ou non.",
        "vote_label": "Les propositions RSE sont-elles convaincantes ?"
    },
    {
        "id": 3, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, cite 10 mots franglais du monde de l'entreprise.",
        "instructions": "Synergies, quick wins, roadmap... t'en as d'autres ? La majorité valide.",
        "vote_label": "A-t-il/elle réussi les 10 mots franglais ?"
    },
    {
        "id": 4, "type": "vote", "timer": 45, "duo": False,
        "text": "Sais-tu ce que signifie 'assertif' ? En 45 secondes, donne une définition.",
        "instructions": "C'est pas juste 'confiant en soi'... ou si ? La majorité valide.",
        "vote_label": "La définition est-elle correcte ?"
    },
    {
        "id": 5, "type": "vote", "timer": 45, "duo": False,
        "text": "Tu arrives en retard au meeting. En 45 secondes, explique ta mésaventure.",
        "instructions": "Trouve la meilleure excuse de l'histoire ! Si la majorité valide, tu restes.",
        "vote_label": "L'excuse est-elle recevable ?"
    },
    {
        "id": 6, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, pitche un post LinkedIn inspirant pour recruter. N'oublie pas les #hashtags !",
        "instructions": "Sois authentique, bienveillant et disruptif à la fois ! La majorité valide.",
        "vote_label": "Ce post mérite-t-il des likes ?"
    },
    {
        "id": 7, "type": "vote", "timer": 45, "duo": False,
        "text": "Sais-tu réellement à quoi sert un Manager ? En 45 secondes, explique.",
        "instructions": "Prends le temps de réfléchir... La majorité valide.",
        "vote_label": "L'explication tient-elle la route ?"
    },
    {
        "id": 8, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, décris comment tu vas résoudre la panne d'imprimante.",
        "instructions": "L'imprimante ne répond plus depuis 3 jours... Si la majorité valide, tu restes.",
        "vote_label": "La solution est-elle crédible ?"
    },
    {
        "id": 9, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, fais un pitch de création de startup innovante.",
        "instructions": "L'appli qui va changer le monde, c'est maintenant ! La majorité valide.",
        "vote_label": "Cette startup mérite-t-elle un financement ?"
    },
    {
        "id": 10, "type": "vote", "timer": 45, "duo": False,
        "text": "Tu as mis une LV3 sur ton CV ? Parle pendant 45 secondes dans cette langue.",
        "instructions": "Espéranto, mandarin, klingon... à toi ! La majorité valide.",
        "vote_label": "La performance linguistique est-elle convaincante ?"
    },
    {
        "id": 11, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, fais une imitation d'une réunion Teams typique qui commence mal.",
        "instructions": "'T'es sur mute !' 'Je vous entends pas...' Go ! La majorité valide.",
        "vote_label": "L'imitation est-elle réussie ?"
    },
    {
        "id": 12, "type": "vote", "timer": 45, "duo": True,
        "text": "Tu as 45 secondes. Convaincs l'entreprise de t'accorder une augmentation en 3 arguments maximum.",
        "instructions": "Sois percutant et droit au but ! Si la majorité valide → tu restes !",
        "vote_label": "Les arguments méritent-ils une augmentation ?"
    },
    {
        "id": 13, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, cite 2 citations inspirantes.",
        "instructions": "Nelson Mandela, Gandhi, ou LinkedIn ? La majorité valide.",
        "vote_label": "Les citations sont-elles convaincantes ?"
    },
    {
        "id": 14, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, cite 3 défauts de l'entreprise.",
        "instructions": "Des défauts constructifs hein, pas juste 'la machine à café est nulle'... La majorité valide.",
        "vote_label": "Les défauts sont-ils pertinents ?"
    },
    {
        "id": 15, "type": "vote", "timer": 45, "duo": False,
        "text": "En 45 secondes, cite 3 mensonges classiques pour justifier une absence au travail.",
        "instructions": "'J'ai un empêchement familial', 'Je suis malade', 'Ma voiture est en panne'... La majorité valide.",
        "vote_label": "Les mensonges sont-ils convaincants ?"
    },
    {
    "id": 16, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais un pitch pour convaincre ton boss de passer en télétravail 5 jours sur 5.",
    "instructions": "Sois crédible mais ambitieux. La majorité valide.",
    "vote_label": "Le télétravail à 100% est-il justifié ?"
    },
    {
    "id": 17, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, raconte ton pire fail professionnel… sans rougir.",
    "instructions": "Assume ton passé. La majorité valide.",
    "vote_label": "Le fail est-il suffisamment honteux ?"
    },
    {
    "id": 18, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, propose un slogan corporate totalement nul.",
    "instructions": "Plus c’est cringe, mieux c’est. La majorité valide.",
    "vote_label": "Le slogan est-il assez nul ?"
    },
    {
    "id": 19, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais un discours de départ comme si tu quittais l'entreprise.",
    "instructions": "Émotion, drama, larmes… La majorité valide.",
    "vote_label": "Le discours est-il digne d’un pot de départ ?"
    },
    {
    "id": 20, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais une imitation d’un collègue qui parle trop fort en open space.",
    "instructions": "On veut du réalisme. La majorité valide.",
    "vote_label": "L’imitation est-elle fidèle ?"
    },
    {
    "id": 21, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, propose 3 idées absurdes pour améliorer la productivité.",
    "instructions": "Plus c’est absurde, mieux c’est. La majorité valide.",
    "vote_label": "Les idées sont-elles suffisamment absurdes ?"
    },
    {
    "id": 22, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, raconte une anecdote de bureau totalement inventée.",
    "instructions": "Fais croire que c’est vrai. La majorité valide.",
    "vote_label": "L’anecdote est-elle crédible ?"
    },
    {
    "id": 23, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais un pitch pour remplacer le PDG.",
    "instructions": "Ambition maximale. La majorité valide.",
    "vote_label": "Serait-il/elle un bon PDG ?"
    },
    {
    "id": 24, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, explique pourquoi tu serais un excellent influenceur LinkedIn.",
    "instructions": "Buzz, storytelling, hashtags. La majorité valide.",
    "vote_label": "Le potentiel d’influenceur est-il réel ?"
    },
    {
    "id": 25, "type": "vote", "timer": 45, "duo": True,
    "text": "En duo : en 45 secondes, faites une scène de bureau totalement improvisée.",
    "instructions": "Impro totale. La majorité valide.",
    "vote_label": "La scène est-elle réussie ?"
    },
    {
    "id": 26, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, propose un nouveau nom pour l'entreprise… le plus éclaté possible.",
    "instructions": "Plus c’est nul, mieux c’est. La majorité valide.",
    "vote_label": "Le nom est-il suffisamment éclaté ?"
    },
    {
    "id": 27, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais un pitch pour supprimer toutes les réunions.",
    "instructions": "Argumente comme si ta vie en dépendait. La majorité valide.",
    "vote_label": "La suppression des réunions est-elle convaincante ?"
    },
    {
    "id": 28, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, raconte ton premier jour dans l’entreprise… version dramatique.",
    "instructions": "Suspense, tension, musique imaginaire. La majorité valide.",
    "vote_label": "Le drama est-il suffisant ?"
    },
    {
    "id": 29, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, fais un pitch pour remplacer la machine à café par quelque chose de pire.",
    "instructions": "Sois créatif dans le mauvais sens. La majorité valide.",
    "vote_label": "La proposition est-elle catastrophique ?"
    },
    {
    "id": 45, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, décris ton collègue idéal… mais fais-le totalement absurde.",
    "instructions": "Plus c’est improbable, mieux c’est. La majorité valide.",
    "vote_label": "Le collègue idéal est-il assez absurde ?"
    },
    {
    "id": 41, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris le mail de démission le plus dramatique possible.",
    "instructions": "On veut du drama, des larmes, et un peu de vengeance passive-agressive.",
    "vote_label": "Le mail est-il suffisamment dramatique ?"
},
{
    "id": 42, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une excuse crédible pour expliquer un retard de 2 heures.",
    "instructions": "Plus c’est crédible et absurde à la fois, mieux c’est.",
    "vote_label": "L’excuse est-elle acceptable ?"
},
{
    "id": 43, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, rédige un post LinkedIn après avoir réussi à changer une ampoule.",
    "instructions": "Transforme un geste banal en exploit entrepreneurial.",
    "vote_label": "Le post est-il digne d’un influenceur LinkedIn ?"
},
{
    "id": 44, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve 10 mots corporate que personne n'utilise dans la vraie vie.",
    "instructions": "Plus c’est incompréhensible, mieux c’est.",
    "vote_label": "Les mots sont-ils suffisamment corporate ?"
},
{
    "id": 45, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente un nouveau métier qui n'existe pas encore.",
    "instructions": "Un métier inutile mais payé très cher, évidemment.",
    "vote_label": "Le métier est-il innovant (et inutile) ?"
},
{
    "id": 46, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris le slogan le plus nul pour une startup.",
    "instructions": "Plus c’est éclaté, mieux c’est.",
    "vote_label": "Le slogan est-il suffisamment nul ?"
},
{
    "id": 47, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, décris ton manager idéal avec seulement 5 emojis.",
    "instructions": "Les emojis doivent raconter une histoire.",
    "vote_label": "Les emojis décrivent-ils un vrai manager idéal ?"
},
{
    "id": 48, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une politique RH totalement absurde.",
    "instructions": "Quelque chose que même Corpo! n’oserait pas.",
    "vote_label": "La politique est-elle suffisamment absurde ?"
},
{
    "id": 49, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, crée un hashtag LinkedIn ridicule.",
    "instructions": "Plus c’est cringe, mieux c’est.",
    "vote_label": "Le hashtag est-il ridiculement corporate ?"
},
{
    "id": 50, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve 5 excuses pour quitter une réunion plus tôt.",
    "instructions": "On veut des excuses créatives et crédibles.",
    "vote_label": "Les excuses sont-elles valables ?"
},
{
    "id": 51, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, renomme l'entreprise avec le pire nom possible.",
    "instructions": "Plus c’est catastrophique, mieux c’est.",
    "vote_label": "Le nom est-il vraiment catastrophique ?"
},
{
    "id": 52, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris une réponse passive-agressive à un mail professionnel.",
    "instructions": "Le passif-agressif doit être subtil mais violent.",
    "vote_label": "La réponse est-elle suffisamment passive-agressive ?"
},
{
    "id": 53, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une réunion totalement inutile.",
    "instructions": "Une réunion qui pourrait être un mail, mais en pire.",
    "vote_label": "La réunion est-elle inutile au possible ?"
},
{
    "id": 54, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, résume ton travail en utilisant uniquement des emojis.",
    "instructions": "On veut un résumé clair… ou pas.",
    "vote_label": "Les emojis résument-ils vraiment ton travail ?"
},
{
    "id": 55, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, crée un KPI complètement absurde.",
    "instructions": "Un indicateur qui ne sert à rien mais qui fait sérieux.",
    "vote_label": "Le KPI est-il suffisamment absurde ?"
},
{
    "id": 56, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, vends un objet banal comme une innovation révolutionnaire.",
    "instructions": "Transforme un trombone en révolution technologique.",
    "vote_label": "La vente est-elle convaincante ?"
},
{
    "id": 57, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris un message Teams qui aurait pu être un email.",
    "instructions": "Le message doit être inutilement long.",
    "vote_label": "Le message aurait-il dû être un email ?"
},
{
    "id": 58, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une startup qui ne résout aucun problème.",
    "instructions": "Une startup inutile mais financée à 10M€.",
    "vote_label": "La startup est-elle inutile ?"
},
{
    "id": 59, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, décris un collègue imaginaire insupportable.",
    "instructions": "On veut du réalisme… trop réaliste.",
    "vote_label": "Le collègue est-il vraiment insupportable ?"
},
{
    "id": 60, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve 5 buzzwords à placer dans une réunion.",
    "instructions": "Plus c’est vide de sens, mieux c’est.",
    "vote_label": "Les buzzwords sont-ils dignes de Corpo! ?"
},
{
    "id": 61, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris le pire commentaire LinkedIn possible.",
    "instructions": "Cringe, corporate, et inutile.",
    "vote_label": "Le commentaire est-il catastrophique ?"
},
{
    "id": 62, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une fonctionnalité inutile pour une application connue.",
    "instructions": "Plus c’est inutile, mieux c’est.",
    "vote_label": "La fonctionnalité est-elle inutile ?"
},
{
    "id": 63, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, rédige un avis Glassdoor hilarant sur ton entreprise imaginaire.",
    "instructions": "On veut du sarcasme et du vécu.",
    "vote_label": "L’avis est-il hilarant ?"
},
{
    "id": 64, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, explique pourquoi la pause café est essentielle à la productivité.",
    "instructions": "Argumente comme si ta carrière en dépendait.",
    "vote_label": "L’argumentation est-elle convaincante ?"
},
{
    "id": 65, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris un mail automatique totalement honnête.",
    "instructions": "Pas de filtre, pas de corporate.",
    "vote_label": "Le mail est-il honnête (trop honnête) ?"
},
{
    "id": 66, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve 5 synonymes corporate du mot 'problème'.",
    "instructions": "On veut du damage control.",
    "vote_label": "Les synonymes sont-ils corporate ?"
},
{
    "id": 67, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une excuse pour ne pas avoir lu un document.",
    "instructions": "Plus c’est plausible, mieux c’est.",
    "vote_label": "L’excuse est-elle crédible ?"
},
{
    "id": 68, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris la bio LinkedIn la plus prétentieuse possible.",
    "instructions": "On veut du leadership, du mindset, du bullshit.",
    "vote_label": "La bio est-elle suffisamment prétentieuse ?"
},
{
    "id": 69, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, crée une devise d'entreprise catastrophique.",
    "instructions": "Une devise qui ferait fuir n’importe quel candidat.",
    "vote_label": "La devise est-elle catastrophique ?"
},
{
    "id": 70, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, transforme une tâche banale en exploit extraordinaire.",
    "instructions": "Fais passer un mail envoyé pour un exploit héroïque.",
    "vote_label": "L’exploit est-il convaincant ?"
},
{
    "id": 71, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve le maximum d'acronymes professionnels inventés.",
    "instructions": "Plus c’est incompréhensible, mieux c’est.",
    "vote_label": "Les acronymes sont-ils crédibles ?"
},
{
    "id": 72, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris un message de félicitations exagérément enthousiaste.",
    "instructions": "On veut du corporate cringe.",
    "vote_label": "Le message est-il trop enthousiaste ?"
},
{
    "id": 73, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente un projet qui coûterait des millions pour rien.",
    "instructions": "Plus c’est inutile, mieux c’est.",
    "vote_label": "Le projet est-il un gouffre financier ?"
},
{
    "id": 74, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, écris un mail contenant le plus de jargon corporate possible.",
    "instructions": "Synergies, roadmap, quick wins… lâche-toi.",
    "vote_label": "Le jargon est-il insupportable ?"
},
{
    "id": 75, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, raconte une journée de travail comme une épopée héroïque.",
    "instructions": "Transforme ton quotidien en film hollywoodien.",
    "vote_label": "L’épopée est-elle héroïque ?"
},
{
    "id": 76, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, trouve 5 raisons absurdes de demander une augmentation.",
    "instructions": "Plus c’est absurde, mieux c’est.",
    "vote_label": "Les raisons sont-elles absurdes ?"
},
{
    "id": 77, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, crée le profil Tinder d'un manager.",
    "instructions": "On veut du cringe professionnel.",
    "vote_label": "Le profil est-il hilarant ?"
},
{
    "id": 78, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, rédige une annonce d'emploi remplie de red flags.",
    "instructions": "Plus c’est toxique, mieux c’est.",
    "vote_label": "L’annonce est-elle un nid à red flags ?"
},
{
    "id": 79, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, invente une règle de bureau complètement ridicule.",
    "instructions": "Une règle que personne ne respecterait.",
    "vote_label": "La règle est-elle ridicule ?"
},
{
    "id": 80, "type": "vote", "timer": 45, "duo": False,
    "text": "En 45 secondes, explique pourquoi tu mérites le poste de PDG.",
    "instructions": "Convaincs-nous que tu es la meilleure option (ou la pire).",
    "vote_label": "Mérite-t-il/elle d’être PDG ?"
}

]

from typing import Optional

class CreatePartyRequest(BaseModel):
    pseudo: str
    name: Optional[str] = None
    is_private: bool = False
    
class JoinByNameRequest(BaseModel):
    pseudo: str
    name: str

class JoinPartyRequest(BaseModel):
    pseudo: str
    code: str

class VoteRequest(BaseModel):
    voter_id: int
    target_id: int
    party_code: str

class DefiVoteRequest(BaseModel):
    voter_id: int
    party_code: str
    success: bool  # True = réussi, False = échoué
    


@router.post("/join_by_name")
def join_by_name(request: JoinByNameRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.pseudo == request.pseudo).first()
    if not player:
        raise HTTPException(404, "Pseudo introuvable")

    party = db.query(Party).filter(
        Party.name == request.name,
        Party.status == "waiting"
    ).first()
    if not party:
        raise HTTPException(404, "Aucun meeting avec ce nom trouvé")

    player.party_id = party.id
    player.last_seen = datetime.utcnow()
    party.last_activity = datetime.utcnow()
    db.commit()

    return {
        "message":  "Joueur ajouté",
        "party_id": party.id,
        "code":     party.code,
        "player_id": player.id
    }
    

# ---------------------------------------------------------
# CRÉATION DE PARTIE
# ---------------------------------------------------------
@router.post("/create")
def create_party(request: CreatePartyRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.pseudo == request.pseudo).first()
    if not player:
        raise HTTPException(404, "Pseudo introuvable")

    # 🔒 Maximum 10 parties simultanées
    waiting_parties = db.query(Party).filter(
        Party.status == "waiting"
    ).count()

    if waiting_parties >= 10:
        raise HTTPException(
            status_code=400,
            detail="Le nombre maximum de meetings simultanés (10) est atteint. Réessayez dans quelques instants."
        )

    # 🔒 Nom déjà utilisé
    existing_name = db.query(Party).filter(
        Party.name == request.name,
        Party.status == "waiting"
    ).first()

    if existing_name:
        raise HTTPException(400, "Ce nom de meeting est déjà utilisé !")

    player.party_id = None
    db.commit()

    code = generate_party_code()

    party = Party(
        code=code,
        host_id=player.id,
        name=request.name,
        is_private=request.is_private,
        status="waiting",
        last_activity=datetime.utcnow()
    )

    db.add(party)
    db.commit()
    db.refresh(party)

    print(f"🔍 DEBUG party.name APRÈS COMMIT = {repr(party.name)}")

    player.party_id = party.id
    player.last_seen = datetime.utcnow()
    party.last_activity = datetime.utcnow()

    db.commit()

    return {
        "message": "Partie créée",
        "party_id": party.id,
        "code": code,
        "is_private": request.is_private,
        "player_id": player.id
    }

# ---------------------------------------------------------
# REJOINDRE UNE PARTIE
# ---------------------------------------------------------
@router.post("/join")
def join_party(request: JoinPartyRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.pseudo == request.pseudo).first()
    if not player:
        raise HTTPException(404, "Pseudo introuvable")

    party = db.query(Party).filter(Party.code == request.code).first()
    if not party:
        raise HTTPException(404, "Code invalide")

    # Déjà dans cette partie → retourner directement
    if player.party_id == party.id:
        return {
            "message": "Déjà dans la partie",
            "party_id": party.id,
            "code": party.code,
            "player_id": player.id
        }

    if party.status != "waiting":
        raise HTTPException(400, "Cette partie a déjà commencé")

    player.party_id = party.id
    player.last_seen = datetime.utcnow()
    party.last_activity = datetime.utcnow()
    db.commit()

    return {
        "message": "Joueur ajouté",
        "party_id": party.id,
        "code": party.code,
        "player_id": player.id
    }


# ---------------------------------------------------------
# QUITTER UNE PARTIE
# ---------------------------------------------------------
@router.post("/leave/{player_id}")
def leave_party(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    
    party_id = player.party_id
    player.party_id = None
    db.commit()

    # 🔥 Supprimer la partie si plus personne dedans
    if party_id:
        remaining = db.query(Player).filter(Player.party_id == party_id).count()
        if remaining == 0:
            party = db.query(Party).filter(Party.id == party_id).first()
            if party and party.status == "waiting":
                db.delete(party)
                db.commit()
                print(f"🗑️ Partie supprimée car vide")

    return {"message": "Tu as quitté la partie."}


# ---------------------------------------------------------
# INFOS PARTIE
# ---------------------------------------------------------
@router.get("/verify/{code}")
def verify_party(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    return {
        "party_id": party.id,
        "code": party.code,
        "is_private": party.is_private,
        "host_id": party.host_id,
        "status": party.status,
        "name": party.name  # 🔥 ajouter

    }


# ---------------------------------------------------------
# LISTE DES JOUEURS
# ---------------------------------------------------------
@router.get("/players/{party_id}")
def get_players(party_id: int, db: Session = Depends(get_db)):
    players = db.query(Player).filter(Player.party_id == party_id).all()
    return [{"id": p.id, "pseudo": p.pseudo, "role": p.role, "is_alive": p.is_alive} for p in players]


# ---------------------------------------------------------
# PARTIES PUBLIQUES
# ---------------------------------------------------------
@router.get("/public")
def get_public_parties(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    limite_joueur = now - timedelta(seconds=60)
    limite_partie = now - timedelta(minutes=2)

    parties = db.query(Party).filter(
        Party.is_private == False,
        Party.status == "waiting"
    ).all()

    result = []

    for party in parties:
        players = db.query(Player).filter(Player.party_id == party.id).all()

        active_players = [
            p for p in players
            if p.last_seen and p.last_seen > limite_joueur
        ]

        should_delete = (
            len(active_players) == 0
            or (party.last_activity and party.last_activity < limite_partie)
        )

        if should_delete:
            for player in players:
                player.party_id = None

            db.delete(party)
            db.commit()
            continue

        result.append({
            "party_id": party.id,
            "code": party.code,
            "host_id": party.host_id,
            "name": party.name,
            "players_count": len(active_players)
        })

    return result


# ---------------------------------------------------------
# RÔLE D'UN JOUEUR
# ---------------------------------------------------------
@router.get("/role/{player_id}")
def get_role(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    if not player.role:
        raise HTTPException(400, "Rôle pas encore attribué")

    role_info = next((r for r in ALL_ROLES if r["name"] == player.role), None)
    if not role_info:
        raise HTTPException(400, "Rôle inconnu")

    return {
        "pseudo": player.pseudo,
        "role_name": player.role,
        "role": role_info["title"],
        "team": role_info["team"],
        "image": role_info["image"]
    }


# ---------------------------------------------------------
# HEARTBEAT
# ---------------------------------------------------------
@router.post("/heartbeat/{player_id}")
def heartbeat(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    player.last_seen = datetime.utcnow()
    if player.party_id:
        party = db.query(Party).filter(Party.id == player.party_id).first()
        if party:
            party.last_activity = datetime.utcnow()
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------
# LANCER LA PARTIE
# ---------------------------------------------------------
@router.post("/start/{party_id}")
async def start_party(party_id: int, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.id == party_id).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    players = db.query(Player).filter(Player.party_id == party_id).all()
    nb = len(players)

    if nb < 4:
        raise HTTPException(400, "Il faut au moins 4 joueurs.")
    if nb > len(ALL_ROLES):
        raise HTTPException(400, f"Maximum {len(ALL_ROLES)} joueurs.")

    if 4 <= nb <= 6:
        nb_managers = 1
    elif 7 <= nb <= 10:
        nb_managers = 2
    else:
        nb_managers = 3

    manager_roles = [r for r in ALL_ROLES if r["team"] == "Managers"]
    collab_roles  = [r for r in ALL_ROLES if r["team"] == "Collaborateurs"]

    chosen = random.sample(manager_roles, nb_managers) + random.sample(collab_roles, nb - nb_managers)
    random.shuffle(chosen)

    for player in players:
        player.is_alive = True
        player.has_used_power = False
        player.has_drawn_corpocard = False
        player.victim_of_managers = False
        player.victim_of_claire = False
        player.virus_from_abdel = False
        player.fired_by_stephane = False  # 🔥 ajouter cette ligne
        player.revealed_to = None

    for player, role in zip(players, chosen):
        player.role = role["name"]
        player.last_role = role["name"]
        player.is_manager = (role["team"] == "Managers")

    party.status = "in_progress"
    party.meeting_number = 1
    party.last_activity = datetime.utcnow()
    db.commit()

    party_code = party.code
    await notify_party_start(party_code)

    # Attendre que les joueurs voient leur rôle (15s sur decouverte_role.html)
    # Attendre que les joueurs voient leur rôle (15s sur decouverte_role.html)
    await asyncio.sleep(18)

# 🔥 Attendre que TOUS les joueurs aient reçu leur rôle
    while True:
        players = db.query(Player).filter(Player.party_id == party_id).all()
        if all(p.role for p in players):
            break
        await asyncio.sleep(0.2)

# 🔥 Attendre que TOUS les joueurs soient connectés au WebSocket
    from websocket_manager import connections
    players = db.query(Player).filter(Player.party_id == party_id).all()   # ✔ IMPORTANT
    while True:
        connected = len(connections.get(party.code, {}))
        if connected >= len(players):
            break
        await asyncio.sleep(0.2)

    db_fresh = SessionLocal()
    try:
        print(f"🚀 Lancement du meeting pour {party_code}")
        await start_meeting(party_code, db_fresh)


    except Exception as e:
        print(f"❌ Erreur start_meeting : {e}")
    finally:
        db_fresh.close()

    return {"message": "Rôles attribués et meeting lancé"}


# ---------------------------------------------------------
# VOTE
# ---------------------------------------------------------
@router.post("/vote")
async def submit_vote(request: VoteRequest, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == request.party_code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    voter = db.query(Player).filter(Player.id == request.voter_id).first()
    if not voter or not voter.is_alive:
        raise HTTPException(400, "Joueur invalide ou éliminé")

    target = db.query(Player).filter(Player.id == request.target_id).first()
    if not target or not target.is_alive:
        raise HTTPException(400, "Cible invalide")

    voter.revealed_to = request.target_id
    db.commit()

    alive_players = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True
    ).all()

    voters_done = [p for p in alive_players if p.revealed_to is not None]

    if len(voters_done) >= len(alive_players):
        vote_counts = {}
        for p in voters_done:
            vote_counts[p.revealed_to] = vote_counts.get(p.revealed_to, 0) + 1

        max_votes = max(vote_counts.values())
        eliminated_ids = [pid for pid, v in vote_counts.items() if v == max_votes]

        for p in alive_players:
            p.revealed_to = None

        print(f"📊 Éliminé(s) du vote : {eliminated_ids}")

        if len(eliminated_ids) > 1:
            print(f"⚖️ Égalité → {len(eliminated_ids)} joueurs concernés")
            victims = [db.query(Player).filter(Player.id == eid).first() for eid in eliminated_ids]
            victims = [v for v in victims if v]
            is_everyone = len(eliminated_ids) >= len(alive_players)

            if is_everyone:
                # Tous les vivants restants sont à égalité → logique joker
                no_joker  = [v for v in victims if not v.has_drawn_corpocard]
                has_joker = [v for v in victims if v.has_drawn_corpocard]

                if len(no_joker) == 0:
                    # Tous ont déjà utilisé leur joker → match nul direct
                    for v in victims:
                        v.is_alive = False
                    db.commit()
                    await broadcast(party.code, "game_over:match_nul")

                elif len(no_joker) == 1 and len(has_joker) >= 1:
                    # Un sans joker → il est éliminé directement
                    loser = no_joker[0]
                    loser.is_alive = False
                    db.commit()
                    await broadcast(party.code, f"player_eliminated_direct:{loser.pseudo}:{loser.role}")
                    await asyncio.sleep(3)
                    alive2 = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
                    if not [p for p in alive2 if p.is_manager]:
                        await broadcast(party.code, "game_over:victoire_collabs")
                        return {"message": "Victoire Collabs"}
                    if not [p for p in alive2 if not p.is_manager]:
                        await broadcast(party.code, "game_over:victoire_managers")
                        return {"message": "Victoire Managers"}
                    await _launch_next_meeting(party.code, party.id, db)

                else:
                    # Tous sans joker → match nul
                    for v in victims:
                        v.is_alive = False
                    db.commit()
                    await broadcast(party.code, "game_over:match_nul")

                return {"message": "Égalité finale traitée"}

            # Égalité classique → file de défis
            names = [v.pseudo for v in victims]
            await broadcast(party.code, f"egalite_defis:{','.join(names)}")
            await asyncio.sleep(3)

            first_victim = victims[0]
            if first_victim.has_drawn_corpocard:
                first_victim.is_alive = False
                party.last_eliminated_id = first_victim.id
                party.turn_order   = json.dumps(eliminated_ids)
                party.current_turn = 0
                party.meeting_phase  = "vote_defi"
                party.defi_sub_phase = "running_from_vote"
                db.commit()
                await broadcast(party.code, f"player_eliminated_direct:{first_victim.pseudo}:{first_victim.role}")
                await asyncio.sleep(3)
                await _process_next_in_queue(party.code, party.id, 0, True)
            else:
                party.last_eliminated_id = first_victim.id
                party.turn_order   = json.dumps(eliminated_ids)
                party.current_turn = 0
                party.meeting_phase  = "vote_defi"
                party.defi_sub_phase = "running_from_vote"
                db.commit()
                await broadcast(party.code, "phase:defi_decision")


        else:
            # Un seul éliminé → vérifier le joker
            first_target_id = eliminated_ids[0]
            victim = db.query(Player).filter(Player.id == first_target_id).first()

            if victim and victim.has_drawn_corpocard:
                # Joker déjà utilisé → élimination directe
                print(f"⛔ {victim.pseudo} a déjà utilisé son joker → élimination directe")
                victim.is_alive = False
                party.last_eliminated_id = victim.id
                db.commit()

                alive_after    = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
                alive_managers = [p for p in alive_after if p.is_manager]
                alive_collabs  = [p for p in alive_after if not p.is_manager]

                if not alive_managers:
                    await broadcast(party.code, "game_over:victoire_collabs")
                    return {"message": "Victoire des Collaborateurs"}
                if not alive_collabs:
                    await broadcast(party.code, "game_over:victoire_managers")
                    return {"message": "Victoire des Managers"}

                await broadcast(party.code, f"player_eliminated_direct:{victim.pseudo}:{victim.role}")
                await asyncio.sleep(5)
                # 🔥 Si Abdel éliminé directement → traiter les infectés
                if victim.role == "Abdel":
                    await _handle_abdel_eliminated(party.code, party, victim, db, came_from_vote=True)
                    return {"message": "Abdel éliminé direct — infectés traités"}
                await _launch_next_meeting(party.code, party.id, db)
            else:
                # Joker disponible → proposer le défi
                party.last_eliminated_id = first_target_id
                party.turn_order         = json.dumps(eliminated_ids)
                party.current_turn       = 0
                party.meeting_phase      = "vote_defi"
                party.defi_sub_phase     = "running_from_vote"
                db.commit()
                await broadcast(party.code, "phase:defi_decision")

    return {"message": "Vote enregistré"}


# ---------------------------------------------------------
# RÉSULTAT DU VOTE
# ---------------------------------------------------------
@router.get("/vote_result/{code}")
def get_vote_result(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    eliminated = None
    if party.last_eliminated_id:
        last_dead = db.query(Player).filter(Player.id == party.last_eliminated_id).first()
        if last_dead:
            role_info = next((r for r in ALL_ROLES if r["name"] == last_dead.role), {})
            eliminated = {
                "player_id": last_dead.id,
                "pseudo": last_dead.pseudo,
                "role": last_dead.role,
                "team": role_info.get("team", "?"),
                "image": role_info.get("image", "joueur1.png"),
                "has_drawn_corpocard": last_dead.has_drawn_corpocard
            }

    all_players = db.query(Player).filter(Player.party_id == party.id).all()
    alive = [p for p in all_players if p.is_alive]
    alive_managers = [p for p in alive if p.is_manager]
    alive_collabs  = [p for p in alive if not p.is_manager]

    game_over = False
    winner = None
    if len(alive_managers) == 0:
        game_over = True
        winner = "Collaborateurs"
    elif len(alive_collabs) == 0:
        game_over = True
        winner = "Managers"

    return {
        "eliminated": eliminated,
        "game_over": game_over,
        "winner": winner
    }


# ---------------------------------------------------------
# VÉRIFIER SI UN JOUEUR EST VIVANT
# ---------------------------------------------------------
@router.get("/is_alive/{player_id}")
def is_alive(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    return {"is_alive": player.is_alive, "pseudo": player.pseudo}


# ---------------------------------------------------------
# RÉCUPÉRER LA CARTE CORPO ACTUELLE (défi en cours)
# ---------------------------------------------------------
@router.get("/current_corpocard/{code}")
def get_current_corpocard(code: str, db: Session = Depends(get_db)):
    """
    Retourne le défi en cours. Si aucun défi n'est tiré pour ce round,
    en tire un aléatoirement, le stocke et le retourne.
    Tous les joueurs appellent cette route → ils reçoivent tous le MÊME défi.
    """
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    # Si un défi est déjà tiré pour ce round → retourner le même
    if party.current_defi_id:
        card = next((c for c in CORPO_CARDS if c["id"] == party.current_defi_id), None)
        if card:
            return card

    # Sinon tirer un nouveau défi aléatoire
    available = [c for c in CORPO_CARDS if c["type"] != "direct_fail"]
    if not available:
        available = CORPO_CARDS

    card = random.choice(available)
    party.current_defi_id = card["id"]
    db.commit()

    return card


# ---------------------------------------------------------
# TIFFANY — Proposer 5 mots parmi ceux pas encore utilisés
# ---------------------------------------------------------
@router.get("/tiff/propose/{code}")
def tiff_propose_mots(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    # Mots déjà utilisés
    used = json.loads(party.tiff_mots_actifs or "[]") + json.loads(party.tiff_mots_utilises or "[]")
    available = [m for m in TIFF_MOTS_DISPONIBLES if m not in used]

    # Si plus assez de mots → reset des utilisés (on garde juste les actifs)
    if len(available) < 5:
        party.tiff_mots_utilises = "[]"
        db.commit()
        actifs = json.loads(party.tiff_mots_actifs or "[]")
        available = [m for m in TIFF_MOTS_DISPONIBLES if m not in actifs]

    proposed = random.sample(available, min(5, len(available)))
    return {"mots": proposed}


# ---------------------------------------------------------
# TIFFANY — Enregistrer les 3 mots choisis
# ---------------------------------------------------------
class TiffMotsRequest(BaseModel):
    code: str
    mots: list

@router.post("/tiff/choisir")
async def tiff_choisir_mots(request: TiffMotsRequest, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == request.code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    if len(request.mots) != 3:
        raise HTTPException(400, "Tu dois choisir exactement 3 mots")

    # Ajouter aux mots actifs
    actifs = json.loads(party.tiff_mots_actifs or "[]")
    utilises = json.loads(party.tiff_mots_utilises or "[]")

    for mot in request.mots:
        if mot not in actifs:
            actifs.append(mot)
        if mot not in utilises:
            utilises.append(mot)

    party.tiff_mots_actifs = json.dumps(actifs)
    party.tiff_mots_utilises = json.dumps(utilises)
    db.commit()

    print(f"🔒 Mots interdits actifs (SECRET) : {actifs}")

    # 🔥 NE PAS broadcaster — les mots sont SECRETS
    # Seule confirmation : la route retourne les mots à Tiffany uniquement (via HTTP)
    # Les autres joueurs ne savent pas quels mots sont interdits

    return {"message": "Mots enregistrés en secret !", "mots_actifs": actifs}


# ---------------------------------------------------------
# TIFFANY — Récupérer les mots actifs
# ---------------------------------------------------------
@router.get("/tiff/mots_actifs/{code}")
def get_tiff_mots(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")
    actifs = json.loads(party.tiff_mots_actifs or "[]")
    return {"mots_actifs": actifs}


# ---------------------------------------------------------
# RÉCUPÉRER LES DONNÉES COMPLÈTES D'UN RÔLE
# ---------------------------------------------------------
@router.get("/role_info/{role_name}")
def get_role_info(role_name: str):
    role = next((r for r in ALL_ROLES if r["name"] == role_name), None)
    if not role:
        raise HTTPException(404, "Rôle introuvable")
    return role


# ---------------------------------------------------------
# PERFORMANCE DU DÉFI TERMINÉE (la victime a fini son action)
# → Déclenche le vote du jury chez les autres
# ---------------------------------------------------------
@router.post("/defi_performance_done/{code}")
async def defi_performance_done(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    # 🔥 NE PAS écraser defi_sub_phase — on en a besoin dans next_phase
    # On stocke juste que la performance est terminée dans meeting_phase
    # defi_sub_phase reste "running_from_vote" ou "running_from_meeting"
    db.commit()

    # Signal au jury pour voter
    await broadcast(code, "phase:resultat_defi")
    return {"message": "Performance terminée, vote du jury ouvert"}


# ---------------------------------------------------------
# VOTE DÉFI — Les observateurs évaluent la performance
# ---------------------------------------------------------
@router.post("/defi_vote")
async def defi_vote(request: DefiVoteRequest, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == request.party_code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    voter = db.query(Player).filter(Player.id == request.voter_id).first()
    if not voter:
        raise HTTPException(400, "Joueur introuvable")

    # Stocker le vote : 1 = succès, 2 = échec
    voter.revealed_to = 1 if request.success else 2
    db.commit()

    # Tous les joueurs vivants de la partie SAUF la victime du défi
    # (la victime peut être encore alive=True pendant le défi → on l'exclut explicitement)
    jury = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True,
        Player.id != party.last_eliminated_id
    ).all()

    # Compter uniquement les votes défi (1 ou 2), pas les None restants d'anciens votes
    votes_cast = [p for p in jury if p.revealed_to in (1, 2)]

    print(f"🗳️ Votes défi : {len(votes_cast)}/{len(jury)}")

    if len(votes_cast) >= len(jury):
        yes_votes = sum(1 for p in votes_cast if p.revealed_to == 1)
        no_votes  = sum(1 for p in votes_cast if p.revealed_to == 2)
        success   = yes_votes > no_votes   # majorité stricte requise, égalité = échec

        print(f"📊 Résultat défi : {yes_votes} oui / {no_votes} non → {'succès' if success else 'échec'}")

        # Nettoyage des votes pour le prochain round
        for p in jury:
            p.revealed_to = None

        # Appliquer le résultat à la victime
        eliminated = db.query(Player).filter(Player.id == party.last_eliminated_id).first()
        if eliminated:
            eliminated.has_drawn_corpocard = True
            eliminated.is_alive = success
            eliminated.victim_of_managers = False
            eliminated.victim_of_claire   = False
            print(f"{'✅' if success else '❌'} Défi {'réussi' if success else 'échoué'} pour {eliminated.pseudo}")
        db.commit()
        
        # 🔥 Si Abdel est éliminé → broadcaster le résultat D'ABORD puis traiter les infectés
        if eliminated and not eliminated.is_alive and eliminated.role == "Abdel":
            came_from_vote = party.defi_sub_phase == "running_from_vote"
            await _handle_abdel_eliminated(request.party_code, party, eliminated, db, came_from_vote=came_from_vote)
            return {"message": "Abdel éliminé — infectés traités"}

        # Vérif fin de partie
        alive_after    = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
        alive_managers = [p for p in alive_after if p.is_manager]
        alive_collabs  = [p for p in alive_after if not p.is_manager]

        if not alive_managers:
            await broadcast(request.party_code, "game_over:victoire_collabs")
            return {"message": "Victoire des Collaborateurs"}
        if not alive_collabs:
            await broadcast(request.party_code, "game_over:victoire_managers")
            return {"message": "Victoire des Managers"}

        # 🔥 Reset le défi — le prochain licencié aura un défi différent
        party.current_defi_id = None
        db.commit()

        result = "success" if success else "fail"
        await broadcast(request.party_code, f"defi_result:{result}")

    return {"message": "Vote défi enregistré"}


# ---------------------------------------------------------
# PHASE SUIVANTE après résultat du défi
# → Appelé par resultat_defi.html quand le host clique "Continuer"
# ---------------------------------------------------------
@router.post("/next_phase/{code}")
async def next_phase(code: str, db: Session = Depends(get_db)):
    """
    Appelé après le résultat du défi (par le host).
    Gère la file d'attente en cas d'égalité (plusieurs éliminés à tour de rôle).
    - Si le défi venait du MEETING → feedback ensuite
    - Si le défi venait du VOTE → meeting suivant ensuite
    """
    party = db.query(Party).filter(Party.code == code).first()
    print("========== NEXT_PHASE ==========")
    print("meeting_phase =", party.meeting_phase)
    print("defi_sub_phase =", party.defi_sub_phase)
    print("turn_order =", party.turn_order)
    print("current_turn =", party.current_turn)
    print("================================")
    if not party:
        raise HTTPException(404, "Partie introuvable")
    
    # 🔥 Abdel en cours de traitement → ignorer next_phase auto
    if party.defi_sub_phase == "abdel_processing":
        return {"message": "Abdel en cours de traitement — ignoré"}

    # Vérif fin de partie
    alive = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True
    ).all()
    alive_managers = [p for p in alive if p.is_manager]
    alive_collabs  = [p for p in alive if not p.is_manager]

    if not alive_managers:
        await broadcast(code, "game_over:victoire_collabs")
        return {"message": "Victoire des Collaborateurs"}
    if not alive_collabs:
        await broadcast(code, "game_over:victoire_managers")
        return {"message": "Victoire des Managers"}

    # 🔥 Lire l'origine AVANT de modifier quoi que ce soit
    came_from_vote = party.defi_sub_phase == "running_from_vote"

    # 🔥 Vérifier s'il reste d'autres éliminés dans la file (cas d'égalité)
    eliminated_queue = json.loads(party.turn_order) if party.turn_order else []
    next_turn_index  = (party.current_turn or 0) + 1

    if next_turn_index < len(eliminated_queue):
        # Il reste un autre joueur à traiter dans la file
        next_victim_id = eliminated_queue[next_turn_index]
        next_victim    = db.query(Player).filter(Player.id == next_victim_id).first()

        print(f"➡️ File d'attente : passage au joueur suivant {next_victim.pseudo if next_victim else '?'}")

        if next_victim and next_victim.has_drawn_corpocard:
            # Joker déjà utilisé → élimination directe
            next_victim.is_alive = False
            party.last_eliminated_id = next_victim_id
            party.current_turn = next_turn_index
            party.current_defi_id = None  # 🔥 FIX : reset défi pour la prochaine victime
            db.commit()

            # Vérif fin de partie après élimination directe
            alive2 = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
            if not [p for p in alive2 if p.is_manager]:
                await broadcast(code, "game_over:victoire_collabs")
                return {"message": "Victoire Collaborateurs"}
            if not [p for p in alive2 if not p.is_manager]:
                await broadcast(code, "game_over:victoire_managers")
                return {"message": "Victoire Managers"}

            await broadcast(code, f"player_eliminated_direct:{next_victim.pseudo}:{next_victim.role}")
            await asyncio.sleep(5)
            # Passer au suivant dans la file récursivement
            await _process_next_in_queue(code, party.id, next_turn_index, came_from_vote)
        else:
            # Joker disponible → proposer le défi
            party.last_eliminated_id = next_victim_id
            party.current_turn       = next_turn_index
            party.current_defi_id    = None  # 🔥 FIX : reset défi pour la prochaine victime
            party.defi_sub_phase = "running_from_vote" if came_from_vote else "running_from_meeting"
            db.commit()
            await broadcast(code, "phase:defi_decision")

        return {"message": "Joueur suivant dans la file"}

    # File épuisée → passer à la phase suivante
    # File épuisée → passer à la phase suivante
    # 🔥 Vérifier si on vient d'un défi d'infecté Abdel (meeting)
    abdel_mort_meeting = db.query(Player).filter(
        Player.party_id == party.id,
        Player.role == "Abdel",
        Player.is_alive == False,
        Player.has_drawn_corpocard == True,
        Player.victim_of_managers == False  # Abdel éliminé pas par vote
    ).first()

    db.query(Player).filter(Player.party_id == party.id).update({
        "victim_of_managers": False,
        "victim_of_claire": False,
        "fired_by_stephane":  False,
    })
    party.last_eliminated_id = None
    party.turn_order         = None
    party.defi_sub_phase     = None

    if came_from_vote and not abdel_mort_meeting:
        db.commit()
        await _launch_next_meeting(code, party.id, db)
    else:
        party.meeting_phase = "feedback"
        db.commit()
        await broadcast(code, "phase:feedback:pre_vote")

    return {"message": "Phase suivante déclenchée"}


async def _process_next_in_queue(code: str, party_id: int, current_index: int, came_from_vote: bool):
    """Traite le joueur suivant dans la file d'élimination."""
    db = SessionLocal()
    try:
        party = db.query(Party).filter(Party.id == party_id).first()
        if not party:
            return

        eliminated_queue = json.loads(party.turn_order) if party.turn_order else []
        next_index = current_index + 1

        if next_index < len(eliminated_queue):
            next_victim_id = eliminated_queue[next_index]
            next_victim    = db.query(Player).filter(Player.id == next_victim_id).first()

            if next_victim and next_victim.has_drawn_corpocard:
                next_victim.is_alive = False
                party.last_eliminated_id = next_victim_id
                party.current_turn = next_index
                db.commit()
                await broadcast(code, f"player_eliminated_direct:{next_victim.pseudo}:{next_victim.role}")
                await asyncio.sleep(5)
                # 🔥 FIX : si Abdel éliminé directement
                if next_victim.role == "Abdel":
                    await _handle_abdel_eliminated(code, party, next_victim, db)
                    return
                await _process_next_in_queue(code, party_id, next_index, came_from_vote)
            else:
                party.last_eliminated_id = next_victim_id
                party.current_turn       = next_index
                party.current_defi_id    = None  # 🔥 FIX : reset défi pour la prochaine victime
                party.defi_sub_phase = "running_from_vote" if came_from_vote else "running_from_meeting"
                db.commit()
                await broadcast(code, "phase:defi_decision")
        else:
            # File épuisée → vérifier s'il reste des vivants
            alive_remaining = db.query(Player).filter(
                Player.party_id == party_id,
                Player.is_alive == True
            ).all()

            if not alive_remaining:
                # Plus personne de vivant → match nul
                db.commit()
                await broadcast(code, "game_over:match_nul")
                return

            # Vérif victoire/défaite normale
            managers = [p for p in alive_remaining if p.is_manager]
            collabs  = [p for p in alive_remaining if not p.is_manager]
            if not managers:
                db.commit()
                await broadcast(code, "game_over:victoire_collabs")
                return
            if not collabs:
                db.commit()
                await broadcast(code, "game_over:victoire_managers")
                return

            db.query(Player).filter(Player.party_id == party_id).update({
                "victim_of_managers": False,
                "victim_of_claire": False,
                "fired_by_stephane":  False,

            })
            party.last_eliminated_id = None
            party.turn_order         = None
            party.defi_sub_phase     = None
            if came_from_vote:
                db.commit()
                await _launch_next_meeting(code, party_id, db)
            else:
                party.meeting_phase = "feedback"
                db.commit()
                await broadcast(code, "phase:feedback:pre_vote")
    finally:
        db.close()

# ---------------------------------------------------------
# CINDY — Info secrète sur ses voisins (privée)
# ---------------------------------------------------------
@router.get("/cindy/voisins/{code}/{player_id}")
async def cindy_voisins(code: str, player_id: int, db: Session = Depends(get_db)):
    """
    Retourne en PRIVÉ à Cindy si l'un de ses voisins est Manager.
    Le résultat est envoyé via WebSocket privé.
    """
    party = db.query(Party).filter(Party.code == code).first()
    if not party or not party.turn_order:
        raise HTTPException(404, "Partie introuvable")

    import json as _json
    turn_order = _json.loads(party.turn_order)

    # Trouver la position de Cindy dans le tour
    all_players = db.query(Player).filter(
        Player.party_id == party.id,
        Player.is_alive == True
    ).all()

    # Retrouver les IDs dans l'ordre de la table (pas du meeting)
    cindy = db.query(Player).filter(Player.id == player_id).first()
    if not cindy:
        raise HTTPException(404, "Joueur introuvable")

    # Récupérer tous les joueurs vivants triés par ID (ordre de la table)
    all_alive = sorted(all_players, key=lambda p: p.id)
    cindy_idx = next((i for i, p in enumerate(all_alive) if p.id == player_id), -1)

    if cindy_idx == -1:
        return {"has_manager_neighbor": False}

    total = len(all_alive)
    left  = all_alive[(cindy_idx - 1) % total]
    right = all_alive[(cindy_idx + 1) % total]

    has_manager = left.is_manager or right.is_manager

    # Envoyer le résultat en PRIVÉ via WebSocket
    from websocket_manager import connections
    if code in connections and player_id in connections[code]:
        msg = "cindy_voisin:oui" if has_manager else "cindy_voisin:non"
        try:
            await connections[code][player_id].send_text(msg)
        except:
            pass

    return {"has_manager_neighbor": has_manager}

# ---------------------------------------------------------
# TIRER LE DÉFI (appelé une seule fois par le serveur)
# Le défi est stocké ET broadcasté à tous les joueurs
# ---------------------------------------------------------
@router.post("/draw_defi/{code}")
async def draw_defi(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    # Si déjà tiré pour ce round → retourner le même
    if party.current_defi_id:
        card = next((c for c in CORPO_CARDS if c["id"] == party.current_defi_id), None)
        if card:
            await broadcast(code, f"defi_card:{json.dumps(card)}")
            return card

    # Tirer un nouveau défi aléatoire
    available = [c for c in CORPO_CARDS if c["type"] != "direct_fail"]
    card = random.choice(available)
    party.current_defi_id = card["id"]
    db.commit()

    # Broadcaster le défi à TOUS les joueurs
    await broadcast(code, f"defi_card:{json.dumps(card)}")
    return card

# ---------------------------------------------------------
# MARQUER QU'UN JOUEUR A TIRÉ SA CARTE CORPO
# ---------------------------------------------------------
@router.post("/draw_corpocard/{player_id}")
async def draw_corpocard(player_id: int, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    player.has_drawn_corpocard = True
    db.commit()
    return {"message": "Carte corpo marquée", "player_id": player_id}

# ---------------------------------------------------------
# RÉSULTAT DU DÉFI (refus ou timeout)
# ---------------------------------------------------------
class DefiResultRequest(BaseModel):
    player_id: int
    success: bool

@router.post("/defi_result")
async def defi_result(request: DefiResultRequest, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == request.player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")
    party = db.query(Party).filter(Party.id == player.party_id).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")
    player.has_drawn_corpocard = True
    if not request.success:
        player.is_alive = False
        player.victim_of_managers = False
        player.victim_of_claire = False
        db.commit()
        if player.role == "Abdel":
            await _handle_abdel_eliminated(party.code, party, player, db)
            return {"message": "Abdel éliminé"}
        alive = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
        if not [p for p in alive if p.is_manager]:
            await broadcast(party.code, "game_over:victoire_collabs")
            return {"message": "Victoire Collaborateurs"}
        if not [p for p in alive if not p.is_manager]:
            await broadcast(party.code, "game_over:victoire_managers")
            return {"message": "Victoire Managers"}
        await broadcast(party.code, f"player_eliminated_direct:{player.pseudo}:{player.role}")
        await asyncio.sleep(2)
        await _launch_next_meeting(party.code, party.id, db)
    else:
        player.victim_of_managers = False
        player.victim_of_claire = False
        db.commit()
        await broadcast(party.code, "defi_result:success")
    return {"message": "Résultat défi traité"}
# ---------------------------------------------------------
# COLLECTIF — Le CHO déclare le perdant
# ---------------------------------------------------------
class CollectifLoserRequest(BaseModel):
    party_code: str
    loser_id: int

@router.post("/collectif_loser")
async def collectif_loser(request: CollectifLoserRequest, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == request.party_code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    loser = db.query(Player).filter(Player.id == request.loser_id).first()
    if not loser:
        raise HTTPException(404, "Joueur introuvable")

    if not loser.has_drawn_corpocard:
        # Proposer le défi
        loser.victim_of_managers = True
        party.last_eliminated_id = loser.id
        party.meeting_phase      = "vote_defi"
        party.defi_sub_phase     = "running_from_vote"
        party.turn_order         = json.dumps([loser.id])
        party.current_turn       = 0
        db.commit()
        await broadcast(request.party_code, f"player_eliminated_direct:{loser.pseudo}:collectif")
        await asyncio.sleep(2)
        await broadcast(request.party_code, "phase:defi_decision")
    else:
        loser.is_alive = False
        db.commit()
        await broadcast(request.party_code, f"player_eliminated_direct:{loser.pseudo}:{loser.role}")

        alive = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
        if not [p for p in alive if p.is_manager]:
            await broadcast(request.party_code, "game_over:victoire_collabs")
        elif not [p for p in alive if not p.is_manager]:
            await broadcast(request.party_code, "game_over:victoire_managers")
        else:
            await _launch_next_meeting(request.party_code, party.id, db)

    # Reset le défi pour le prochain licencié
    party.current_defi_id = None
    db.commit()
    return {"message": "Perdant déclaré"}


# ---------------------------------------------------------
# DÉFI SPÉCIAL — Effets particuliers
# ---------------------------------------------------------
class DefiSpecialRequest(BaseModel):
    party_code: str
    player_id: int
    special_type: str
    target_id: int = None

@router.post("/defi_special")
async def defi_special(request: DefiSpecialRequest, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == request.party_code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    player = db.query(Player).filter(Player.id == request.player_id).first()
    if not player:
        raise HTTPException(404, "Joueur introuvable")

    stype = request.special_type

    if stype == "become_manager":
        # Le joueur rejoint les managers
        player.is_manager = True
        player.role       = "Fabien"
        player.is_alive   = True
        player.has_drawn_corpocard = True
        db.commit()
        await broadcast(request.party_code, f"player_became_manager:{player.pseudo}")
        await asyncio.sleep(3)
        await _end_special_defi(request.party_code, party, db)

    elif stype == "skip_meeting":
        # Revient au prochain meeting — reste en jeu
        player.is_alive = True
        player.has_drawn_corpocard = True
        db.commit()
        await broadcast(request.party_code, f"player_skip_meeting:{player.pseudo}")
        await asyncio.sleep(2)
        await _end_special_defi(request.party_code, party, db)

    elif stype == "contaminate_abdel":
        # Contaminé par Abdel
        player.virus_from_abdel = True
        player.is_alive = True
        player.has_drawn_corpocard = True
        db.commit()
        await broadcast(request.party_code, f"player_contaminated:{player.pseudo}")
        await asyncio.sleep(2)
        await _end_special_defi(request.party_code, party, db)

    elif stype == "designate_victim":
        # Désigne une autre victime à sa place
        if not request.target_id:
            raise HTTPException(400, "target_id requis")
        target = db.query(Player).filter(Player.id == request.target_id).first()
        if not target:
            raise HTTPException(404, "Cible introuvable")

        player.is_alive = True
        player.has_drawn_corpocard = True

        if not target.has_drawn_corpocard:
            target.victim_of_managers = True
            party.last_eliminated_id  = target.id
            party.meeting_phase       = "vote_defi"
            party.defi_sub_phase      = "running_from_vote"
            party.turn_order          = json.dumps([target.id])
            party.current_turn        = 0
            db.commit()
            await broadcast(request.party_code, f"player_designated:{player.pseudo}:{target.pseudo}")
            await asyncio.sleep(2)
            await broadcast(request.party_code, "phase:defi_decision")
        else:
            target.is_alive = False
            db.commit()
            await broadcast(request.party_code, f"player_eliminated_direct:{target.pseudo}:{target.role}")
            await asyncio.sleep(2)
            await _end_special_defi(request.party_code, party, db)

    elif stype == "cumul_roles":
        # Attribuer un 2ème rôle aléatoire
        current_roles = [p.role for p in db.query(Player).filter(Player.party_id == party.id).all()]
        available_roles = [r for r in ALL_ROLES if r["name"] not in current_roles]
        if available_roles:
            new_role = random.choice(available_roles)
            player.last_role = new_role["name"]  # Stocker comme rôle secondaire
        player.is_alive = True
        player.has_drawn_corpocard = True
        db.commit()
        await broadcast(request.party_code, f"player_cumul_roles:{player.pseudo}:{player.last_role}")
        await asyncio.sleep(2)
        await _end_special_defi(request.party_code, party, db)

    return {"message": "Effet spécial appliqué"}


async def _end_special_defi(code: str, party, db):
    """Après un défi spécial, continuer le flux normal."""
    came_from_vote = party.defi_sub_phase == "running_from_vote"

    # Nettoyer
    db.query(Player).filter(Player.party_id == party.id).update({
        "victim_of_managers": False, "victim_of_claire": False
    })
    party.last_eliminated_id = None
    party.defi_sub_phase     = None

    alive = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
    if not [p for p in alive if p.is_manager]:
        db.commit()
        await broadcast(code, "game_over:victoire_collabs")
        return
    if not [p for p in alive if not p.is_manager]:
        db.commit()
        await broadcast(code, "game_over:victoire_managers")
        return

    if came_from_vote:
        db.commit()
        await _launch_next_meeting(code, party.id, db)
    else:
        party.meeting_phase = "feedback"
        db.commit()
        await broadcast(code, "phase:feedback:pre_vote")

async def _launch_next_meeting(code: str, party_id: int, db: Session):
    """Reset la partie et lance le meeting suivant."""
    party = db.query(Party).filter(Party.id == party_id).first()
    if not party:
        return

    party.meeting_number += 1
    party.meeting_phase = "waiting"
    party.defi_sub_phase = None
    party.turn_order = None
    party.current_turn = 0
    party.last_eliminated_id = None

    # Reset uniquement les flags de victime (pas has_drawn_corpocard !)
    db.query(Player).filter(Player.party_id == party_id).update({
        "victim_of_managers": False,
        "victim_of_claire": False,
        "fired_by_stephane": False,
        "has_used_power": False,   # 🔥 FIX : Claire peut ré-agir chaque meeting

    })
    db.commit()

    print(f"🔄 Lancement Meeting {party.meeting_number} — room {code}")
    await broadcast(code, f"next_meeting:{party.meeting_number}")
    await asyncio.sleep(4)

    db_fresh = SessionLocal()
    try:
        await start_meeting(code, db_fresh)
    except Exception as e:
        print(f"❌ Erreur start_meeting : {e}")
    finally:
        db_fresh.close()
        
        
async def _handle_abdel_eliminated(code: str, party, abdel, db, came_from_vote: bool = False):
    infectes = db.query(Player).filter(
        Player.party_id == party.id,
        Player.virus_from_abdel == True,
        Player.is_alive == True
    ).all()

    # 🔥 Marquer AVANT tout broadcast pour bloquer next_phase
    party.current_defi_id = None
    party.meeting_phase  = "vote_defi"
    party.defi_sub_phase = "abdel_processing"
    db.commit()

    # Broadcaster le résultat du défi d'Abdel
    await broadcast(code, "defi_result:fail")

    if not infectes:
        party.defi_sub_phase = None
        db.commit()
        await broadcast(code, "phase:feedback:pre_vote")
        return

    victims_with_joker    = [v for v in infectes if not v.has_drawn_corpocard]
    victims_without_joker = [v for v in infectes if v.has_drawn_corpocard]

    # 🔥 FIX : mettre à jour last_eliminated_id/turn_order AVANT le broadcast abdel_reveal
    # pour que feedback_defi.html (qui se charge dès qu'il reçoit abdel_reveal)
    # trouve déjà la bonne victime via /party/meeting_victim
    if victims_with_joker:
        victim_ids = [v.id for v in victims_with_joker]
        party.last_eliminated_id = victim_ids[0]
        party.turn_order         = json.dumps(victim_ids)
        party.current_turn       = 0
    else:
        party.last_eliminated_id = None
        party.turn_order         = None
        party.current_turn       = 0
    db.commit()

    await asyncio.sleep(2)
    noms = ", ".join([p.pseudo for p in infectes])
    await broadcast(code, f"abdel_reveal:{abdel.pseudo}:{noms}")
    await asyncio.sleep(3)

    for v in victims_without_joker:
        v.is_alive = False
    db.commit()

    for v in victims_without_joker:
        await broadcast(code, f"player_eliminated_direct:{v.pseudo}:{v.role}")
    if victims_without_joker:
        await asyncio.sleep(2)

    alive = db.query(Player).filter(Player.party_id == party.id, Player.is_alive == True).all()
    if not [p for p in alive if p.is_manager]:
        await broadcast(code, "game_over:victoire_collabs")
        return
    if not [p for p in alive if not p.is_manager]:
        await broadcast(code, "game_over:victoire_managers")
        return

    if victims_with_joker:
        party.meeting_phase  = "vote_defi"
        party.defi_sub_phase = "running_from_vote" if came_from_vote else "running_from_meeting"
        db.commit()
        await broadcast(code, "phase:defi_decision")
    else:
        if came_from_vote:
            await _launch_next_meeting(code, party.id, db)
        else:
            party.meeting_phase = "feedback"
            db.commit()
            await broadcast(code, "phase:feedback:pre_vote")
# ---------------------------------------------------------
# RÉCUPÉRER LA VICTIME DU MEETING en cours (pour feedback_defi)
# ---------------------------------------------------------
@router.get("/meeting_victim/{code}")
def get_meeting_victim(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    if not party.last_eliminated_id:
        return {"victim": None}

    victim = db.query(Player).filter(Player.id == party.last_eliminated_id).first()
    if not victim:
        return {"victim": None}

    return {
        "victim": {
            "id": victim.id,
            "player_id": victim.id,
            "pseudo": victim.pseudo,
            "role": victim.role,
            "is_alive": victim.is_alive,
            "has_drawn_corpocard": victim.has_drawn_corpocard
        }
    }


# ---------------------------------------------------------
# LANCER LE MEETING SUIVANT
# ---------------------------------------------------------
@router.post("/next_meeting/{code}")
async def next_meeting(code: str, db: Session = Depends(get_db)):
    party = db.query(Party).filter(Party.code == code).first()
    if not party:
        raise HTTPException(404, "Partie introuvable")

    party.meeting_number += 1
    party.meeting_phase = "waiting"
    party.defi_sub_phase = None
    party.turn_order = None
    party.current_turn = 0
    party.last_eliminated_id = None

    # Reset des flags de victime pour le nouveau meeting
    db.query(Player).filter(Player.party_id == party.id).update({
        "victim_of_managers": False,
        "victim_of_claire": False,
        "fired_by_stephane": False,
        "has_used_power": False,   # 🔥 FIX : Claire peut ré-agir chaque meeting

    })
    db.commit()

    print(f"🔄 Passage au Meeting {party.meeting_number} pour la room {code}")
    await broadcast(code, f"next_meeting:{party.meeting_number}")
    await asyncio.sleep(3)

    db_fresh = SessionLocal()
    try:
        await start_meeting(code, db_fresh)
    except Exception as e:
        print(f"❌ Erreur start_meeting : {e}")
    finally:
        db_fresh.close()

    return {"message": f"Meeting {party.meeting_number} lancé"}