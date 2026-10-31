"""28/10/2026 — exigence 11 : « GIF insultants bloqués (lien, titre, texte de l'image) ». Le texte écrit dans un GIF
Tenor / Giphy posté en lien est lu par l'OCR sur l'image de son aperçu, prise par le relais de Discord seulement."""
from __future__ import annotations

import ast
import asyncio
import re
import time
from pathlib import Path

import insult_filter
import offtopic_filter
import sujets_interdits

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


class _Rep:
    status, headers = 200, {"Content-Length": "10"}

    def __init__(self):
        self.content = self

    async def read(self, n):
        return b"image"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session(_Rep):
    def __init__(self, *a, **k):
        super().__init__()

    def get(self, url):
        APPELS.append(url)
        return _Rep()


APPELS, RETIRES, JOURNAL = [], [], []


def _ns(texte_lu):
    class Discord:
        class HTTPException(Exception):
            pass

    class Aiohttp:
        ClientSession = _Session

        @staticmethod
        def ClientTimeout(**k):
            return None

    class Sem:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def cfg(_gid):
        return {}

    async def send_log(g, cle, m, msg, titre, detail):
        JOURNAL.append((cle, titre, detail))

    async def _dormir(_s):
        return None

    class Asyncio:
        sleep = staticmethod(_dormir)

        @staticmethod
        def get_event_loop():
            class L:
                async def run_in_executor(self, _x, f, data):
                    return f(data)
            return L()
    ns = {"re": re, "time": time, "discord": Discord, "aiohttp": Aiohttp, "asyncio": Asyncio, "_OCR_SEM": Sem(), "cfg": cfg,
          "send_log": send_log, "insult_filter": insult_filter, "offtopic_filter": offtopic_filter,
          "sujets_interdits": sujets_interdits, "_normalize_for_scan": lambda t: t, "_logerr": lambda *a, **k: None,
          "ocr_scan": type("O", (), {"available": staticmethod(lambda: True), "image_text": staticmethod(lambda d: texte_lu)})}
    noms = {"_texte_image_interdit", "_retirer_si_texte_interdit", "_ocr_gif_lien", "_HOTES_APERCU", "_GIF_LIEN_RE",
            "_sujet_interdit", "_gif_texte", "_msg_url_slugs", "_URL_INMSG_RE",
            "_lire_apercu", "_ATTENTE_APERCU", "_APERCUS_LUS"}
    for n in ARBRE.body:
        nom = n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
            getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in noms:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _message(proxy):
    class M:
        content = "regarde https://tenor.com/view/drole-gif-123"
        guild = type("G", (), {"id": 1})()
        author = object()
        id = 5

        async def delete(self):
            RETIRES.append(self.id)
    m = M()
    emb = type("E", (), {"thumbnail": type("T", (), {"proxy_url": proxy})(), "image": None})()
    m.embeds = [emb]

    async def relire(_id):
        return m
    m.channel = type("C", (), {"fetch_message": staticmethod(relire)})()
    return m


def test_G1_le_texte_insultant_du_gif_le_retire():
    APPELS.clear(), RETIRES.clear(), JOURNAL.clear()
    ns = _ns("HEIL HITLER")
    asyncio.run(ns["_ocr_gif_lien"](_message("https://images-ext-1.discordapp.net/external/x/tenor.png")))
    assert APPELS and RETIRES == [5] and JOURNAL[-1][1] == "Texte interdit dans un GIF"


def test_G2_un_gif_normal_reste():
    APPELS.clear(), RETIRES.clear()
    ns = _ns("when you finally win")
    asyncio.run(ns["_ocr_gif_lien"](_message("https://media.discordapp.net/x.png")))
    assert APPELS and not RETIRES


def test_G3_jamais_l_hote_du_gif_directement():
    APPELS.clear(), RETIRES.clear()
    ns = _ns("HEIL HITLER")
    asyncio.run(ns["_ocr_gif_lien"](_message("https://media.tenor.com/x.png")))
    asyncio.run(ns["_ocr_gif_lien"](_message("https://evil.example/discordapp.net.png")))
    assert not APPELS and not RETIRES, "seul le relais de Discord est lu"
