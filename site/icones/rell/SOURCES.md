# Sources des images officielles de RELL Seas

Visuels du jeu **RELL Seas**, du studio **RELL Games** : icônes et rendus hébergés par le wiki
communautaire RELL Seas (Fandom, https://rellseas.fandom.com), logos servis par Roblox et Discord.
Ils restent la propriété de RELL Games. Ils sont utilisés tels quels (recadrés, mis à l'échelle,
convertis en WebP/PNG) sur le **site privé du clan GoRP**, réservé à son fondateur et à sa
direction, avec l'accord du fondateur (25/10/2026) ; ils ne sont pas redistribués ailleurs.
Les descriptions du catalogue sont des résumés en français ; la page source de chaque élément est
dans `donnees_jeu/rell_catalogue.json` (champ `source`).

Tout est fabriqué par `outils/icones_rellseas.py`. Chaque original a été vérifié avant toute
conversion : octets magiques, taille, ouverture complète par Pillow, dimensions. L'empreinte
SHA-256 est celle de l'original reçu.

## Logos (`site/logos/`)

| Fichier | Logo | Demandé à | Image reçue | Téléchargé le | Original | SHA-256 |
|---|---|---|---|---|---|---|
| `logos/rellseas_jeu.webp` | Icône du jeu RELL Seas (Roblox) (https://www.roblox.com/communities/11020595/RELL-Seas) | https://thumbnails.roblox.com/v1/games/icons?universeIds=2738929784&size=512x512&format=Png&isCircular=false | https://tr.rbxcdn.com/180DAY-5c06d38c14c44bb9d04a410068fe0e96/512/512/Image/Png/noFilter | 25/10/2026 20:41 UTC | 512×512 PNG, 276703 o | `55288ecefc118163` |
| `logos/rellseas_groupe.webp` | Groupe Roblox « RELL Seas » (11020595) (https://www.roblox.com/communities/11020595/RELL-Seas) | https://thumbnails.roblox.com/v1/groups/icons?groupIds=11020595&size=420x420&format=Png&isCircular=false | https://tr.rbxcdn.com/180DAY-1860e88e743735228930c9bb6ff05fe5/420/420/Image/Png/noFilter | 25/10/2026 20:41 UTC | 420×420 PNG, 213046 o | `845abf7b99ba6ebc` |
| `logos/rellgames_groupe.webp` | Groupe studio « RELL GAMES » (4939446) (https://www.roblox.com/communities/4939446) | https://thumbnails.roblox.com/v1/groups/icons?groupIds=4939446&size=420x420&format=Png&isCircular=false | https://tr.rbxcdn.com/180DAY-2feb811d77e9fb6ca1cd1d20e680f49f/420/420/Image/Png/noFilter | 25/10/2026 20:41 UTC | 420×420 PNG, 105747 o | `ec2a27cd595ad51f` |
| `logos/rellseas_discord.webp` | Icône du serveur Discord RELL Seas (https://discord.gg/RELLSEAS) | https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512 | https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512 | 25/10/2026 20:41 UTC | 512×512 PNG, 313506 o | `4a819c1820619d59` |

## Icônes et rendus du catalogue (`site/icones/rell/`, `visuels/icones/rell_*.png`)

| Fichier(s) | Élément | Fichier du wiki | Téléchargé le | Original | SHA-256 |
|---|---|---|---|---|---|
| `icones/rell/fruit/love.webp`<br>`visuels/icones/rell_fruit_love.png` | Amour (Love) | [LoveGodFruit.png](https://rellseas.fandom.com/wiki/File:LoveGodFruit.png) — https://static.wikia.nocookie.net/rell-seasw/images/2/24/LoveGodFruit.png/revision/latest?cb=20241229092739&format=original | 25/10/2026 20:39 UTC | 120×120 PNG, 21074 o | `a02df04e6bf8e2ce` |
| `icones/rell/fruit/light.webp`<br>`visuels/icones/rell_fruit_light.png` | Lumière (Light) | [LightGodFruit.png](https://rellseas.fandom.com/wiki/File:LightGodFruit.png) — https://static.wikia.nocookie.net/rell-seasw/images/f/f2/LightGodFruit.png/revision/latest?cb=20241229092739&format=original | 25/10/2026 20:39 UTC | 120×120 PNG, 16760 o | `8c45a61724bdd591` |
| `icones/rell/fruit/giraffe.webp`<br>`visuels/icones/rell_fruit_giraffe.png` | Girafe (Giraffe) | [GiraffeGodFruit.png](https://rellseas.fandom.com/wiki/File:GiraffeGodFruit.png) — https://static.wikia.nocookie.net/rell-seasw/images/7/77/GiraffeGodFruit.png/revision/latest?cb=20241229092739&format=original | 25/10/2026 20:39 UTC | 120×120 PNG, 15077 o | `4ca6ac1cd273ec62` |

## En attente (141)

Listées par le dossier de recherche mais pas encore obtenues. Le CDN des images du wiki
(static.wikia.nocookie.net) répond aux outils automatiques par un défi anti-robot
(Cloudflare) : il n'a pas été contourné. Elles s'importent avec `--depuis` une fois
enregistrées par un navigateur (procédure en tête de `outils/icones_rellseas.py`).

| Élément | Adresse (dossier de recherche ou API du wiki) | Raison |
|---|---|---|
| metier/cooking — Cuisine | https://static.wikia.nocookie.net/rell-seasw/images/b/bb/Cookingicon.png/revision/latest?cb=20260622234132 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/thieving — Vol | https://static.wikia.nocookie.net/rell-seasw/images/2/21/Thievingtalenticon.png/revision/latest?cb=20260622235241 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/navigation — Navigation | https://static.wikia.nocookie.net/rell-seasw/images/9/99/Navigationtalenticon.png/revision/latest?cb=20260622235102 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/fishing — Pêche | https://static.wikia.nocookie.net/rell-seasw/images/0/03/Fishingtalenticon.png/revision/latest?cb=20260622233608 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/crafting — Artisanat | https://static.wikia.nocookie.net/rell-seasw/images/f/f8/Craftingtalenticon.png/revision/latest?cb=20260622234856 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/woodcutting — Bûcheronnage | https://static.wikia.nocookie.net/rell-seasw/images/6/6f/Woodcuttingicon.png/revision/latest?cb=20260622233928 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/mining — Minage | https://static.wikia.nocookie.net/rell-seasw/images/5/55/Miningtalenticon.png/revision/latest?cb=20260622234434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| metier/shipwright — Charpentier naval | https://static.wikia.nocookie.net/rell-seasw/images/6/6b/Shipwrighttalenticon.png/revision/latest?cb=20260622234652 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/human — Humain | https://static.wikia.nocookie.net/rell-seasw/images/6/6e/Human.png/revision/latest?cb=20261025160144 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/beastman — Homme-bête | https://static.wikia.nocookie.net/rell-seasw/images/5/5f/BeastMan_Race.png/revision/latest?cb=20261025150735 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/marinian — Marinien | https://static.wikia.nocookie.net/rell-seasw/images/7/77/Marinian_Race.png/revision/latest?cb=20261025152400 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/avalonian — Avalonien | https://static.wikia.nocookie.net/rell-seasw/images/1/17/Avalonian_Race.png/revision/latest?cb=20261025154306 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/cyborg — Cyborg | https://static.wikia.nocookie.net/rell-seasw/images/f/f9/Cyborg_Race.png/revision/latest?cb=20261025145700 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/giant — Géant | https://static.wikia.nocookie.net/rell-seasw/images/8/8c/GaintRace.png/revision/latest?cb=20261025183132 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/dwarf — Nain | https://static.wikia.nocookie.net/rell-seasw/images/7/7f/DwarfRace.png/revision/latest?cb=20261025183131 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/three_eyes — Trois-Yeux | https://static.wikia.nocookie.net/rell-seasw/images/6/66/ThreeEyesRace.png/revision/latest?cb=20261025182351 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/lunars — Lunars | https://static.wikia.nocookie.net/rell-seasw/images/f/f0/LunarianRace.png.png/revision/latest?cb=20261025183544 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| race/oni — Oni | https://static.wikia.nocookie.net/rell-seasw/images/5/56/OniRace.png/revision/latest?cb=20261025183133 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| faction/pirates — Pirates | https://static.wikia.nocookie.net/rell-seasw/images/8/84/PirateCouncil.png/revision/latest?cb=20241227094259 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| faction/marines — Marine | https://static.wikia.nocookie.net/rell-seasw/images/f/f3/MarineCorps.png/revision/latest?cb=20241227094300 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| faction/revolution — Révolutionnaires | https://static.wikia.nocookie.net/rell-seasw/images/f/f5/ArmsOfRevolution.png/revision/latest?cb=20260326125443 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| faction/gouvernement — Gouvernement mondial | https://static.wikia.nocookie.net/rell-seasw/images/f/fe/WorldSeasGovernment.png/revision/latest?cb=20241227094300 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/health — Santé | https://static.wikia.nocookie.net/rell-seasw/images/d/de/HealthTraitIcon.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/endurance — Endurance | https://static.wikia.nocookie.net/rell-seasw/images/0/0c/StaminaTraitIcon.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/defense — Défense | https://static.wikia.nocookie.net/rell-seasw/images/b/b5/DefenseTraitIcon.png/revision/latest?cb=20261025192900 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/willpower — Volonté | https://static.wikia.nocookie.net/rell-seasw/images/2/20/WillPowerTraitIcon.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/spiritual — Spirituel | https://static.wikia.nocookie.net/rell-seasw/images/d/db/SpiritualTraitIcon.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| trait/luck — Chance | https://static.wikia.nocookie.net/rell-seasw/images/3/3b/LuckTraitIcon.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| classe/light — Léger | https://static.wikia.nocookie.net/rell-seasw/images/0/0b/LightMainClass.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| classe/medium — Moyen | https://static.wikia.nocookie.net/rell-seasw/images/6/69/MediumMainClass.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| classe/heavy — Lourd | https://static.wikia.nocookie.net/rell-seasw/images/7/7f/HeavyMainClass.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| classe/gunman — Tireur | https://static.wikia.nocookie.net/rell-seasw/images/b/be/GunmanMainClass.png/revision/latest?cb=20261025192901 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/rubber — Caoutchouc | https://static.wikia.nocookie.net/rell-seasw/images/8/8d/RubberGodFruit.png/revision/latest?cb=20250703005433 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/quake — Séisme | https://static.wikia.nocookie.net/rell-seasw/images/d/d6/QuakeGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/dough — Pâte | https://static.wikia.nocookie.net/rell-seasw/images/3/37/DoughGodFruit.png/revision/latest?cb=20250703005434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/operation — Opération | https://static.wikia.nocookie.net/rell-seasw/images/b/bc/OperationGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/venom — Venin | https://static.wikia.nocookie.net/rell-seasw/images/9/91/VenomGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/soul — Âme | https://static.wikia.nocookie.net/rell-seasw/images/0/01/SoulGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/paw — Patte | https://static.wikia.nocookie.net/rell-seasw/images/5/55/PawGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/gravity — Gravité | https://static.wikia.nocookie.net/rell-seasw/images/6/64/GravityGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/string — Fil | https://static.wikia.nocookie.net/rell-seasw/images/b/b2/StringGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/barrier — Barrière | https://static.wikia.nocookie.net/rell-seasw/images/c/c9/BarrierGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/revive — Résurrection | https://static.wikia.nocookie.net/rell-seasw/images/d/dc/ReviveGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/bomb — Bombe | https://static.wikia.nocookie.net/rell-seasw/images/2/2b/BombGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/chop — Découpe | https://static.wikia.nocookie.net/rell-seasw/images/d/d9/ChopGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/flame — Flamme | https://static.wikia.nocookie.net/rell-seasw/images/7/78/FlameGodFruit.png/revision/latest?cb=20241229090314 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/ice — Glace | https://static.wikia.nocookie.net/rell-seasw/images/6/61/IceGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/sand — Sable | https://static.wikia.nocookie.net/rell-seasw/images/c/c4/SandGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/smoke — Fumée | https://static.wikia.nocookie.net/rell-seasw/images/3/36/SmokeGodFruit.png/revision/latest?cb=20241229092740 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/dark — Ténèbres | https://static.wikia.nocookie.net/rell-seasw/images/a/a4/DarkGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/rumble — Foudre | https://static.wikia.nocookie.net/rell-seasw/images/2/28/RumbleGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/magma — Magma | https://static.wikia.nocookie.net/rell-seasw/images/9/9e/MagmaGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/dragon — Dragon | https://static.wikia.nocookie.net/rell-seasw/images/6/69/DragonGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/phoenix — Phénix | https://static.wikia.nocookie.net/rell-seasw/images/0/09/PhoenixGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/buddha — Bouddha | https://static.wikia.nocookie.net/rell-seasw/images/4/4d/BuddhaGodFruit.png/revision/latest?cb=20241229092843 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/mythical_wolf — Loup mythique | https://static.wikia.nocookie.net/rell-seasw/images/4/48/MythicalWolfGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/allosaurus — Allosaure | https://static.wikia.nocookie.net/rell-seasw/images/c/c8/AllosaurusGodFruit.png/revision/latest?cb=20241229092737 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/leopard — Léopard | https://static.wikia.nocookie.net/rell-seasw/images/7/76/LeopardGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/wolf — Loup | https://static.wikia.nocookie.net/rell-seasw/images/1/12/WolfGodFruit.png/revision/latest?cb=20241229092844 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/falcon — Faucon | https://static.wikia.nocookie.net/rell-seasw/images/4/48/FalconGodFruit.png/revision/latest?cb=20241229092739 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| fruit/bison — Bison | https://static.wikia.nocookie.net/rell-seasw/images/0/04/BisonGodFruit.png/revision/latest?cb=20241229092738 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| haki/armament — Armement | https://static.wikia.nocookie.net/rell-seasw/images/0/07/ArmamentHakiImage.png/revision/latest?cb=20241231151444 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| haki/observation — Observation | https://static.wikia.nocookie.net/rell-seasw/images/5/51/ObservationHakiImage.png/revision/latest?cb=20241231153834 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| haki/conqueror — Conquérant | https://static.wikia.nocookie.net/rell-seasw/images/d/d1/ConquerorsHakiImage.png/revision/latest?cb=20241231153256 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/bri_o_tarth — Bri O. Tarth | https://static.wikia.nocookie.net/rell-seasw/images/5/51/HCA_Bri.png/revision/latest?cb=20241228075430 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sir_galahad — Sir Galahad | https://static.wikia.nocookie.net/rell-seasw/images/7/71/HCA_Galahad.png/revision/latest?cb=20241228075432 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sir_gawain — Sir Gawain | https://static.wikia.nocookie.net/rell-seasw/images/1/19/HCA_Gawain.png/revision/latest?cb=20241228075432 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sir_lancelot — Sir Lancelot | https://static.wikia.nocookie.net/rell-seasw/images/1/14/HCA_Lancelot.png/revision/latest?cb=20241228075432 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sie_g_fried — Sie G. Fried | https://static.wikia.nocookie.net/rell-seasw/images/4/4e/HCA_Sie.png/revision/latest?cb=20241228075432 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sir_lannister — Sir Lannister | https://static.wikia.nocookie.net/rell-seasw/images/c/cd/Sir_Lannister.png/revision/latest?cb=20250824232403 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/opp_e_heimer — Opp E. Heimer | https://static.wikia.nocookie.net/rell-seasw/images/a/a7/OHC_Opp.png/revision/latest?cb=20241228073051 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/new_d_ton — New D. Ton | https://static.wikia.nocookie.net/rell-seasw/images/b/b7/HCO_New.png/revision/latest?cb=20241228075435 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/ein_s_tein — Ein S. Tein | https://static.wikia.nocookie.net/rell-seasw/images/1/1b/HCO_Ein.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/dar_d_win — Dar D. Win | https://static.wikia.nocookie.net/rell-seasw/images/0/05/HCO_Dar.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/sigma_freud — Sigma Freud | https://static.wikia.nocookie.net/rell-seasw/images/d/da/HCO_Sigma.png/revision/latest?cb=20241228075435 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/tom_e_dison — Tom E. Dison | https://static.wikia.nocookie.net/rell-seasw/images/3/3c/HCO_Tom.png/revision/latest?cb=20241228075435 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/xanda_d_goat — Xanda D. Goat | https://static.wikia.nocookie.net/rell-seasw/images/8/8c/HCC_Xanda.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/julius_c_zar — Julius C. Zar | https://static.wikia.nocookie.net/rell-seasw/images/7/71/HCC_Julius.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/geng_d_khan — Geng D. Khan | https://static.wikia.nocookie.net/rell-seasw/images/3/3b/HCC_Geng.png/revision/latest?cb=20241228075432 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/nap_o_leon — Nap O. Leon | https://static.wikia.nocookie.net/rell-seasw/images/e/ea/HCC_Nap.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| carte_haki/go_d_zilla — Go D. Zilla | https://static.wikia.nocookie.net/rell-seasw/images/a/a7/HCC_Go.png/revision/latest?cb=20241228075434 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/alpha_clasher — Alpha Clasher | https://static.wikia.nocookie.net/rell-seasw/images/9/9c/AlphaClasherMASK.png/revision/latest?cb=20250722100507 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/m1_god — M1 God | https://static.wikia.nocookie.net/rell-seasw/images/d/df/M1GodMASK.png/revision/latest?cb=20250722100508 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/full_stack — Full Stack | https://static.wikia.nocookie.net/rell-seasw/images/1/1a/FullStackMASK.png/revision/latest?cb=20250722100508 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/faster_punch — Faster Punch | https://static.wikia.nocookie.net/rell-seasw/images/8/86/FasterPunchMASK.png/revision/latest?cb=20250722100508 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/strong_puncher — Strong Puncher | https://static.wikia.nocookie.net/rell-seasw/images/b/bf/StrongPunchMASK.png/revision/latest?cb=20250722100508 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/down_god — Down God | https://static.wikia.nocookie.net/rell-seasw/images/7/79/DownGodMASK.png/revision/latest?cb=20250811060232 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/flash_dash — Flash Dash | https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Poster_FlashDash.png/revision/latest?cb=20250607061101 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/geppo_master — Geppo Master | https://static.wikia.nocookie.net/rell-seasw/images/b/ba/GeppoMasterMASK.png/revision/latest?cb=20250722095707 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/wall_bouncer — Wall Bouncer | https://static.wikia.nocookie.net/rell-seasw/images/a/af/WallBouncerMASK.png/revision/latest?cb=20260115043428 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/ronaldo_trip — Ronaldo Trip | https://static.wikia.nocookie.net/rell-seasw/images/2/2f/RonaldoTripMASK.png/revision/latest?cb=20250722100508 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/jumper — Jumper | https://static.wikia.nocookie.net/rell-seasw/images/4/45/JumperMASK.png/revision/latest?cb=20250722101459 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/mr_widestep — Mr Widestep | https://static.wikia.nocookie.net/rell-seasw/images/2/29/MrWidestepMASK.png/revision/latest?cb=20250722095707 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/sir_pitcher — Sir Pitcher | https://static.wikia.nocookie.net/rell-seasw/images/6/6d/SirPtcherMASK.png/revision/latest?cb=20250722095708 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/strong_tilt — Strong Tilt | https://static.wikia.nocookie.net/rell-seasw/images/a/a9/StrongTiltMASK.png/revision/latest?cb=20250722095708 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/auto_parry — Auto Parry | https://static.wikia.nocookie.net/rell-seasw/images/6/67/AutoParryMASK.png/revision/latest?cb=20250722101101 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/parry_god — Parry God | https://static.wikia.nocookie.net/rell-seasw/images/2/2f/ParryGodMASK.png/revision/latest?cb=20250722101103 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/quick_parry — Quick Parry | https://static.wikia.nocookie.net/rell-seasw/images/c/cf/QuickParryMASK.png/revision/latest?cb=20250722101103 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/evade_god — Evade God | https://static.wikia.nocookie.net/rell-seasw/images/c/c1/EvadeGodMASK.png/revision/latest?cb=20250722101103 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| poster/parryingan — Parryingan | https://static.wikia.nocookie.net/rell-seasw/images/8/82/ParryinganMASK.png/revision/latest?cb=20250722101103 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| arme/light — Armes légères | https://static.wikia.nocookie.net/rell-seasw/images/b/bc/LightWeaponsIcon.png/revision/latest?cb=20250709043922 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| arme/medium — Armes moyennes | https://static.wikia.nocookie.net/rell-seasw/images/b/bb/MediumWeaponsIcon.png/revision/latest?cb=20250709043852 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| arme/heavy — Armes lourdes | https://static.wikia.nocookie.net/rell-seasw/images/a/a1/HeavyWeaponsIcon.png/revision/latest?cb=20250709043351 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| arme/ranged — Armes à distance | https://static.wikia.nocookie.net/rell-seasw/images/9/92/RangedWeaponsIcon.png/revision/latest?cb=20250709043906 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/spyglass — Longue-vue | https://static.wikia.nocookie.net/rell-seasw/images/6/6c/Telescope.png/revision/latest?cb=20250621131530 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/snail_phone — Escargot-téléphone | https://static.wikia.nocookie.net/rell-seasw/images/9/95/DenDenMushi.png/revision/latest?cb=20250621131113 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/ship_in_a_bottle — Navire en bouteille | https://static.wikia.nocookie.net/rell-seasw/images/a/a6/ShipInABottle1%28AI_upcalled%29.png/revision/latest?cb=20250708142838 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/lock_pick — Crochet de serrure | https://static.wikia.nocookie.net/rell-seasw/images/e/ea/PickLock.png/revision/latest?cb=20250621130856 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/shovel — Pelle | https://static.wikia.nocookie.net/rell-seasw/images/e/ee/Shovel1.png/revision/latest?cb=20250719030541 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/paraglider — Parapente | https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Paraglider.png/revision/latest?cb=20250621131234 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/compass — Boussole | https://static.wikia.nocookie.net/rell-seasw/images/9/92/Compass.png/revision/latest?cb=20250708182551 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| equipement/traders_bag — Sac de marchand | https://static.wikia.nocookie.net/rell-seasw/images/1/1a/TradersBag.png/revision/latest?cb=20250808081915 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/sails — Voiles | https://static.wikia.nocookie.net/rell-seasw/images/7/79/Sailsicon.png/revision/latest?cb=20260624153312 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/cannons — Canons | https://static.wikia.nocookie.net/rell-seasw/images/b/bf/Canonicon.png/revision/latest?cb=20260624152721 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/steering_wheel — Roue de gouvernail | https://static.wikia.nocookie.net/rell-seasw/images/a/a4/SteeringWheelicon.png/revision/latest?cb=20260624153832 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/material — Matériau | https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Materialshipicon.png/revision/latest?cb=20260624154055 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/bow — Proue | https://static.wikia.nocookie.net/rell-seasw/images/1/18/Bowfrontshipicon.png/revision/latest?cb=20260624154410 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/midship — Milieu | https://static.wikia.nocookie.net/rell-seasw/images/b/bf/Middleshipicon.png/revision/latest?cb=20260624154803 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/stern — Poupe | https://static.wikia.nocookie.net/rell-seasw/images/c/c2/Sternbackicon.png/revision/latest?cb=20260624155108 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/basic_cannon — Canon de base | https://static.wikia.nocookie.net/rell-seasw/images/1/10/ShipCanonIcon1.png/revision/latest?cb=20260625152648 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| piece_navire/heavy_cannon — Canon lourd | https://static.wikia.nocookie.net/rell-seasw/images/3/30/ShipHeavyCanonIcon2.png/revision/latest?cb=20260625153151 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/terrestrial — Terrestre | https://static.wikia.nocookie.net/rell-seasw/images/c/c7/TerrestrialMountIcon.png/revision/latest?cb=20250718134100 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/aquatic — Aquatique | https://static.wikia.nocookie.net/rell-seasw/images/4/48/AquaticMountIcon.png/revision/latest?cb=20250718134100 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/aerial — Aérienne | https://static.wikia.nocookie.net/rell-seasw/images/6/6f/AerialMountIcon.png/revision/latest?cb=20250718134059 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/blu — Blu | https://static.wikia.nocookie.net/rell-seasw/images/5/5f/BluMountDisplay.png/revision/latest?cb=20250718131752 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/cat — Chat | https://static.wikia.nocookie.net/rell-seasw/images/7/7a/CatMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/crab — Crabe | https://static.wikia.nocookie.net/rell-seasw/images/f/f4/CrabMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/deer — Cerf | https://static.wikia.nocookie.net/rell-seasw/images/d/df/DeerMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/dragon — Dragon | https://static.wikia.nocookie.net/rell-seasw/images/c/cc/DragonMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/flying_fish — Poisson volant | https://static.wikia.nocookie.net/rell-seasw/images/c/c1/FlyingFishMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/fox — Renard | https://static.wikia.nocookie.net/rell-seasw/images/4/46/FoxMountDisplay.png/revision/latest?cb=20250718131754 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/frog — Grenouille | https://static.wikia.nocookie.net/rell-seasw/images/5/54/FrogMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/mammoth — Mammouth | https://static.wikia.nocookie.net/rell-seasw/images/3/38/MammothMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/octopus — Pieuvre | https://static.wikia.nocookie.net/rell-seasw/images/b/b2/OctopusMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/owl — Hibou | https://static.wikia.nocookie.net/rell-seasw/images/e/e4/OwlMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/rooster — Coq | https://static.wikia.nocookie.net/rell-seasw/images/a/a7/RoosterMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/shark — Requin | https://static.wikia.nocookie.net/rell-seasw/images/8/8c/SharkMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/spider — Araignée | https://static.wikia.nocookie.net/rell-seasw/images/e/eb/SpiderMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/thragg — Thragg | https://static.wikia.nocookie.net/rell-seasw/images/b/b7/ThraggMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monture/whale — Baleine | https://static.wikia.nocookie.net/rell-seasw/images/7/7c/WhaleMountDisplay.png/revision/latest?cb=20250718131755 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |
| monnaie/relli — Relli | https://static.wikia.nocookie.net/rell-seasw/images/0/03/RELLCoin.png/revision/latest?cb=20241229144543 | défi anti-robot du CDN du wiki (Cloudflare) : non contourné |

## Sans icône (29)

Le dossier de recherche ne donne aucune icône officielle pour ces éléments : le site affiche
le nom seul. (La page Enchants du wiki montre des images d'enchantements, non retenues par le
dossier : elles n'ont pas été téléchargées.)

- metier/doctor — Médecin (Doctor)
- mer/desolate — Desolate (Desolate)
- mer/sunken — Sunken (Sunken)
- mer/molten — Molten (Molten)
- mer/uncharted — Uncharted (Uncharted)
- style/black_leg — Black Leg (Black Leg)
- style/electro — Electro (Electro)
- style/rokushiki — Rokushiki (Rokushiki)
- style/dragon_claw — Dragon Claw (Dragon Claw)
- arme/katana — Katana (Katana)
- arme/dagger — Dague (Dagger)
- arme/yahu_great_sword — Yahu Great Sword (Yahu Great Sword)
- equipement/fishing_rod — Canne à pêche (Fishing rod)
- equipement/grappling_hook — Grappin (Grappling hook)
- enchantement/fire — Feu (Fire)
- enchantement/ice — Glace (Ice)
- enchantement/poison — Poison (Poison)
- enchantement/lightning — Foudre (Lightning)
- enchantement/sea_prism — Sea Prism (Sea Prism)
- navire/sloop — Sloop (Sloop)
- navire/caravel — Caravelle (Caravel)
- navire/galleon — Galion (Galleon)
- navire/sovereign — Sovereign (Sovereign)
- navire/submarine — Sous-marin (Submarine)
- piece_navire/burst_cannon — Canon à rafale (Burst Cannon)
- piece_navire/mortar_cannon — Mortier (Mortar Cannon)
- monture/bee — Abeille (Bee)
- monnaie/tickets — Tickets (Tickets)
- monnaie/randomize — Randomize (Randomize)

<!-- provenance-json
{
 "fruit/giraffe": {
  "date": "2026-10-25T20:39:45Z",
  "fichier_wiki": "GiraffeGodFruit.png",
  "format": "PNG",
  "hauteur": 120,
  "largeur": 120,
  "octets": 15077,
  "page_fichier": "https://rellseas.fandom.com/wiki/File:GiraffeGodFruit.png",
  "sha256": "4ca6ac1cd273ec623462409f143efec956d2a7a137e8de6c402c27748ee490b4",
  "url_finale": "https://static.wikia.nocookie.net/rell-seasw/images/7/77/GiraffeGodFruit.png/revision/latest?cb=20241229092739&format=original",
  "url_source": "https://static.wikia.nocookie.net/rell-seasw/images/7/77/GiraffeGodFruit.png/revision/latest?cb=20241229092739",
  "url_telechargee": "https://static.wikia.nocookie.net/rell-seasw/images/7/77/GiraffeGodFruit.png/revision/latest?cb=20241229092739&format=original"
 },
 "fruit/light": {
  "date": "2026-10-25T20:39:32Z",
  "fichier_wiki": "LightGodFruit.png",
  "format": "PNG",
  "hauteur": 120,
  "largeur": 120,
  "octets": 16760,
  "page_fichier": "https://rellseas.fandom.com/wiki/File:LightGodFruit.png",
  "sha256": "8c45a61724bdd5913be8060bed012088b2027a62620f6b13d93008ceb4df1d5e",
  "url_finale": "https://static.wikia.nocookie.net/rell-seasw/images/f/f2/LightGodFruit.png/revision/latest?cb=20241229092739&format=original",
  "url_source": "https://static.wikia.nocookie.net/rell-seasw/images/f/f2/LightGodFruit.png/revision/latest?cb=20241229092739",
  "url_telechargee": "https://static.wikia.nocookie.net/rell-seasw/images/f/f2/LightGodFruit.png/revision/latest?cb=20241229092739&format=original"
 },
 "fruit/love": {
  "date": "2026-10-25T20:39:22Z",
  "fichier_wiki": "LoveGodFruit.png",
  "format": "PNG",
  "hauteur": 120,
  "largeur": 120,
  "octets": 21074,
  "page_fichier": "https://rellseas.fandom.com/wiki/File:LoveGodFruit.png",
  "sha256": "a02df04e6bf8e2ce4fa96f06894b28973ec8be1f761cefc90e9850ff0b427ef7",
  "url_finale": "https://static.wikia.nocookie.net/rell-seasw/images/2/24/LoveGodFruit.png/revision/latest?cb=20241229092739&format=original",
  "url_source": "https://static.wikia.nocookie.net/rell-seasw/images/2/24/LoveGodFruit.png/revision/latest?cb=20241229092739",
  "url_telechargee": "https://static.wikia.nocookie.net/rell-seasw/images/2/24/LoveGodFruit.png/revision/latest?cb=20241229092739&format=original"
 },
 "logo/rellgames_groupe": {
  "date": "2026-10-25T20:41:30Z",
  "format": "PNG",
  "hauteur": 420,
  "largeur": 420,
  "octets": 105747,
  "page": "https://www.roblox.com/communities/4939446",
  "sha256": "ec2a27cd595ad51f6a6ce562a69e0feeca6aee8bdcf02cd16c664472800c7bca",
  "titre": "Groupe studio « RELL GAMES » (4939446)",
  "url_finale": "https://tr.rbxcdn.com/180DAY-2feb811d77e9fb6ca1cd1d20e680f49f/420/420/Image/Png/noFilter",
  "url_source": "https://thumbnails.roblox.com/v1/groups/icons?groupIds=4939446&size=420x420&format=Png&isCircular=false",
  "url_telechargee": "https://tr.rbxcdn.com/180DAY-2feb811d77e9fb6ca1cd1d20e680f49f/420/420/Image/Png/noFilter"
 },
 "logo/rellseas_discord": {
  "date": "2026-10-25T20:41:32Z",
  "format": "PNG",
  "hauteur": 512,
  "largeur": 512,
  "octets": 313506,
  "page": "https://discord.gg/RELLSEAS",
  "sha256": "4a819c1820619d597473202c9790b4a0db11f372184f6c084993f5135f5d0945",
  "titre": "Icône du serveur Discord RELL Seas",
  "url_finale": "https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512",
  "url_source": "https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512",
  "url_telechargee": "https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512"
 },
 "logo/rellseas_groupe": {
  "date": "2026-10-25T20:41:28Z",
  "format": "PNG",
  "hauteur": 420,
  "largeur": 420,
  "octets": 213046,
  "page": "https://www.roblox.com/communities/11020595/RELL-Seas",
  "sha256": "845abf7b99ba6ebc0961f5bfd77a7505d8d4d5ffe3cb8cda964f1b09582125d4",
  "titre": "Groupe Roblox « RELL Seas » (11020595)",
  "url_finale": "https://tr.rbxcdn.com/180DAY-1860e88e743735228930c9bb6ff05fe5/420/420/Image/Png/noFilter",
  "url_source": "https://thumbnails.roblox.com/v1/groups/icons?groupIds=11020595&size=420x420&format=Png&isCircular=false",
  "url_telechargee": "https://tr.rbxcdn.com/180DAY-1860e88e743735228930c9bb6ff05fe5/420/420/Image/Png/noFilter"
 },
 "logo/rellseas_jeu": {
  "date": "2026-10-25T20:41:26Z",
  "format": "PNG",
  "hauteur": 512,
  "largeur": 512,
  "octets": 276703,
  "page": "https://www.roblox.com/communities/11020595/RELL-Seas",
  "sha256": "55288ecefc1181632609cd2b17220178f0ac1d9e9de6986966570099fba0618b",
  "titre": "Icône du jeu RELL Seas (Roblox)",
  "url_finale": "https://tr.rbxcdn.com/180DAY-5c06d38c14c44bb9d04a410068fe0e96/512/512/Image/Png/noFilter",
  "url_source": "https://thumbnails.roblox.com/v1/games/icons?universeIds=2738929784&size=512x512&format=Png&isCircular=false",
  "url_telechargee": "https://tr.rbxcdn.com/180DAY-5c06d38c14c44bb9d04a410068fe0e96/512/512/Image/Png/noFilter"
 }
}
-->
