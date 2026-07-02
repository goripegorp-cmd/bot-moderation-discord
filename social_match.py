"""
social_match.py — APPARIEMENT CROISÉ de messages (owner 2026-07-02).

Repère 2 personnes DIFFÉRENTES dont les messages se répondent ou se ressemblent, et permet à bot.py
de leur proposer de se réunir :
  • TRADE (strict) : quelqu'un poste un échange, un AUTRE lui RÉPOND → il est intéressé → on peut
    lancer un salon d'échange entre les deux (`trade_reply_match`).
  • GROUPE / AIDE (plus souple) : 2 messages du MÊME type d'activité qui partagent un mot SPÉCIFIQUE
    (hors mots génériques) → on peut mentionner les deux pour qu'ils se réunissent (`note`).

ANTI-FAUX-POSITIF (RÈGLE N°1) : on n'apparie JAMAIS sur des mots génériques (boss, raid, aide, faire,
« ce soir »…) — il faut un token SPÉCIFIQUE partagé (nom de boss/objet/zone), le MÊME type, et une
fenêtre de fraîcheur. Au-delà de FRESH_SEC, bot.py DEMANDE « tu cherches toujours ? » avant d'apparier
(pour clôturer les demandes périmées). Zéro dépendance discord → logique pure, testable.

API :
  note(guild_id, author_id, msg_id, channel_id, kind, text) -> match|None   (kind: 'group'|'help'|'trade')
  trade_reply_match(guild_id, replied_msg_id, replier_id) -> other_author_id|None
  drop(guild_id, author_id)                                                  (clôture : oublie ses demandes)
  tokens(text) -> set[str]                                                    (exposé pour tests)
"""
from __future__ import annotations

import re
import time
import unicodedata

_INDEX: dict = {}            # guild_id -> list[dict(author_id, msg_id, channel_id, ts, kind, tokens)]
_MAX_PER_GUILD = 80
_MAX_AGE_SEC = 2 * 3600      # on oublie un message au-delà de 2 h
FRESH_SEC = 30 * 60          # < 30 min → appariement direct ; au-delà → « toujours besoin ? »

# Mots GÉNÉRIQUES ignorés pour l'appariement : gaming génériques + temporels + stopwords FR/EN.
# Deux messages ne matchent QUE s'ils partagent un mot HORS de cet ensemble (un vrai nom
# de boss/objet/zone) → « boss gelid » vs « boss taupe » ne matchent PAS (ne partagent que « boss »).
_GENERIC = frozenset({
    # gaming génériques
    "boss", "bosses", "raid", "raids", "donjon", "donjons", "dungeon", "dungeons", "farm", "farmer",
    "kill", "tuer", "battre", "vaincre", "mob", "mobs", "event", "events", "quete", "quetes", "quest",
    "stuff", "loot", "drop", "level", "niveau", "niveaux", "grade", "rang", "pvp", "pve", "boss",
    "carry", "rush", "team", "squad", "duo", "trio", "coop", "groupe", "groupes", "group", "partie",
    "manche", "arene", "invasion", "climax", "world", "skin", "skins", "trophee", "elo", "ranked",
    # aide / entraide
    "aide", "aider", "aidez", "help", "besoin", "coup", "main", "sauver", "explique", "expliquer",
    "comprends", "comprendre", "bloque", "bloquer", "galere", "galerer", "probleme", "souci",
    # trade génériques
    "trade", "trades", "trader", "echange", "echanger", "echanges", "vends", "vendre", "achete",
    "acheter", "achat", "vente", "cherche", "chercher", "donne", "donner", "recup", "recuperer",
    "propose", "proposer", "offre", "contre", "contres", "prix", "wtb", "wts", "wtt",
    # coordination génériques
    "veut", "veux", "veulent", "quelqu", "quelqun", "personne", "monde", "joueur", "joueurs", "gens",
    "peut", "peux", "pouvez", "faire", "fait", "faites", "aller", "venir", "rejoindre", "monter",
    "chercher", "trouver", "dispo", "disponible", "libre", "pret", "prete", "prets",
    # temporels (source classique de faux positifs)
    "soir", "soiree", "matin", "aprem", "apres", "midi", "nuit", "jour", "aujourd", "demain", "hier",
    "maintenant", "tantot", "bientot", "heure", "heures", "minute", "minutes", "semaine", "weekend",
    "week", "today", "tonight", "now", "later", "soon",
    # stopwords FR/EN >= 4 lettres (les < 4 sont déjà exclus par la longueur)
    "avec", "pour", "dans", "sans", "sous", "vers", "chez", "entre", "mais", "donc", "alors", "comme",
    "cette", "cela", "leur", "leurs", "nous", "vous", "elle", "elles", "ils", "eux", "mon", "ton",
    "mes", "tes", "ses", "nos", "vos", "quoi", "quel", "quelle", "quels", "quelles", "dont", "plus",
    "moins", "tres", "trop", "bien", "aussi", "encore", "juste", "meme", "tout", "tous", "toute",
    "toutes", "rien", "quand", "parce", "puis", "here", "there", "want", "need", "some", "have",
    "does", "with", "that", "this", "your", "mine", "please", "anyone", "someone",
    # interpellations / familier / salutations (source majeure de FP — revue 2026-07-02)
    "gars", "mecs", "amis", "potes", "poto", "potos", "guys", "folks", "salut", "coucou", "hello",
    "bonjour", "bonsoir", "wesh", "hola", "yolo", "frere", "freros", "reuf", "boug", "bougs",
    "merci", "thanks", "truc", "trucs", "machin", "chose", "choses", "chaud", "chaude", "chauds",
    "jouer", "jouez", "jouons", "joue", "jouent", "play", "playing", "finir", "finish", "fini",
    "perso", "persos", "ensemble", "together", "venez", "viens", "viennent", "vient", "allez",
    "allons", "nouvelle", "nouveau", "nouveaux", "monte", "monter", "rejoins", "rejoint",
    "genre", "style", "grave", "carrement", "direct", "tranquille", "tranquil", "motive",
    "motives", "chill", "voila", "ouais", "faut", "faudrait", "capable", "capables",
    # économie / communauté (aussi génériques que « boss »/« raid » → à exclure)
    "kamas", "gold", "golds", "mesos", "zeny", "berry", "berrys", "robux", "credit", "credits",
    "gemme", "gemmes", "gems", "monnaie", "argent", "money", "coins", "piece", "pieces",
    "guilde", "guildes", "guild", "guilds", "clan", "clans", "alliance", "alliances", "team",
    "serveur", "serveurs", "server", "servers", "discord", "salon", "salons", "channel",
    "daide", "svpl", "siouplait", "veux", "voudrais", "aimerais", "cherchons", "besoins",
    # ── multilingue trade/coordination (owner 2026-07-02 : serveur international) — EN + ES/PT ──
    "selling", "buying", "trading", "sells", "buys", "trades", "offer", "offering", "offers",
    "looking", "swap", "swaps", "swapping", "sale", "sales", "worth", "paying", "giving", "taking",
    "anything", "anyone", "someone", "player", "players", "people", "friend", "friends", "helping",
    "wanna", "gonna", "lemme", "gimme", "trade", "buyer", "seller", "cheap", "offering",
    "vendo", "compro", "cambio", "vender", "comprar", "cambiar", "busco", "cambios", "troca",
    "trocar", "vendendo", "comprando", "quiero", "necesito", "ayuda", "ayudar", "grupo", "partida",
    "hilfe", "suche", "verkaufe", "tausch", "handel", "gruppe", "helfen", "brauche",
    # noms VAGUES (« un truc/objet/des affaires ») — génériques, ne doivent jamais apparier
    "items", "item", "something", "somethin", "things", "thing", "objet", "objets", "objeto",
    "objetos", "cosas", "cosa", "affaires", "affaire", "matos", "stuffs", "gears", "trucs",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _now() -> float:
    return time.time()


def _normalize(text: str) -> str:
    s = (text or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.replace("’", " ").replace("'", " ")


def tokens(text: str) -> set:
    """Mots SPÉCIFIQUES d'un message : >= 5 lettres, AUCUN chiffre (rejette « lvl50 »/« 500k »),
    hors génériques/temporels/familiers/économie/stopwords. C'est sur l'INTERSECTION de ces tokens
    que repose l'appariement → RÈGLE N°1 : un mot filler partagé ne suffit JAMAIS à apparier 2 gens.
    (Seuil 5 : élimine d'office les fillers de 4 lettres — gars/amis/guys/mecs/avec/pour…)"""
    out = set()
    try:
        for w in _TOKEN_RE.findall(_normalize(text)):
            if len(w) >= 5 and not any(c.isdigit() for c in w) and w not in _GENERIC:
                out.add(w)
    except Exception:
        pass
    return out


def _prune(lst: list) -> list:
    cut = _now() - _MAX_AGE_SEC
    return [r for r in lst if r.get("ts", 0) >= cut][-_MAX_PER_GUILD:]


def note(guild_id, author_id, msg_id, channel_id, kind: str, text: str):
    """Enregistre le message dans l'index et retourne un MATCH avec un AUTRE auteur (même type,
    token spécifique partagé, ≤ 2 h), ou None. Le match porte : other_author_id/msg_id/channel_id,
    age_sec (→ bot.py décide direct vs « toujours besoin ? »), shared (mots communs). FAIL-SAFE None."""
    try:
        gid = int(guild_id)
        aid = int(author_id)
        toks = tokens(text)
        lst = _prune(_INDEX.get(gid, []))
        match = None
        # owner 2026-07-02 : 'trade' apparié aussi par SIMILARITÉ (2 messages d'échange qui partagent
        # le même objet), pas seulement par réponse directe (cf. trade_reply_match).
        if kind in ("group", "help", "trade") and toks:
            # message récent d'un AUTRE auteur, MÊME type, partageant un token spécifique (le + récent).
            for r in reversed(lst):
                if r["author_id"] == aid or r["kind"] != kind:
                    continue
                shared = toks & r["tokens"]
                if shared:
                    match = {
                        "kind": kind,
                        "other_author_id": r["author_id"],
                        "other_msg_id": r["msg_id"],
                        "other_channel_id": r["channel_id"],
                        "age_sec": max(0.0, _now() - r["ts"]),
                        "shared": sorted(shared),
                    }
                    break
        lst.append({"author_id": aid, "msg_id": int(msg_id), "channel_id": int(channel_id),
                    "ts": _now(), "kind": kind, "tokens": toks})
        _INDEX[gid] = lst[-_MAX_PER_GUILD:]
        return match
    except Exception:
        return None


def trade_reply_match(guild_id, replied_msg_id, replier_id):
    """Si le message auquel on RÉPOND était un TRADE d'un AUTRE auteur (≤ 2 h) → retourne son
    author_id (celui-ci est intéressé par l'échange). Sinon None. FAIL-SAFE None."""
    try:
        gid = int(guild_id)
        rid = int(replied_msg_id)
        who = int(replier_id)
        cut = _now() - _MAX_AGE_SEC
        for r in _INDEX.get(gid, []):
            if r["msg_id"] == rid and r["kind"] == "trade" and r["author_id"] != who \
                    and r.get("ts", 0) >= cut:
                return r["author_id"]
    except Exception:
        pass
    return None


def drop(guild_id, author_id):
    """Oublie les messages d'un auteur (ex. il a répondu « non, plus besoin » → demande clôturée)."""
    try:
        gid = int(guild_id)
        aid = int(author_id)
        _INDEX[gid] = [r for r in _INDEX.get(gid, []) if r["author_id"] != aid]
    except Exception:
        pass


def drop_msg(guild_id, msg_id):
    """Oublie un message précis (ex. il a servi à un appariement → ne pas ré-apparier)."""
    try:
        gid = int(guild_id)
        mid = int(msg_id)
        _INDEX[gid] = [r for r in _INDEX.get(gid, []) if r["msg_id"] != mid]
    except Exception:
        pass
