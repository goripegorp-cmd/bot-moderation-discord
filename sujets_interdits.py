"""sujets_interdits.py — les SUJETS INTERDITS du serveur : religion, politique, extrémisme (27/10/2026).

Le fondateur : « Tout ce qui est à des fins religieuses, présidentielles, tout ce qui est prière […] catholiques,
machin, tout ce qui est à l'extrême […] tu bloques tout […] même des gifs. » Précisé le même jour : « omg », « oh my
god », « mon dieu » restent PERMIS (la surprise), sauf si la suite parle vraiment d'un dieu ou d'une religion ;
« wallah » et toutes ses formes sont BLOQUÉS, comme tout serment, toute formule ou bénédiction religieuse, dans toutes
les langues et toutes les religions.

C'est l'interdiction d'un SUJET, jamais d'une cible : une même fonction (surprise, serment, formule, prière,
prosélytisme, débat) a le même verdict quelle que soit la langue ou la religion, et tous les bords politiques sont
traités pareil (tests/test_sujets_interdits.py, les symétries).

Trois catégories, chacune en familles (`FAMILLES` : catégorie, active par défaut) :
  religion   : priere · formule · serment · proselytisme · debat · symbole · pratique et figure (GIF) ·
               surprise (PERMISE par défaut) · salutation (PERMISE par défaut : « salam », « shalom »…)
  politique  : election · figure · parti · slogan · histoire (Hitler, nazis, croix gammée NOMMÉS : retirés, pas punis)
  extremisme : la plus grave — apologie du terrorisme, nazisme revendiqué, slogans de haine, symboles. Le bot la
               sanctionne comme une insulte haineuse.

Le jugement : le texte est PLIÉ (minuscules, sans accents, homoglyphes, chiffres pour des lettres « w4ll4h », lettres
espacées « w a l l a h », lettres répétées « amennnn »), les EXCEPTIONS sont retirées (« god of war », « je t'en
prie », « président du club »…), puis les expressions SÛRES (une seule suffit). Un mot AMBIGU seul ne suffit jamais
dans un message (« il joue comme un dieu », « la bible du jeu », « le président du club ») : il en faut deux, ou une
surprise suivie d'un mot religieux (« mon dieu, va à la messe »). Dans un GIF, le titre DÉSIGNE l'image : un nom de
figure religieuse (« jesus », « allah ») ou une pratique (« praying ») suffit.

Les listes vivent ici, dans le code. Un serveur peut les ajuster par sa configuration, clé `sujets_interdits` :
{"categories": {"politique": false}, "familles": {"surprise": true}, "mots": {"religion": ["…"]},
 "exceptions": ["…"]} — couper une catégorie ou une famille, ajouter des mots, des exceptions. 100 % FAIL-SAFE :
une erreur rend « rien trouvé », jamais une exception dans on_message.
"""
from __future__ import annotations

import functools
import re
import unicodedata

CATEGORIES = ("religion", "politique", "extremisme")

# famille → (catégorie, active par défaut)
FAMILLES = {
    "priere": ("religion", True), "formule": ("religion", True), "serment": ("religion", True),
    "proselytisme": ("religion", True), "debat": ("religion", True), "symbole": ("religion", True),
    "pratique": ("religion", True), "figure_religieuse": ("religion", True),
    "surprise": ("religion", False), "salutation": ("religion", False),
    "election": ("politique", True), "figure_politique": ("politique", True), "parti": ("politique", True),
    "slogan": ("politique", True), "histoire": ("politique", True),
    "terrorisme": ("extremisme", True), "nazisme": ("extremisme", True), "haine": ("extremisme", True),
    "symbole_haineux": ("extremisme", True),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  LES LISTES (formes PLIÉES : minuscules, sans accents, apostrophes et tirets en espaces)
# ═══════════════════════════════════════════════════════════════════════════════

PRIERE = """
notre pere qui es aux cieux | notre pere qui etes aux cieux | que ton nom soit sanctifie | que votre nom soit sanctifie
que ton regne vienne | je vous salue marie | pleine de grace | sainte marie mere de dieu | priez pour nous
au nom du pere | et du fils et du saint esprit | gloire au pere | our father who art in heaven | hallowed be thy name
thy kingdom come | hail mary full of grace | in the name of the father | padre nuestro | santificado sea tu nombre
dios te salve maria | ave maria | pater noster | la ilaha illallah | la ilaha illa allah | ashhadu an la ilaha
al fatiha | sourate al fatiha | bismillah ar rahman ar rahim | bismillahi rahmani rahim | shema israel | shema yisrael
baruch atah adonai | om namah shivaya | hare krishna | hare rama | om mani padme hum | nam myoho renge kyo
je prie pour | je prierai pour | je vais prier pour | on prie pour | prions pour | prions ensemble | prie pour moi
prie pour lui | prie pour elle | prie pour nous | prie pour eux | prie pour toi | priez pour | prions le seigneur
prions dieu | prie dieu | priez dieu | prier dieu | prier allah | prie allah | priez allah | faire la priere
faire ma priere | faire sa priere | je fais ma priere | l heure de la priere | i pray for | i ll pray for | ill pray for
i will pray for | pray for | praying for | let us pray | lets pray | keep praying | pray to god | pray to allah
pray to jesus | say a prayer | my prayers | our prayers | prayers to | thoughts and prayers | rezo por | rezare por
reza por | oremos | vamos a rezar
"""

FORMULE = """
si dieu le veut | dieu merci | grace a dieu | merci mon dieu | merci seigneur | merci a dieu | que dieu te benisse
que dieu vous benisse | dieu te benisse | dieu vous benisse | que dieu te garde | que dieu vous garde
que dieu te protege | que dieu vous protege | dieu te garde | dieu te protege | que dieu le benisse | dieu est grand
gloire a dieu | louange a dieu | dieu soit loue | dieu soit beni | le seigneur soit loue | loue soit dieu
beni soit dieu | alleluia | alleluja | hallelujah | halleluja | amen | god bless | god bless you | god bless america
thank god | thanks god | thank the lord | praise the lord | praise god | praise jesus | praise allah | praise be
god willing | lord willing | god is great | god is good | glory to god | glory be to god | bless the lord
si dios quiere | gracias a dios | dios te bendiga | dios los bendiga | bendito sea dios | gloria a dios | gott sei dank
grazie a dio | gracas a deus | se deus quiser | deus abencoe | deus te abencoe
inchallah | inshallah | inch allah | insh allah | in sha allah | insha allah | inshaallah | inchaallah | nchallah
inchalah | inshalah | incha allah | in shaa allah
hamdoulilah | hamdoulillah | hamdoulah | hamdoullah | hamdullah | hamdulillah | alhamdulillah | alhamdoulillah
el hamdoulillah | al hamdoulillah | el hamdoulilah | al hamdulillah | lhamdoulilah | lhamdoullah | hamdulilah
el hamdoulah | hamdolillah
machallah | mashallah | masha allah | ma sha allah | machaallah | mashaallah | macha allah | machalah | mashalah
bismillah | bismilah | bissmillah | besmellah | bsmellah | bismi allah | bismi llah
subhanallah | subhan allah | soubhanallah | sobhanallah | soubhan allah | subhanalah
astaghfirullah | astaghfirallah | astaghfiroullah | astaghfirulah | astaghfirlah | starfoullah | starfoulah
starfallah | staghfirullah | astarfighullah | astarfoullah | estaghfirullah | astaghfirou allah
allahu akbar | allah akbar | allahou akbar | allah ou akbar | allah wakbar | allahuakbar | allahouakbar | takbir
barakallahu fik | barakallahu fiki | barakallah | barak allah | baraka allah | baraka allahu fik | barakalah
jazakallah | jazak allah | jazakallahu khayran | jazak allahu khair | allah y rahmo | allah yarhamou | allah yerhamo
allah yarhmo | rahimahullah | allah yehdik | allah ybarek | allah yhfdek | allah yahfdek | allah y hfdek
allah yster | rabi yhfdek | allah ihfdek | allah yjazik | baruch hashem | b ezrat hashem | be ezrat hashem
im yirtzeh hashem | jai shri ram | jai shree ram | waheguru | har har mahadev
"""

SERMENT = """
billah | wallah el3adim | wallah el adim | wallah al adim | wallahi el adhim | je jure sur dieu
je te jure sur dieu | je vous jure sur dieu | jure sur dieu | je le jure sur dieu | devant dieu | je jure devant dieu
sur le coran | sur la bible | sur la torah | je jure sur le coran | je jure sur la bible | sur la mecque | sur allah
je jure sur allah | sur dieu | i swear to god | swear to god | swear on god | i swear on god | swear to allah
i swear on the bible | swear on the bible | swear on the quran | on god | hand to god | as god is my witness
te lo juro por dios | juro por dios | lo juro por dios | por dios | ich schwore bei gott | giuro su dio | juro por deus
"""

PROSELYTISME = """
convertis toi | convertissez vous | convertis toi a | jesus t aime | jesus vous aime | jesus t a sauve | dieu t aime
dieu vous aime | allah t aime | allah vous aime | god loves you | jesus loves you | allah loves you | jesus saves
jesus is lord | jesus is the way | jesus est le chemin | jesus revient | jesus is coming | jesus est mort pour
jesus died for | mort pour nos peches | died for our sins | accepte jesus | accept jesus | repentez vous | repens toi
lis la bible | lisez la bible | lis le coran | lisez le coran | lis la torah | lisez la torah | read the bible
read the quran | read the torah | va a la messe | allez a la messe | va a l eglise | allez a l eglise
va a la mosquee | allez a la mosquee | va a la synagogue | viens a l eglise | viens a la mosquee | go to church
go to the mosque | rejoins l islam | embrasse l islam | reviens a l islam | revert to islam | convert to islam
convert to christianity | le seul vrai dieu | the one true god | la vraie religion | the true religion
l islam est la verite | islam is the truth | la bible dit | le coran dit | the bible says | the quran says
selon la bible | selon le coran | dieu existe | god exists | god is real | allah est le seul
il n y a de dieu que dieu | jesus est le fils de dieu | jesus is the son of god | le paradis t attend | tu iras en enfer
you will go to hell | brulera en enfer | burn in hell
"""

DEBAT = """
dieu n existe pas | god is not real | god isn t real | god doesn t exist | god is dead | dieu est mort
la religion c est | les religions c est | religion is | religions are | ta religion | votre religion | sa religion
leur religion | your religion | quelle religion | religion de paix | religion of peace | toutes les religions
l islam c est | le christianisme c est | le judaisme c est | la bible c est | le coran c est | la bible est
le coran est | la torah est | islam is | christianity is | judaism is | the bible is | the quran is
"""

# « je suis musulman », « t'es juif », « les chrétiens sont… » : une MÊME phrase pour chaque religion, construite.
_GROUPES = ("musulman musulmane musulmans musulmanes chretien chretienne chretiens chretiennes juif juive juifs juives "
            "catholique catholiques protestant protestante protestants athee athees bouddhiste bouddhistes hindou "
            "hindoue hindous evangelique evangeliques croyant croyante croyants mecreant mecreants sikh sikhs mormon "
            "mormons salafiste salafistes").split()
_GROUPES_EN = "muslim christian jewish jew catholic atheist buddhist hindu protestant mormon sikh".split()
_GROUPES_EN_PL = "muslims christians jews catholics atheists buddhists hindus protestants mormons sikhs".split()
_SUJETS_FR = ("je suis | j suis | chuis | t es | tu es | tes | il est | elle est | on est | nous sommes | vous etes "
              "| ils sont | elles sont | t etais | il etait").split(" | ")
_SUJETS_EN = "i m | im | i am | you re | youre | you are | he is | hes | she is | shes | they are | theyre | we are".split(" | ")
_RELIGIONS_FR = ("l islam | le christianisme | le judaisme | le bouddhisme | l hindouisme | le catholicisme "
                 "| le protestantisme | l atheisme | la religion | les religions").split(" | ")


def _debat_construit() -> list:
    out = []
    for s in _SUJETS_FR:
        for g in _GROUPES:
            out += [f"{s} {g}", f"{s} un {g}", f"{s} une {g}", f"{s} pas {g}"]
    for g in _GROUPES:
        if g.endswith("s"):
            out += [f"les {g} sont", f"les {g} c est", f"les {g} ont", f"tous les {g}", f"toutes les {g}"]
    for r in _RELIGIONS_FR:
        out += [f"{r} est", f"{r} c est", f"{r} n est", f"{r} sera"]
    for s in _SUJETS_EN:
        for g in _GROUPES_EN:
            out += [f"{s} {g}", f"{s} a {g}", f"{s} an {g}", f"{s} not {g}"]
    for g in _GROUPES_EN_PL:
        out += [f"{g} are", f"all {g}"]
    for s in ("soy", "eres", "es", "somos"):
        for g in ("musulman", "musulmana", "cristiano", "cristiana", "judio", "judia", "catolico", "catolica", "ateo",
                  "atea"):
            out.append(f"{s} {g}")
    return out


# Symboles (les variantes d'émoji « ️ » sont retirées avant). 🙏 n'en est pas un : « merci », « s'il te plaît ».
SYMBOLES_RELIGION = frozenset("✝✞✟☦☪✡🕉☸☬🛐📿⛪🕌🕍🕋")
SYMBOLES_HAINE = frozenset("卐卍࿕࿖")
SYMBOLES_HAINE_SUITES = ("ϟϟ", "ᛋᛋ")

# Les mots AMBIGUS seuls : il en faut deux dans un message (ou une surprise suivie de l'un d'eux) ; dans un GIF, un
# seul suffit (le titre désigne l'image). « dieu », « god », « seigneur », « paradis », « enfer », « ange »… n'en
# sont PAS : ils sont partout dans le jeu.
PRATIQUES = """
priere prieres prier prie priez prions pray prays prayed praying prayer prayers worship worshipping eglise eglises
church churches cathedrale cathedral mosquee mosquees mosque mosques synagogue synagogues messe bible bibles coran
quran koran torah talmud evangile gospel religion religions religieux religieuse religious ramadan careme hijab burqa
kippa crucifix chapelet rosaire rosary bapteme baptism communion islam islamique islamic christianisme christianity
judaisme judaism bouddhisme buddhism hindouisme hinduism catholicisme catholicism catholique catholiques catholic
catholics chretien chretiens chretienne chretiennes christians musulman musulmans musulmane musulmanes muslim
muslims juif juifs juive juives jew jews jewish protestant protestants evangelique evangeliques bouddhiste
bouddhistes buddhist buddhists hindou hindous hindu hindus athee athees atheisme atheist atheists atheism croyant
croyants mecreant mecreants kouffar kafir kuffar apostat sikh sikhs mormon mormons jehovah imam imams mollah mufti
cure pretre pretres priest priests rabbin rabbins rabbi pape pope eveque nonne nun nuns iglesia misa rezar oracion
biblia jihad djihad
"""
FIGURES_RELIGIEUSES = """
jesus | christ | jesus christ | allah | mahomet | le prophete | rasoul allah | rasulullah | bouddha | buddha | krishna
vishnu | ganesh | ganesha | vierge marie | virgin mary | sainte vierge | pope francis | pape francois | dalai lama
yahweh | yhwh
"""

# Les SURPRISES (permises par défaut) : la même fonction dans toutes les langues. Les formes « nom seul » (jesus,
# christ) ne valent surprise qu'en début ou fin de message, ou entre deux ponctuations — et jamais dans un GIF.
SURPRISES = """
oh my god | omg | omfg | oh my lord | my god | my lord | oh god | oh lord | good god | good lord | dear god | dear lord
god damn | goddamn | god dammit | jeez | geez | mon dieu | oh mon dieu | bon dieu | nom de dieu | mais mon dieu
mon dieux | dios mio | ay dios mio | oh dios | ay dios | dios santo | madre de dios | mein gott | oh mein gott
o mio dio | oddio | dio mio | meu deus | ai meu deus | nossa senhora | ya allah | ya rabbi | ya rabi | ya rab
"""
SURPRISES_NOM = "jesus christ | sweet jesus | doux jesus | jesus marie joseph | jesus | christ"

SALUTATIONS = """
salam aleykoum | salam alaykoum | salam alaykum | salam aleikoum | salamalekoum | salamalikoum | assalamu alaykum
assalamou alaykoum | as salam alaykoum | wa alaykoum salam | waleykoum salam | aleykoum salam | shalom aleichem
shabbat shalom | que la paix soit avec vous | que la paix soit avec toi | peace be upon you | sat sri akal
namaste | mazel tov
"""

FIGURES_POLITIQUES = """
macron | emmanuel macron | brigitte macron | le pen | marine le pen | jean marie le pen | marion marechal | bardella
jordan bardella | melenchon | jean luc melenchon | zemmour | eric zemmour | sarkozy | nicolas sarkozy
francois hollande | gabriel attal | elisabeth borne | edouard philippe | bayrou | francois bayrou | retailleau
darmanin | gerald darmanin | francois ruffin | glucksmann | raphael glucksmann | fabien roussel | marine tondelier
ciotti | eric ciotti | wauquiez | michel barnier | lecornu | dupont aignan | philippot | mathilde panot
manuel bompard | sandrine rousseau | olivier faure | chirac | jacques chirac | mitterrand | poutine
vladimir poutine | putin | vladimir putin | zelensky | zelenski | zelenskyy | trump | donald trump | biden
joe biden | kamala harris | obama | barack obama | hillary clinton | netanyahu | netanyahou | erdogan | xi jinping
kim jong un | khamenei | jd vance | desantis | ron desantis | bolsonaro | lula da silva | milei | javier milei
meloni | giorgia meloni | orban | viktor orban | pedro sanchez | keir starmer | boris johnson | rishi sunak | merkel
angela merkel | olaf scholz | maduro | nicolas maduro | bachar el assad | bashar al assad | kadyrov | loukachenko
lukashenko | narendra modi | nigel farage | tebboune
"""
PARTIS = """
rassemblement national | le rn | du rn | au rn | lfi | la france insoumise | france insoumise | les insoumis
parti renaissance | la republique en marche | lrem | les republicains | reconquete | parti socialiste | eelv
les ecologistes | nupes | nouveau front populaire | front national | parti communiste | pcf | lutte ouvriere
debout la france | maga | gop | labour party | tory | tories | afd | democrat party | republican party
"""
ELECTION = """
presidentielle | presidentielles | election presidentielle | elections presidentielles | legislatives
elections legislatives | elections municipales | elections europeennes | elections regionales | les municipales
les europeennes | second tour de la presidentielle | premier tour de la presidentielle | campagne presidentielle
president de la republique | premier ministre | assemblee nationale | 49 3 | reforme des retraites | loi immigration
vote blanc | votez blanc | allez voter | aller voter | va voter | bulletin de vote | isoloir | presidential election
election day | midterms | extreme droite | extreme gauche | ultra droite | ultradroite | ultragauche | ultra gauche
far right | far left | gauchiste | gauchistes | droitard | droitards | facho | fachos | fasciste | fascistes
islamo gauchiste | islamogauchiste | wokiste | wokistes
"""
HISTOIRE = "hitler | adolf hitler | nazi | nazis | neo nazi | croix gammee | swastika | troisieme reich | third reich | mussolini | goebbels | himmler"
POLITIQUE_FAIBLE = """
president presidente presidents presidence election elections electoral electorale voter votez vote votes votons
candidat candidate candidats campagne scrutin depute deputes deputee senat senateur senateurs ministre ministres
gouvernement parlement parti partis politique politiques politicien politiciens manif manifestation manifestations
greve greves democratie dictature dictateur republique reforme government senate congress democrat democrats
republican republicans leftist leftists
"""
POLITIQUE_FAIBLE_PHRASES = "la gauche | la droite | de gauche | de droite | vote pour | votez pour | vote for | left wing | right wing"
# Un de ces mots dans le message : « président », « élection », « vote »… parlent du jeu ou du serveur, pas de politique.
POLITIQUE_CONTEXTE_JEU = frozenset("""
club sondage sondages build builds meilleur meilleure serveur discord staff guilde clan equipe team classe delegue
delegues bde asso association concours tournoi miss jeu game partie mvp skin carte map mode saison ligue league match
ranked event evenement roleplay rp joueur joueurs perso personnage
""".split())

NAZISME = """
heil hitler | sieg heil | hitler avait raison | hitler a eu raison | hitler had a point | hitler was right
hitler did nothing wrong | vive hitler | vive le reich | vive le troisieme reich | 1488 | 14 88 | white power
white pride | white pride world wide | wpww | hh 88
"""
TERRORISME = """
vive daesh | vive l etat islamique | vive l ei | vive al qaida | vive al qaeda | vive le hamas | vive le hezbollah
vive le jihad | vive le djihad | long live isis | long live hamas | long live hezbollah | glory to hamas
glory to isis | go hamas | les terroristes ont raison | les terroristes avaient raison | bien fait pour charlie
"""
HAINE = """
mort aux juifs | mort aux arabes | mort aux musulmans | mort aux chretiens | mort aux noirs | mort aux blancs
mort aux gays | mort aux pd | mort aux juives | death to jews | death to muslims | death to christians
death to arabs | death to blacks | death to whites | death to gays | kill all jews | kill all muslims
kill all christians | kill all arabs | kill all blacks | kill all whites | kill all gays | gas the jews
holocaust never happened | the holocaust is a lie | holohoax | l holocauste n a jamais existe
la shoah n a jamais existe | la shoah est un mensonge | l holocauste est un mensonge
"""

# Les anciens slogans (`offtopic_lexicon.json`, 387, revus contre les faux positifs du jeu) : la plupart politiques ;
# ceux-ci sont de la haine ou du terrorisme, ceux-là religieux.
_SLOGANS_EXTREMISME = frozenset("""
accelerationism | accelerationist | atomwaffen | atomwaffen division | blood and honour | blood and soil
day of the rope | death to america | death to america death to israel | death to israel | death to the infidels
death to the kuffar | death to the unbelievers | feuerkrieg | fourteen words | gas the jews | heil hitler
jews will not replace us | kill all kuffar | ku klux klan | misanthropic division | mort a israel | mort aux arabes
mort aux infideles | mort aux juifs | mort aux mecreants | neo nazi | neonazi | neonazis | order of nine angles
race war now | rahowa | rapefugees | remove kebab | sieg heil | sonnenkrieg | stormfront | the fourteen words
total aryan victory | white genocide | white sharia | you will not replace us | khaybar khaybar ya yahud
tradwife reich | patriot front | proud boys | oath keepers | boogaloo boys | deus vult kebab
""".replace("\n", " | ").split(" | ")) - {""}
_SLOGANS_RELIGION = frozenset("""
dawah team | jehovah witnesses | jehovah s witnesses | temoins de jehovah | opus dei | salafi dawah | tabligh jamaat
tablighi jamaat | watchtower society | westboro | westboro baptist
""".replace("\n", " | ").split(" | ")) - {""}

EXCEPTIONS = """
god of war | god mode | god tier | god roll | god rolls | god gamer | temple run | easter egg | easter eggs
hail mary pass | hail mary play | holy moly | holy cow | je t en prie | je vous en prie | je te prie | je vous prie
gabriel jesus | jesus navas | islam makhachev | muhammad ali | mohamed salah | mohammed salah | christian bale
christian grey | trump card | trump cards | une poutine | la poutine | de la poutine | des poutines | ma poutine
cette poutine | poutine quebecoise | president du club | presidente du club | president du serveur
president de la guilde | president du bde | election du meilleur | election de la meilleure | vote du sondage
votez pour moi | vote pour moi | votez pour le meilleur | vote pour le meilleur | campagne solo | mode campagne
campaign mode | la bible du | c est ma bible | parole d evangile | la mecque du | le pape du | la messe est dite
grand messe | pas tres catholique | grammar nazi | grammar nazis | feminazi | soup nazi | blue lives
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  LE PLIAGE
# ═══════════════════════════════════════════════════════════════════════════════

_ZW = re.compile("[​‌‍⁠﻿­︎️]")
#  Lettres trompeuses (cyrillique, grec) → latines : « Аllаh » écrit avec des « а » cyrilliques.
_HOMO = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
                       "ѕ": "s", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "α": "a", "ο": "o", "ε": "e",
                       "ι": "i", "κ": "k", "ν": "v", "τ": "t", "υ": "u", "ρ": "p"})
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a", "$": "s", "€": "e"}
_LEET_RE = re.compile(r"(?<=[a-z])[0134578@$€]|[0134578@$€](?=[a-z])")
_PONCT_RE = re.compile(r"[.,;:!?¡¿…()\[\]{}\"«»|/\\]+")
_LETTRES_ESPACEES_RE = re.compile(r"(?<![a-z0-9])[a-z](?: [a-z]){2,}(?![a-z0-9])")


def plier(texte: str, garder_ponctuation: bool = False) -> str:
    """« T'es MUSULMAN ?! » → « t es musulman ». Avec `garder_ponctuation`, une ponctuation devient « | » (la place
    d'une surprise : « mon dieu, … »)."""
    t = unicodedata.normalize("NFKC", str(texte or ""))
    t = _ZW.sub("", t).lower().translate(_HOMO)
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    t = re.sub(r"[’'`´ʼ]", " ", t)
    if garder_ponctuation:
        t = _PONCT_RE.sub(" | ", t)
        t = re.sub(r"[^a-z0-9|@$€\s]", " ", t)
    else:
        t = re.sub(r"[^a-z0-9@$€\s]", " ", t)
    return " ".join(t.split())


def _leet(t: str) -> str:
    return _LEET_RE.sub(lambda m: _LEET[m.group(0)], t)


def _sans_repetitions(t: str) -> str:
    return re.sub(r"([a-z])\1+", r"\1", t)


def _variantes(texte: str) -> list:
    """Le texte plié, ses chiffres-lettres, ses lettres espacées recollées, puis sans lettres répétées."""
    a = plier(texte)
    b = _leet(a).replace("@", "a").replace("$", "s").replace("€", "e")
    b = re.sub(r"[@$€]", " ", b)
    c = _LETTRES_ESPACEES_RE.sub(lambda m: m.group(0).replace(" ", ""), b)
    out = []
    for v in (re.sub(r"[@$€]", " ", a), b, c):
        v = " ".join(v.split())
        if v and v not in out:
            out.append(v)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  LES EXPRESSIONS COMPILÉES
# ═══════════════════════════════════════════════════════════════════════════════

def _liste(bloc: str) -> list:
    sep = "|" if "|" in bloc else None
    morceaux = bloc.replace("\n", " | " if sep else " ").split(sep)
    return [" ".join(plier(x).split()) for x in morceaux if plier(x)]


def _rx(phrases) -> re.Pattern | None:
    ps = sorted({p for p in phrases if p}, key=len, reverse=True)
    if not ps:
        return None
    corps = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in ps)
    return re.compile(r"(?<![a-z0-9])(?:" + corps + r")(?![a-z0-9])")


def _rx_doubles(phrases):
    """Les mêmes expressions, lettres répétées réduites (« alllahu akbarrr » ≈ « allahu akbar »)."""
    return _rx({_sans_repetitions(p) for p in phrases})


_RX: dict = {}
_RX_SQ: dict = {}
_ORDRE_SURES = ("symbole_haineux", "haine", "nazisme", "terrorisme", "priere", "formule", "serment", "proselytisme",
                "debat", "election", "figure_politique", "parti", "slogan", "histoire")


def _charger() -> dict:
    """Compile les listes (et les anciens slogans d'`offtopic_filter`). Rend les tailles, pour le journal."""
    import offtopic_filter
    slogans = {" ".join(plier(s).split()) for s in (offtopic_filter._TERMS or ())}
    ext = {plier(s) for s in _SLOGANS_EXTREMISME}
    rel = {plier(s) for s in _SLOGANS_RELIGION}
    sures = {
        "priere": _liste(PRIERE), "formule": _liste(FORMULE), "serment": _liste(SERMENT),
        "proselytisme": _liste(PROSELYTISME) + [s for s in slogans if s in rel],
        "debat": _liste(DEBAT) + [" ".join(x.split()) for x in _debat_construit()],
        "election": _liste(ELECTION), "figure_politique": _liste(FIGURES_POLITIQUES), "parti": _liste(PARTIS),
        "slogan": [s for s in slogans if s not in ext and s not in rel], "histoire": _liste(HISTOIRE),
        "nazisme": _liste(NAZISME), "terrorisme": _liste(TERRORISME),
        "haine": _liste(HAINE) + [s for s in slogans if s in ext],
    }
    _RX.clear()
    _RX_SQ.clear()
    for fam, phrases in sures.items():
        _RX[fam] = _rx(phrases)
        if fam in ("priere", "formule", "serment", "proselytisme", "nazisme", "terrorisme", "haine"):
            _RX_SQ[fam] = _rx_doubles(phrases)
    _RX["surprise"] = _rx(_liste(SURPRISES))
    _RX["surprise_nom"] = _rx(_liste(SURPRISES_NOM))
    _RX["salutation"] = _rx(_liste(SALUTATIONS))
    _RX["exceptions"] = _rx(_liste(EXCEPTIONS))
    _RX["figure_religieuse"] = _rx(_liste(FIGURES_RELIGIEUSES))
    _RX["pratique"] = _rx(PRATIQUES.split())
    _RX["politique_faible"] = _rx(POLITIQUE_FAIBLE.split() + _liste(POLITIQUE_FAIBLE_PHRASES))
    tailles = {f: len(p) for f, p in sures.items()}
    print(f"[SUJETS] listes chargées : {sum(tailles.values())} expressions")
    return tailles


# ═══════════════════════════════════════════════════════════════════════════════
#  « WALLAH » ET SES FORMES
# ═══════════════════════════════════════════════════════════════════════════════
#  Sur un mot sans lettres répétées : wallah → walah, wallahi → walahi, wlh, wollah → wolah, walla → wala, wallay,
#  wouallah, ouallah ; « w4ll4h », « wa2lah », « w'allah », « w.a.l.l.a.h », « w a l l a h » s'y ramènent avant.
#  Jamais « wall », « while », « oula », « voila », « blah ».
_WALLAH_RE = re.compile(r"^(?:(?:w|ou|wou)[aeiou]{0,3}l[aeiou]?h[iy]?e?|wlh|w[ao]la(?:y|ye)?)$")
_WALLAH_DEBUT_RE = re.compile(r"^(?:w|ou|wou)[aeiou]{0,3}l[aeiou]?h")
_BILLAH_RE = re.compile(r"^bil[aeiou]?h[iy]?$")


def _mot_wallah(mot: str) -> bool:
    m = _sans_repetitions(mot.replace("2", "l"))
    return bool(_WALLAH_RE.match(m) or _BILLAH_RE.match(m) or (len(m) <= 16 and _WALLAH_DEBUT_RE.match(m)))


def _wallah(variantes) -> str | None:
    for v in variantes:
        mots = v.split()
        for i, mot in enumerate(mots):
            if _mot_wallah(mot):
                return mot
            #  « w allah », « wa llah », « wal lah » : deux morceaux d'un même mot.
            if i + 1 < len(mots) and len(mot) <= 3 and _mot_wallah(mot + mots[i + 1]):
                return mot + " " + mots[i + 1]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  LE JUGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@functools.lru_cache(maxsize=64)
def _rx_ajoutes(mots: tuple):
    return _rx([" ".join(plier(m).split()) for m in mots if plier(m)])


def _reglages(r) -> tuple:
    """(catégories actives, familles actives, mots ajoutés par catégorie, exceptions ajoutées) — `r` : la clé
    `sujets_interdits` de la configuration du serveur, ou None."""
    r = r if isinstance(r, dict) else {}
    cats = {c: bool((r.get("categories") or {}).get(c, True)) for c in CATEGORIES}
    fams = {f: bool((r.get("familles") or {}).get(f, defaut)) for f, (_c, defaut) in FAMILLES.items()}
    mots = {c: tuple(str(x)[:80] for x in ((r.get("mots") or {}).get(c) or [])[:200]) for c in CATEGORIES}
    exc = tuple(str(x)[:80] for x in (r.get("exceptions") or [])[:200])
    return cats, fams, mots, exc


def _retirer(rx, texte: str) -> str:
    return " ".join(rx.sub(" ", texte).split()) if rx is not None else texte


def _cherche(rx, variantes) -> str | None:
    if rx is None:
        return None
    for v in variantes:
        m = rx.search(v)
        if m:
            return m.group(0)
    return None


def _verdict(famille: str, terme: str) -> dict:
    return {"categorie": FAMILLES[famille][0], "famille": famille, "terme": str(terme or "")[:60]}


def juger(texte: str, *, gif: bool = False, reglages=None) -> dict | None:
    """Le sujet interdit du texte : {"categorie", "famille", "terme"} — ou None. `gif` : le texte est le titre, le
    lien ou le texte lu dans l'image d'un GIF (un seul mot de figure ou de pratique religieuse suffit)."""
    try:
        return _juger(texte, gif, reglages)
    except Exception as ex:  # un filtre ne casse jamais on_message
        print("[SUJETS][E1] jugement impossible")
        print(f"[SUJETS][E1:DETAIL] {type(ex).__name__} {ex}")
        return None


def _juger(texte: str, gif: bool, reglages) -> dict | None:
    if not texte or not _RX:
        return None
    texte = str(texte)[:4000]
    cats, fams, mots, exc = _reglages(reglages)

    def actif(f):
        return fams.get(f, False) and cats.get(FAMILLES[f][0], False)

    # Les symboles se lisent sur le texte brut.
    if actif("symbole_haineux"):
        for s in SYMBOLES_HAINE:
            if s in texte:
                return _verdict("symbole_haineux", s)
        for s in SYMBOLES_HAINE_SUITES:
            if s in texte:
                return _verdict("symbole_haineux", s)
    if actif("symbole"):
        for s in SYMBOLES_RELIGION:
            if s in texte:
                return _verdict("symbole", s)

    variantes = []
    for v in _variantes(texte):
        v = _retirer(_RX.get("exceptions"), v)
        if exc:
            v = _retirer(_rx_ajoutes(exc), v)
        if v and v not in variantes:
            variantes.append(v)
    if not variantes:
        return None
    sq = list(dict.fromkeys(_sans_repetitions(v) for v in variantes))

    # 1) Les mots ajoutés par la direction : sûrs, dans leur catégorie.
    for cat in CATEGORIES:
        if cats[cat] and mots[cat]:
            t = _cherche(_rx_ajoutes(mots[cat]), variantes)
            if t:
                return {"categorie": cat, "famille": "ajoute", "terme": t[:60]}
    # 2) Les expressions sûres, de la plus grave à la moins grave.
    for fam in _ORDRE_SURES:
        if not actif(fam):
            continue
        t = _cherche(_RX.get(fam), variantes) or _cherche(_RX_SQ.get(fam), sq)
        if t:
            return _verdict(fam, t)
        if fam == "serment":
            t = _wallah(variantes)
            if t:
                return _verdict("serment", t)
    if actif("salutation"):
        t = _cherche(_RX.get("salutation"), variantes)
        if t:
            return _verdict("salutation", t)

    # 3) Les surprises : permises, sauf réglage — ou si la suite parle d'une religion.
    reste = variantes[-1]
    surprise = None
    rx_s, rx_nom = _RX.get("surprise"), _RX.get("surprise_nom")
    if rx_s is not None:
        m = rx_s.search(reste)
        if m:
            surprise = m.group(0)
            reste = _retirer(rx_s, reste)
    if rx_nom is not None and not gif:
        ponct = plier(texte, garder_ponctuation=True)
        ponct = _retirer(_RX.get("exceptions"), ponct)
        for m in rx_nom.finditer(ponct):
            avant, apres = ponct[:m.start()].strip(), ponct[m.end():].strip()
            if (not avant or avant.endswith("|")) or (not apres or apres.startswith("|")):
                surprise = surprise or m.group(0)
                reste = " ".join(reste.replace(m.group(0), " ", 1).split())
    if surprise and actif("surprise"):
        return _verdict("surprise", surprise)

    # 4) Les mots ambigus.
    if cats["religion"]:
        trouves = []
        for fam in ("figure_religieuse", "pratique"):
            rx = _RX.get(fam)
            if rx is not None and fams.get(fam, True):
                trouves += [(fam, m.group(0)) for m in rx.finditer(reste)]
        distincts = {t for _f, t in trouves}
        if trouves and (gif or surprise or len(distincts) >= 2):
            fam, t = trouves[0]
            return _verdict("debat" if (len(distincts) >= 2 and not gif) else fam, " · ".join(sorted(distincts))[:60]
                            if len(distincts) >= 2 else t)
    if cats["politique"] and actif("election"):
        rx = _RX.get("politique_faible")
        if rx is not None and not (set(reste.split()) & POLITIQUE_CONTEXTE_JEU):
            distincts = {m.group(0) for m in rx.finditer(reste)}
            if len(distincts) >= 2:
                return _verdict("election", " · ".join(sorted(distincts))[:60])
    return None


_charger()
