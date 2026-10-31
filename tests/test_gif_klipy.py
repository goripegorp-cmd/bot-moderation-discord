"""31/10/2026 : le GIF https://klipy.com/gifs/django-unchained-negre (texte de l'image : « qui est ce negre sur ce
cheval? »), posté par un membre, est passé alors que le filtre était en ligne.

Rejoué dans le VRAI on_message / on_message_edit, avec la forme d'un message réel du sélecteur de GIF : le contenu est
l'adresse Klipy, l'aperçu « gifv » arrive ensuite par une MODIFICATION du message (même contenu, un embed de plus).
Un membre ordinaire dans un salon ordinaire était bien sanctionné. Mais tout le filtre des insultes est derrière
`if user_immune or is_ticket: return` : le GIF de la tête, du staff (tout rôle placé au niveau du rôle staff ou plus
haut), d'un administrateur, d'un immunisé, ou posté dans un ticket, n'était jamais lu — et la lecture de son image non
plus. La modification qui apporte l'aperçu, elle, n'était jamais jugée (« contenu identique » → sortie)."""
import asyncio
import datetime as dt
import os

import pytest

os.environ.setdefault("FAUX_JETON", "1")
import discord  # noqa: E402
import bot as B  # noqa: E402

URL = "https://klipy.com/gifs/django-unchained-negre"
URL_SANS_MOT = "https://klipy.com/gifs/django-unchained-horse"     # l'insulte n'est que dans l'image
TEXTE_IMAGE = "qui est ce negre sur ce cheval?"
MEMBRE, STAFF, TETE = 401, 501, 781205382923288593
GID = 99031
MAINTENANT = dt.datetime.now(dt.timezone.utc)
JOURNAL: list = []


def note(*a):
    JOURNAL.append(" ".join(str(x) for x in a))


def vu(debut: str) -> bool:
    return any(ligne.startswith(debut) for ligne in JOURNAL)


class Salon:
    def __init__(self, nom="chat"):
        self.id, self.name, self.type, self.category, self.category_id = 555, nom, discord.ChannelType.text, None, None
        self.mention, self.nsfw, self.slowmode_delay, self.guild = "#" + nom, False, 0, None
        self.messages = {}

    async def send(self, *a, **k):
        note("ENVOI")

    def permissions_for(self, x):
        return discord.Permissions.all() if x is GUILDE.me else discord.Permissions.text()

    async def fetch_message(self, i):
        if i not in self.messages:
            raise discord.NotFound(type("R", (), {"status": 404, "reason": "absent"})(), "absent")
        return self.messages[i]

    def history(self, **k):
        async def vide():
            if False:
                yield None
        return vide()

    async def webhooks(self):
        return []


class Membre:
    def __init__(self, i):
        self.id, self.bot, self.name, self.display_name, self.global_name = i, False, f"m{i}", f"m{i}", None
        self.mention, self.roles, self.guild_permissions = f"<@{i}>", [], discord.Permissions.none()
        self.joined_at, self.created_at = MAINTENANT - dt.timedelta(days=200), MAINTENANT - dt.timedelta(days=400)
        self.avatar = self.display_avatar = self.premium_since = self.top_role = self.status = None
        self.public_flags = self.flags = self.communication_disabled_until = self.voice = self.timed_out_until = None
        self.pending, self.guild = False, GUILDE

    def is_timed_out(self):
        return False

    async def timeout(self, *a, **k):
        note("EXCLUSION", k.get("reason", ""))

    async def send(self, *a, **k):
        note("MP")

    async def add_roles(self, *r, **k):
        note("ROLE+")

    async def remove_roles(self, *r, **k):
        note("ROLE-")


class Guilde:
    def __init__(self):
        self.id, self.owner_id, self.name, self.member_count = GID, 1, "essai", 500
        self.roles, self.channels, self.text_channels, self.voice_channels, self.members = [], [], [], [], []
        self.default_role = type("R", (), {"id": GID, "name": "@everyone", "mention": "@everyone"})()
        self.icon = self.premium_subscriber_role = self.system_channel = self.rules_channel = self.me = None

    def get_member(self, i):
        return None

    def get_channel(self, i):
        return None

    def get_role(self, i):
        return None

    def get_thread(self, i):
        return None


GUILDE = Guilde()
_N = [7000]


class Message:
    def __init__(self, texte, auteur, salon, embeds=(), ident=None):
        if ident is None:
            _N[0] += 1
            ident = _N[0]
        self.id, self.content, self.author, self.guild, self.channel = ident, texte, auteur, GUILDE, salon
        self.attachments, self.embeds, self.stickers, self.mentions = [], list(embeds), [], []
        self.role_mentions, self.channel_mentions, self.mention_everyone = [], [], False
        self.reference, self.type, self.webhook_id, self.message_snapshots = None, discord.MessageType.default, None, []
        self.poll, self.created_at, self.edited_at, self.jump_url = None, MAINTENANT, None, "https://discord.com/x"
        self.flags = self.interaction = self.application_id = None
        self.clean_content = self.system_content = texte
        self.pinned, self.tts, self.components = False, False, []

    async def delete(self, **k):
        note("SUPPRIMÉ")
        self.channel.messages.pop(self.id, None)

    async def reply(self, *a, **k):
        note("RÉPONSE")

    async def add_reaction(self, e):
        note("RÉACTION")


def apercu_gifv(url):
    """L'embed que Discord pose sur un GIF Klipy : « gifv », sans titre ; l'image passe par son relais."""
    return discord.Embed.from_dict({
        "type": "gifv", "url": url, "provider": {"name": "Klipy", "url": "https://klipy.com"},
        "thumbnail": {"url": "https://static.klipy.com/ii/a/b/c.webp", "width": 498, "height": 280,
                      "proxy_url": "https://images-ext-1.discordapp.net/external/abc/https/static.klipy.com/ii/a/b/c.webp"},
        "video": {"url": "https://static.klipy.com/ii/a/b/c.mp4", "width": 498, "height": 280,
                  "proxy_url": "https://images-ext-1.discordapp.net/external/def/https/static.klipy.com/ii/a/b/c.mp4"},
    })


@pytest.fixture
def banc(monkeypatch, tmp_path):
    JOURNAL.clear()
    GUILDE.me = Membre(2)
    GUILDE.me.bot, GUILDE.me.guild_permissions = True, discord.Permissions.all()
    # Jamais la base du dépôt (bot.db est suivi par git) ; un pool neuf par essai, fermé à la fin (ses fils aiosqlite
    # retiendraient sinon le processus).
    monkeypatch.setattr(B, "DB_PATH", str(tmp_path / "banc.db"))
    monkeypatch.setattr(B, "_db_pool", B.DBPool(str(tmp_path / "banc.db"), pool_size=2))

    async def faux(*a, **k):
        return False

    async def rien(*a, **k):
        return None

    async def lire_config(gid):
        return {"anti_invite": 1}, True

    async def immunites(gid):
        return {"channels": set(), "users": set(), "roles": set()}

    async def sanction(m, action, dur, raison, g, actor_id=None):
        note("SANCTION", action, raison)

    async def journal(g, genre, auteur, msg, titre, detail=None, *a, **k):
        note("JOURNAL", titre, detail)

    async def alerte(bot, g, ev, **k):
        note("ALERTE", getattr(ev, "name", ev))

    async def lire_apercu(url):
        note("APERÇU LU", url.split("/")[2])
        return b"GIF-KLIPY"

    monkeypatch.setattr(B, "_lire_config", lire_config)
    for nom in ("is_channel_immune", "update_realsy_activity", "_questions_hook", "_check_auto_slow_mode"):
        monkeypatch.setattr(B, nom, faux)
    monkeypatch.setattr(B, "is_ticket_channel", lambda salon: _vrai_si(salon.name.startswith("ticket-")))
    monkeypatch.setattr(B, "_staff_ou_plus", lambda g, m, c: getattr(m, "id", 0) == STAFF)
    monkeypatch.setattr(B, "_get_immunity", immunites)
    monkeypatch.setattr(B, "sanction", sanction)
    monkeypatch.setattr(B, "send_log", journal)
    monkeypatch.setattr(B.ulogger2026, "log_event", alerte)
    monkeypatch.setattr(B.activite_module, "marquer_actif", rien)
    monkeypatch.setattr(B, "_lire_apercu", lire_apercu, raising=False)
    monkeypatch.setattr(B, "_ATTENTE_APERCU", 0, raising=False)
    monkeypatch.setattr(B.ocr_scan, "available", lambda: True)
    monkeypatch.setattr(B.ocr_scan, "image_text", lambda data: TEXTE_IMAGE if data == b"GIF-KLIPY" else "")
    return JOURNAL


async def _vrai_si(oui):
    return oui


async def _fond():
    """Attend les lectures d'image lancées en fond (au plus 5 s)."""
    taches = [t for t in list(B._bg_scan_tasks) if not t.done()]
    if taches:
        await asyncio.wait(taches, timeout=5)


def rejouer(scenario):
    """Un essai = une boucle ; le pool de la base est fermé à la fin."""
    async def tout():
        try:
            await scenario()
        finally:
            await B._db_pool.close_all()
    asyncio.run(tout())


def envoyer(auteur_id, url=URL, salon_nom="chat"):
    """Le message du sélecteur de GIF : l'adresse seule, sans aperçu ; puis l'aperçu arrive par une modification."""
    async def scenario():
        salon = Salon(salon_nom)
        salon.guild = GUILDE
        auteur = Membre(auteur_id)
        avant = Message(url, auteur, salon)
        salon.messages[avant.id] = avant
        await asyncio.wait_for(B.on_message(avant), 20)
        await _fond()
        if avant.id in salon.messages:
            apres = Message(url, auteur, salon, [apercu_gifv(url)], ident=avant.id)
            salon.messages[avant.id] = apres
            await asyncio.wait_for(B.on_message_edit(avant, apres), 20)
            await _fond()
    rejouer(scenario)
    return JOURNAL


def test_K1_le_cas_exact_d_un_membre_est_supprime_et_sanctionne(banc):
    j = envoyer(MEMBRE)
    assert vu("SUPPRIMÉ") and vu("EXCLUSION"), j


def test_K2_le_cas_exact_du_staff_est_supprime_sans_sanction(banc):
    j = envoyer(STAFF)
    assert vu("SUPPRIMÉ"), j
    assert not vu("SANCTION") and not vu("EXCLUSION"), j
    assert any("negre" in l and "lien" in l for l in j if l.startswith("JOURNAL")), j


def test_K3_le_cas_exact_de_la_tete_est_supprime_sans_sanction(banc):
    j = envoyer(TETE)
    assert vu("SUPPRIMÉ"), j
    assert not vu("SANCTION") and not vu("EXCLUSION"), j


def test_K4_dans_un_ticket_le_gif_part_et_l_echelle_compte(banc):
    j = envoyer(MEMBRE, salon_nom="ticket-0042")
    assert vu("SUPPRIMÉ") and vu("SANCTION delete"), j


def test_K5_l_image_seule_suffit_quand_l_apercu_arrive_par_la_modification(banc):
    """L'adresse ne dit rien ; le texte de l'image, lu dans l'aperçu posé APRÈS l'envoi, suffit."""
    j = envoyer(MEMBRE, url=URL_SANS_MOT)
    assert vu("APERÇU LU images-ext-1.discordapp.net"), j          # toujours par le relais de Discord
    assert vu("SUPPRIMÉ"), j
    assert any("negre" in l for l in j if l.startswith("JOURNAL")), j


def test_K6_l_image_seule_suffit_aussi_pour_le_staff(banc):
    j = envoyer(STAFF, url=URL_SANS_MOT)
    assert vu("SUPPRIMÉ"), j
    assert not vu("SANCTION") and not vu("EXCLUSION"), j


@pytest.mark.parametrize("auteur", [MEMBRE, STAFF])
def test_K7_un_gif_innocent_reste(banc, monkeypatch, auteur):
    monkeypatch.setattr(B.ocr_scan, "image_text", lambda data: "yeehaw cowboy")
    j = envoyer(auteur, url="https://klipy.com/gifs/django-unchained-horse")
    assert not vu("SUPPRIMÉ") and not vu("SANCTION"), j


def test_K8_l_image_n_est_lue_qu_une_fois(banc, monkeypatch):
    """L'aperçu est déjà là quand l'envoi relit le message, et la modification le demande aussi : une seule lecture."""
    monkeypatch.setattr(B.ocr_scan, "image_text", lambda data: "yeehaw cowboy")

    async def scenario():
        salon = Salon()
        salon.guild = GUILDE
        auteur = Membre(MEMBRE)
        avant = Message(URL_SANS_MOT, auteur, salon)
        apres = Message(URL_SANS_MOT, auteur, salon, [apercu_gifv(URL_SANS_MOT)], ident=avant.id)
        salon.messages[avant.id] = apres            # l'aperçu est arrivé avant la relecture
        await B.on_message(avant)
        await B.on_message_edit(avant, apres)
        await _fond()
    rejouer(scenario)
    assert sum(1 for ligne in JOURNAL if ligne.startswith("APERÇU LU")) == 1, JOURNAL
