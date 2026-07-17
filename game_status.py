"""game_status.py — Détecte si un jeu/plateforme est DOWN (owner 2026-07-17).

DEMANDE OWNER : « quand on est déconnecté d'un coup, que les serveurs sont down, on ne sait pas
pourquoi → on veut voir sur le Discord si le jeu est actif ou non. Poste un message quand c'est
down ; une fois le jeu relancé et que tout va bien, SUPPRIME le message. »

RÉALITÉ EMPIRIQUE (endpoints testés EN DIRECT le 2026-07-17, rien de supposé) :
 • statuspage.io v2 (`/api/v2/status.json`) = format JSON FIABLE : `status.indicator` ∈
   none / minor / major / critical. Universel pour tout service qui l'utilise.
 • Roblox = hébergé sur **status.io** (PAS statuspage) ; aucune API JSON publique trouvable (id
   introuvable), MAIS la page `status.roblox.com` rend un TEXTE lisible (« All Systems Operational »
   quand tout va bien, vs incidents « Investigating / Major Outage / Degraded Performance ») →
   détection par lecture de page, CONSERVATRICE.
 • Steam par-jeu = 403 Cloudflare ; Blizzard/WoW = aucune API publique. → NON auto-détectables
   (l'appelant peut le compléter par un signalement manuel du staff).

BACKENDS :
 • 'statuspage' : GET JSON, up si indicator == 'none', down si minor/major/critical.
 • 'html'       : GET la page (repli via r.jina.ai anti-blocage) ; up si un marqueur OK est présent
   ET aucun marqueur DOWN fort ; down si un marqueur DOWN fort est présent.

⚠️ RÈGLE N°1 (anti-faux-positif) : on ne CONCLUT JAMAIS « down » sur une incertitude. Tout doute
(HTTP≠200, page illisible, ni marqueur OK ni marqueur DOWN) → 'unknown' → l'appelant NE TOUCHE À
RIEN. Et l'appelant exige un DEBOUNCE (N checks 'down' consécutifs) avant de poster. Un message de
statut est de toute façon informatif et s'auto-supprime au retour à la normale → faible nuisance.

Module PUR : aucune dépendance à bot.py.
"""
from __future__ import annotations

from typing import Optional

# game_key -> source de statut. Extensible : pour tout jeu doté d'un statuspage.io, ajouter
#   "<key>": {"type": "statuspage", "url": "https://<sub>.statuspage.io/api/v2/status.json"}
STATUS_SOURCES = {
    "roblox": {
        "type": "html",
        "url": "https://status.roblox.com/",
        "ok_markers": ["all systems operational"],
        "down_markers": [
            "major outage", "major service outage", "partial outage",
            "degraded performance", "service disruption", "we are investigating",
            "identified the issue", "monitoring the",
        ],
    },
    # Exemples prêts à activer si un statuspage.io officiel est confirmé pour ces jeux :
    #   "xxx": {"type": "statuspage", "url": "https://status.xxx.com/api/v2/status.json"},
}


def has_source(game_key: str) -> bool:
    return game_key in STATUS_SOURCES


async def _fetch_text(session, url: str) -> str:
    """GET du texte d'une page. Essai direct puis repli r.jina.ai (anti-blocage Cloudflare),
    même patron que game_updates._fetch_discourse. '' si tout échoue."""
    _hdr = {"User-Agent": "Mozilla/5.0 (compatible; GoRpBot/1.0)"}
    for u in (url, "https://r.jina.ai/" + url):
        try:
            async with session.get(u, headers=_hdr, timeout=15) as r:
                if r.status == 200:
                    return await r.text()
        except Exception:
            continue
    return ""


async def check_status(session, game_key: str) -> tuple[str, str]:
    """Renvoie ('up' | 'down' | 'unknown', description_courte).

    'unknown' = indéterminé → l'appelant ne doit RIEN changer (ni poster, ni supprimer).
    Ne lève JAMAIS.
    """
    src = STATUS_SOURCES.get(game_key)
    if not src:
        return ("unknown", "")
    try:
        _type = src.get("type")
        if _type == "statuspage":
            async with session.get(src["url"], timeout=15) as r:
                if r.status != 200:
                    return ("unknown", "")
                data = await r.json()
            st = (data.get("status") or {}) if isinstance(data, dict) else {}
            ind = str(st.get("indicator") or "").lower()
            desc = str(st.get("description") or "")
            if ind == "none":
                return ("up", desc or "Opérationnel")
            if ind in ("minor", "major", "critical"):
                return ("down", desc or ind)
            return ("unknown", "")

        if _type == "html":
            text = await _fetch_text(session, src["url"])
            if not text:
                return ("unknown", "")
            low = text.lower()
            has_down = any(m in low for m in src.get("down_markers", []))
            has_ok = any(m in low for m in src.get("ok_markers", []))
            # ⚠️ LE SIGNAL POSITIF PRIME (anti-faux-positif — corrigé avant déploiement) :
            # la page status.io affiche EN BAS l'HISTORIQUE des incidents PASSÉS (« Investigating »,
            # « Degraded Performance »…). Si on laissait « down » l'emporter, un incident RÉSOLU dans
            # l'historique déclencherait un faux « down » alors que tout va bien. Or status.io
            # n'affiche la bannière « All Systems Operational » QUE si tout est actuellement vert →
            # sa présence est un « up » définitif, le bruit de l'historique est ignoré.
            if has_ok:
                return ("up", "Opérationnel")
            if has_down:
                return ("down", "Incident en cours")
            return ("unknown", "")
    except Exception:
        return ("unknown", "")
    return ("unknown", "")


__all__ = ["STATUS_SOURCES", "has_source", "check_status"]
