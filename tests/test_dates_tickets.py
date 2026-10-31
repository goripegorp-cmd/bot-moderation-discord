"""31/10/2026, le fondateur : « la création des tickets… ça nous dit que ça a été créé il y a 7 ans, alors qu'ils ont été
créés à l'instant ». Sur une base ancienne, la colonne `created_at` a pour défaut le 01/01/2020."""
import re
import sqlite3
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
EPOQUE_DISCORD_MS = 1420070400000


def _flocon(t_unix: int) -> int:
    return (t_unix * 1000 - EPOQUE_DISCORD_MS) << 22


def test_D1_chaque_ticket_ecrit_sa_date():
    inserts = re.findall(r"INSERT INTO tickets\([^)]*\)", SRC)
    assert len(inserts) == 2 and all("created_at" in i for i in inserts)


def test_D2_les_dates_faussees_reprennent_celle_du_salon():
    sql = re.search(r'"(UPDATE tickets SET created_at = datetime\(.*?)"\)', SRC.replace('"\n                "', ""), re.S).group(1)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, channel_id INTEGER, created_at DATETIME DEFAULT '2020-01-01 00:00:00')")
    vrai = 1_761_900_000                                       # 31/10/2025 08:40 UTC
    db.execute("INSERT INTO tickets(channel_id) VALUES (?)", (_flocon(vrai),))                       # né avec le défaut 2020
    db.execute("INSERT INTO tickets(channel_id, created_at) VALUES (?, datetime(?, 'unixepoch'))",
               (_flocon(vrai), vrai + 5 * 86400))                                                  # rattrapé au démarrage
    db.execute("INSERT INTO tickets(channel_id, created_at) VALUES (?, datetime(?, 'unixepoch'))",
               (_flocon(vrai), vrai + 20))                                                         # juste : intouché
    db.execute(sql)
    dates = [r[0] for r in db.execute("SELECT strftime('%s', created_at) FROM tickets ORDER BY id")]
    assert [int(x) for x in dates] == [vrai, vrai, vrai + 20]
