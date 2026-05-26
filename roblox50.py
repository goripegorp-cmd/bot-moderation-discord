"""
Phase 50 — ROBLOX SPÉCIALISÉ
─────────────────────────────────────────────────────────
Le serveur étant Roblox-centric, on lui donne des features qui parlent à
sa niche :

• STUDIO_TIPS : 60+ conseils pour devs Roblox, posté 1x/jour à 9h FR.
• SPEEDRUN_CATEGORIES : défis chronométrés, submission par vidéo, review
  staff, leaderboard hebdo + mensuel + all-time.
• MATCHMAKING_GAMES : tes jeux Roblox que les membres peuvent annoncer
  qu'ils jouent, créant une "party" que d'autres rejoignent.

Toutes les listes sont des données pures, sans side-effect.
"""
from __future__ import annotations

from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  STUDIO TIPS — Conseils dev Roblox (curated, sources fiables 2025-2026)
# ═══════════════════════════════════════════════════════════════════════════════

STUDIO_TIPS = [
    {
        "id": 1,
        "title": "Préfère `task.wait()` à `wait()`",
        "content": (
            "`wait()` est deprecated et a un overhead. Utilise `task.wait(time)` "
            "qui est plus rapide et plus précis. Pour 0 sec, `task.defer()` qui "
            "s'exécute après le current frame."
        ),
        "category": "performance",
    },
    {
        "id": 2,
        "title": "Évite `:WaitForChild()` en boucle",
        "content": (
            "Si tu utilises `:WaitForChild()` 100 fois dans un Loop, ça yield 100x. "
            "Cache la référence une seule fois : `local part = workspace:WaitForChild('Part')` "
            "PUIS utilise `part` dans la boucle."
        ),
        "category": "performance",
    },
    {
        "id": 3,
        "title": "RemoteEvents > RemoteFunctions pour fire-and-forget",
        "content": (
            "RemoteFunction yield le client en attendant la réponse serveur. "
            "Pour envoyer une donnée du client au serveur SANS attendre, "
            "utilise RemoteEvent + `:FireServer()` — pas de yield."
        ),
        "category": "network",
    },
    {
        "id": 4,
        "title": "Ne JAMAIS faire confiance au client",
        "content": (
            "Le client peut envoyer N'IMPORTE QUEL paramètre dans un RemoteEvent. "
            "Toujours valider côté serveur : type, range, ownership. "
            "Exemple : si tu fais `PurchaseItem:FireServer(itemId, price)`, "
            "**ne lis pas le price** envoyé par le client — cherche-le côté serveur."
        ),
        "category": "security",
    },
    {
        "id": 5,
        "title": "DataStore : Save toujours sur PlayerRemoving",
        "content": (
            "Connecte `Players.PlayerRemoving:Connect(savePlayerData)`. Ne save "
            "pas seulement au quit — sauvegarde aussi périodiquement (toutes 5 min) "
            "via `task.delay()` pour limiter la perte si crash."
        ),
        "category": "data",
    },
    {
        "id": 6,
        "title": "BindToClose pour sauvegarder en cas de shutdown",
        "content": (
            "`game:BindToClose(function() ... end)` te donne ~30s pour finir tes "
            "saves. CRITIQUE pour les serveurs avec 1-2 joueurs où PlayerRemoving "
            "ne firerait pas avant le shutdown."
        ),
        "category": "data",
    },
    {
        "id": 7,
        "title": "Utilise des Object Pools pour les projectiles",
        "content": (
            "Créer/Destroy des Parts en boucle est CHER. Crée un pool de 50 parts "
            "réutilisables au start, mets-les en `CollectionService`, recycle-les "
            "quand inactives."
        ),
        "category": "performance",
    },
    {
        "id": 8,
        "title": "PreloadAsync pour charger les assets au start",
        "content": (
            "`ContentProvider:PreloadAsync({asset1, asset2})` force le chargement "
            "des assets AVANT que le joueur les voit. Évite les flashes de "
            "textures grises au mid-game."
        ),
        "category": "ux",
    },
    {
        "id": 9,
        "title": "TweenService > lerp manuel",
        "content": (
            "Pour animer une UI ou une part, utilise `TweenService` avec un "
            "TweenInfo. C'est plus performant que tweener à la main dans un "
            "`RunService.Heartbeat`."
        ),
        "category": "ux",
    },
    {
        "id": 10,
        "title": "Anchored = true pour les Parts décoratives",
        "content": (
            "Une Part non-anchored est calculée par la physics chaque frame, "
            "même si elle ne bouge pas. Si elle est décorative, **Anchored = true** "
            "pour économiser de la perf."
        ),
        "category": "performance",
    },
    {
        "id": 11,
        "title": "CollectionService pour tagger des objets",
        "content": (
            "Au lieu de mettre tes ennemis dans un Folder et itérer, "
            "tag-les avec `CollectionService:AddTag(npc, 'Enemy')`. "
            "Tu retrouves tous les enemies avec `GetTagged('Enemy')`."
        ),
        "category": "architecture",
    },
    {
        "id": 12,
        "title": "Server Authority pour le mouvement",
        "content": (
            "Si ton jeu est compétitif, NE FAIS PAS confiance au CFrame envoyé "
            "par le client. Soit replique le mouvement côté serveur, soit "
            "valide la vitesse max + téléport check. Sinon : speed-hack instant."
        ),
        "category": "security",
    },
    {
        "id": 13,
        "title": "Profile ton jeu avec MicroProfiler",
        "content": (
            "Ouvre Studio → View → MicroProfiler (Ctrl+Alt+F6). Tu vois où le "
            "framerate part. Cherche les pics rouges. Sur mobile, surveille "
            "le Heartbeat — il doit rester sous 4ms."
        ),
        "category": "performance",
    },
    {
        "id": 14,
        "title": "ModuleScript > require global",
        "content": (
            "Toujours `require(workspace.Modules.MyModule)` pour partager du code. "
            "PAS de `_G.MyFunction` — c'est un anti-pattern qui rend ton code "
            "intestable et fragile aux race conditions."
        ),
        "category": "architecture",
    },
    {
        "id": 15,
        "title": "Pcall sur TOUS les appels DataStore",
        "content": (
            "DataStore peut throw en cas de network. **Toujours** `local ok, err "
            "= pcall(function() return ds:GetAsync(key) end)`. Sinon ton jeu "
            "crash silencieusement à l'API down."
        ),
        "category": "data",
    },
    {
        "id": 16,
        "title": "Utilise `task.spawn` pour le code parallèle",
        "content": (
            "`coroutine.wrap()` masque les erreurs (le stack trace est perdu). "
            "Préfère `task.spawn(function() ... end)` qui propage les erreurs "
            "dans l'output. Plus simple à débugger."
        ),
        "category": "performance",
    },
    {
        "id": 17,
        "title": "Streaming Enabled = true pour les grosses maps",
        "content": (
            "Active StreamingEnabled sur Workspace si ta map fait >5000 parts. "
            "Le client n'en charge que ce qui est proche du joueur. Performance "
            "x2-x4 sur mobile."
        ),
        "category": "performance",
    },
    {
        "id": 18,
        "title": "Sound:Play() avec `IsLoaded` check",
        "content": (
            "Si tu fais `sound:Play()` avant que le sound asset soit chargé, "
            "il joue avec un délai. Check `sound.IsLoaded` ou utilise "
            "`ContentProvider:PreloadAsync({sound})` au start."
        ),
        "category": "ux",
    },
    {
        "id": 19,
        "title": "GuiObject.AnchorPoint pour centrer",
        "content": (
            "Pour centrer une frame, mets `AnchorPoint = Vector2.new(0.5, 0.5)` "
            "+ `Position = UDim2.new(0.5, 0, 0.5, 0)`. Pas besoin de calculer "
            "AbsoluteSize ni de Frame parent."
        ),
        "category": "ui",
    },
    {
        "id": 20,
        "title": "UIListLayout > positions manuelles",
        "content": (
            "Pour aligner 10 boutons dans une frame, mets un `UIListLayout` "
            "dedans avec `FillDirection.Vertical`. Plus besoin de calculer "
            "des UDim2 — ça s'auto-adapte."
        ),
        "category": "ui",
    },
    {
        "id": 21,
        "title": "Use Camera:WorldToScreenPoint pour overlay UI sur monde",
        "content": (
            "Pour afficher un nom au-dessus d'un NPC : "
            "`Camera:WorldToScreenPoint(npc.Position)` retourne la position "
            "écran. Utilise-la pour positionner ta GuiObject. Si Z<0 → derrière "
            "la caméra, ne dessine pas."
        ),
        "category": "ui",
    },
    {
        "id": 22,
        "title": "ProximityPrompt > détecter Touch + KeyEvent",
        "content": (
            "Pour interagir avec un objet (porte, NPC), utilise `ProximityPrompt`. "
            "Gère seul l'UI, la distance, et fonctionne nativement sur mobile. "
            "Plus besoin de coder un input handler."
        ),
        "category": "ux",
    },
    {
        "id": 23,
        "title": "Humanoid:MoveTo() au lieu de CFrame teleport",
        "content": (
            "Pour faire bouger un NPC, `Humanoid:MoveTo(targetPosition)` "
            "respecte la physics et les obstacles. CFrame teleport bypass la "
            "physics — le NPC peut traverser les murs."
        ),
        "category": "ai",
    },
    {
        "id": 24,
        "title": "PathfindingService pour NPCs intelligents",
        "content": (
            "Pour qu'un NPC contourne un obstacle, utilise `PathfindingService:"
            "CreatePath()`. Précompute le path une fois, suis les waypoints "
            "avec MoveTo. Le NPC évite les murs automatiquement."
        ),
        "category": "ai",
    },
    {
        "id": 25,
        "title": "RemoteEvents : rate-limiter côté serveur",
        "content": (
            "Un client peut spammer un RemoteEvent 1000x/sec. Ajoute un cooldown "
            "par player : `local lastFire = {}` + check `tick() - (lastFire[plr] "
            "or 0) > 0.1`. Sinon : flood = lag serveur."
        ),
        "category": "security",
    },
    {
        "id": 26,
        "title": "Use `assert()` pour valider tes inputs",
        "content": (
            "`assert(type(itemId) == 'string', 'itemId must be string')` au début "
            "d'une fonction. Crashe vite avec un message clair plutôt que d'aller "
            "loin avec des données pourries."
        ),
        "category": "code-quality",
    },
    {
        "id": 27,
        "title": "Évite `wait(0.03)` — utilise RunService",
        "content": (
            "Pour exécuter du code chaque frame, connecte `RunService.Heartbeat:Connect()`. "
            "C'est synchronisé avec le rendu. `wait(0.03)` drift et est imprécis."
        ),
        "category": "performance",
    },
    {
        "id": 28,
        "title": "Debounce les click events",
        "content": (
            "Si ton joueur clique 5x rapidement sur un bouton 'Buy', tu vas "
            "vendre 5x. Ajoute un debounce : `if debounce then return end; "
            "debounce = true; ...; debounce = false`."
        ),
        "category": "ux",
    },
    {
        "id": 29,
        "title": "LocalScript dans StarterPlayerScripts > StarterGui",
        "content": (
            "Les LocalScripts dans StarterGui ne tournent qu'une fois (au load "
            "du GUI). Pour du code qui doit tourner dès le respawn, mets-le "
            "dans `StarterPlayer.StarterPlayerScripts`."
        ),
        "category": "architecture",
    },
    {
        "id": 30,
        "title": "Roblox Marketplace : utilise ProductId pas AssetId",
        "content": (
            "Pour les gamepasses et developer products, utilise leur ID Produit, "
            "PAS l'AssetId du Marketplace. C'est 2 IDs différents — confusion "
            "fréquente qui casse les achats."
        ),
        "category": "monetization",
    },
    {
        "id": 31,
        "title": "MemoryStoreService pour leaderboards real-time",
        "content": (
            "DataStore est trop lent pour un leaderboard live. Utilise "
            "`MemoryStoreSortedMap` — récupération instantanée des top scores. "
            "Limite TTL : 45 jours max."
        ),
        "category": "data",
    },
    {
        "id": 32,
        "title": "Variables locales > .Value globales",
        "content": (
            "Accéder à un IntValue.Value 100x est plus lent que de copier "
            "`local hp = humanoid.Health` une fois et utiliser `hp`. Cache "
            "les valeurs hot dans des locals."
        ),
        "category": "performance",
    },
    {
        "id": 33,
        "title": "Tween:Play() — pas Tween:Run()",
        "content": (
            "TweenService crée un objet Tween que tu dois `:Play()`. "
            "Erreur fréquente : oublier le `:Play()` et croire que le tween "
            "ne marche pas."
        ),
        "category": "ux",
    },
    {
        "id": 34,
        "title": "UserInputService > KeyDown deprecated",
        "content": (
            "`Mouse.KeyDown` et `Mouse.Button1Down` sont deprecated. Utilise "
            "`UserInputService.InputBegan:Connect()` qui gère clavier + souris "
            "+ touch + gamepad uniformément."
        ),
        "category": "input",
    },
    {
        "id": 35,
        "title": "Workspace:Raycast() params object",
        "content": (
            "Ancien `FindPartOnRay` est deprecated. Use `Workspace:Raycast(origin, "
            "direction, raycastParams)` avec un RaycastParams pour filtrer les "
            "parts à ignorer (caméra, joueur lui-même, etc.)."
        ),
        "category": "code-quality",
    },
    {
        "id": 36,
        "title": "Don't yield in events",
        "content": (
            "Si tu fais `task.wait(1)` dans un event handler "
            "(`Touched:Connect()`), tu bloques les autres signals du même event. "
            "Préfère `task.spawn(function() task.wait(1); ... end)`."
        ),
        "category": "performance",
    },
    {
        "id": 37,
        "title": "ContextActionService pour rebind input",
        "content": (
            "Au lieu de hardcode `if input.KeyCode == E then attack()`, utilise "
            "`ContextActionService:BindAction('Attack', attack, false, Enum.KeyCode.E)`. "
            "Le joueur peut rebind. Gère touch/gamepad auto."
        ),
        "category": "input",
    },
    {
        "id": 38,
        "title": "Don't store everything in attributes",
        "content": (
            "Les attributes sont synchronisés au client. Si tu mets des données "
            "sensibles (gold, premium status) dedans, le client les voit. "
            "Garde-les serveur-only dans des tables Lua."
        ),
        "category": "security",
    },
    {
        "id": 39,
        "title": "Use `wait()` only as last resort dans coroutines",
        "content": (
            "Quand tu peux event-driven (signal:Wait()), évite le polling avec "
            "wait(). Utilise `RunService.Heartbeat:Wait()` ou les events de "
            "Roblox plutôt que des boucles fixes."
        ),
        "category": "performance",
    },
    {
        "id": 40,
        "title": "PolicyService pour les régions",
        "content": (
            "Avant d'afficher du contenu mature/competitif/social, check "
            "`PolicyService:GetPolicyInfoForPlayerAsync(player)`. Certaines "
            "regions limitent l'affichage de prix, chat, etc."
        ),
        "category": "compliance",
    },
    {
        "id": 41,
        "title": "Décompose tes scripts en modules",
        "content": (
            "Un script de 2000 lignes est ingérable. Sépare en modules : "
            "`CombatModule.lua` / `EconomyModule.lua` / `UIModule.lua`. "
            "Chaque module fait UNE chose, exporte ses fonctions publiques."
        ),
        "category": "architecture",
    },
    {
        "id": 42,
        "title": "Roblox Open Cloud : DataStore via HTTP API",
        "content": (
            "Tu peux maintenant lire/écrire DataStore depuis EXTERNE via "
            "Open Cloud API. Utile pour un dashboard web qui montre les "
            "stats du jeu. Auth via API Key dans le studio settings."
        ),
        "category": "data",
    },
    {
        "id": 43,
        "title": "ZIndex et ZIndexBehavior pour les GUIs en couches",
        "content": (
            "Si tu as 5 frames qui se chevauchent et que l'ordre est faux, "
            "utilise `ZIndex` (plus haut = devant) + `ZIndexBehavior = Global` "
            "sur le ScreenGui parent."
        ),
        "category": "ui",
    },
    {
        "id": 44,
        "title": "EmojiText > Emoji image",
        "content": (
            "Roblox supporte les emojis natifs dans TextLabel : `'❤️"
            "Super Coeur'`. Plus besoin d'importer une image et la gérer "
            "comme asset."
        ),
        "category": "ui",
    },
    {
        "id": 45,
        "title": "Don't loop createPart in render frames",
        "content": (
            "Créer 100 parts dans une boucle bloque le serveur jusqu'à "
            "complétion. Use `task.wait()` entre chaque batch de 10 pour "
            "céder le tick et éviter le lag spike."
        ),
        "category": "performance",
    },
    {
        "id": 46,
        "title": "PlayerService:CreateHumanoidModelFromUserId pour avatar",
        "content": (
            "Pour mettre l'avatar d'un autre joueur dans un menu (leaderboard "
            "etc.), utilise `Players:CreateHumanoidModelFromUserId(userId)`. "
            "Plus simple que de fetch l'avatar via HTTP."
        ),
        "category": "ui",
    },
    {
        "id": 47,
        "title": "Verbose logs : utilise warn() pas print()",
        "content": (
            "`print()` est noyé dans les logs. `warn()` apparaît en jaune et "
            "est facile à filtrer. `error()` en rouge et stop l'exécution. "
            "Choisis selon la gravité."
        ),
        "category": "code-quality",
    },
    {
        "id": 48,
        "title": "Avoid frequent `Instance.new()` in loops",
        "content": (
            "`Instance.new('Part')` est lent (alloc Roblox engine). Si tu crées "
            "1000 parts, utilise `Instance.new()` une fois + `:Clone()` pour les "
            "999 suivants. 3x plus rapide."
        ),
        "category": "performance",
    },
    {
        "id": 49,
        "title": "Set Parent en dernier",
        "content": (
            "`local p = Instance.new('Part'); p.Color = Color3...; p.Size = ...; "
            "p.Parent = workspace`. Set le Parent EN DERNIER — sinon chaque "
            "propriété mise à jour trigger des replications inutiles au client."
        ),
        "category": "performance",
    },
    {
        "id": 50,
        "title": "Use Profile Service pour DataStore robuste",
        "content": (
            "Pour un projet sérieux, utilise la library open-source `ProfileService` "
            "(Loleris). Gère sessions, locks, auto-reconnect, migration. Évite "
            "les pertes de données et data races."
        ),
        "category": "data",
    },
    {
        "id": 51,
        "title": "Group invites pour gating premium",
        "content": (
            "Tu peux check si un joueur est dans ton groupe Roblox : "
            "`player:IsInGroup(groupId)`. Utilisé pour donner accès gratuit "
            "aux membres du groupe. Plus simple qu'un gamepass."
        ),
        "category": "monetization",
    },
    {
        "id": 52,
        "title": "TextChat (chat 2.0) > TextChatService.LegacyChat",
        "content": (
            "Roblox a un nouveau chat depuis 2023. Active `TextChatService.ChatVersion "
            "= TextChatVersion`. Plus moderne, plus customisable, supporte les "
            "channels et les commandes /commande."
        ),
        "category": "ux",
    },
    {
        "id": 53,
        "title": "Don't trust client time",
        "content": (
            "`tick()` côté client peut être manipulé par le joueur. Pour les "
            "cooldowns sensibles (anti-spam, daily reward), utilise `os.time()` "
            "côté serveur uniquement."
        ),
        "category": "security",
    },
    {
        "id": 54,
        "title": "Avoid creating LocalScript inside Folders",
        "content": (
            "LocalScript dans `workspace.Folder` n'exécute PAS. Il faut qu'il "
            "soit dans `StarterPlayer.StarterCharacterScripts`, "
            "`StarterPlayer.StarterPlayerScripts`, ou `StarterGui`. Sinon il "
            "ne tournera jamais."
        ),
        "category": "architecture",
    },
    {
        "id": 55,
        "title": "TypeChecker pour Lua : strict mode + types",
        "content": (
            "Mets `--!strict` en haut de tes scripts importants. Tu auras des "
            "warnings de type en Studio (script analysis). Détecte 80% des "
            "bugs avant runtime."
        ),
        "category": "code-quality",
    },
    {
        "id": 56,
        "title": "GUI inset auto avec Camera:GetGuiInset()",
        "content": (
            "Top bar Roblox prend ~36px en haut. Pour positionner une GUI "
            "qui ne soit pas masquée par la top bar, soustrais "
            "`game.GuiService:GetGuiInset().Y`."
        ),
        "category": "ui",
    },
    {
        "id": 57,
        "title": "AddTagListenChange > polling Folder",
        "content": (
            "Pour réagir quand un objet est tagué : `CollectionService:GetInstanceAddedSignal('Enemy')"
            ":Connect(spawn)`. Au lieu de poller un Folder, tu réagis à "
            "l'event."
        ),
        "category": "architecture",
    },
    {
        "id": 58,
        "title": "Replace `string.find` avec `string.match` pour patterns",
        "content": (
            "`string.find` retourne start/end positions. Si tu veux juste le "
            "matched substring, `string.match` est plus simple : "
            "`local name = string.match(input, '%a+')`."
        ),
        "category": "code-quality",
    },
    {
        "id": 59,
        "title": "Use `ipairs` pas `pairs` pour les tables séquentielles",
        "content": (
            "Pour itérer une liste `[1,2,3,4,5]`, `ipairs` est ~30% plus rapide "
            "que `pairs`. `pairs` itère TOUTES les clés (y compris non-numérique). "
            "Pour les arrays purs : ipairs."
        ),
        "category": "performance",
    },
    {
        "id": 60,
        "title": "Connection:Disconnect() pour éviter les leaks",
        "content": (
            "Si tu connectes un signal dans un script qui peut être détruit "
            "(NPC qui meurt), stocke la connection et fais "
            "`connection:Disconnect()` au cleanup. Sinon : memory leak."
        ),
        "category": "performance",
    },
]


def pick_random_tip(exclude_ids: Optional[list] = None) -> dict:
    """Pick un tip random qui n'est pas dans exclude_ids."""
    import random
    pool = STUDIO_TIPS
    if exclude_ids:
        pool = [t for t in STUDIO_TIPS if t["id"] not in exclude_ids]
    if not pool:
        pool = STUDIO_TIPS
    return random.choice(pool)


# ═══════════════════════════════════════════════════════════════════════════════
#  SPEEDRUN — Catégories par défaut (l'owner peut en ajouter via slash)
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_SPEEDRUN_CATEGORIES = [
    {
        "id": "obby_master",
        "name": "🏃 Obby Master",
        "description": "Finir l'obby principal en moins de temps possible.",
        "target_seconds": 120,
        "active": True,
    },
    {
        "id": "100_coins",
        "name": "💰 100 Coins Rush",
        "description": "Récolter 100 pièces le plus vite possible.",
        "target_seconds": 180,
        "active": True,
    },
    {
        "id": "boss_solo",
        "name": "⚔️ Boss Solo Kill",
        "description": "Vaincre le boss principal seul, le plus vite possible.",
        "target_seconds": 300,
        "active": True,
    },
    {
        "id": "speedrun_any",
        "name": "🎯 Any% (catégorie libre)",
        "description": "Une catégorie libre : finir le jeu de façon créative.",
        "target_seconds": 600,
        "active": True,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
#  MATCHMAKING — Jeux Roblox que les membres peuvent annoncer
# ═══════════════════════════════════════════════════════════════════════════════
#
# L'owner peut ajouter des jeux via slash. Ce catalogue par défaut est un
# squelette. Chaque jeu a un place_id Roblox que le bot embed quand quelqu'un
# crée une "party" pour ce jeu.

DEFAULT_MATCHMAKING_GAMES = [
    {
        "id": "main_game",
        "name": "🎮 Jeu Principal",
        "place_id": 0,  # owner remplace via /game_add
        "description": "Le jeu principal de la communauté.",
        "image_url": "",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════════════════════════════════════════════


def format_time(seconds: float) -> str:
    """Format un temps en secondes vers '1m23s456ms' ou '23.456s'."""
    if seconds < 60:
        return f"{seconds:.3f}s"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}m{s:06.3f}s"


def get_speedrun_category(cat_id: str, custom_categories: Optional[list] = None) -> Optional[dict]:
    pool = (custom_categories or []) + DEFAULT_SPEEDRUN_CATEGORIES
    for c in pool:
        if c["id"] == cat_id:
            return c
    return None


__all__ = [
    "STUDIO_TIPS", "DEFAULT_SPEEDRUN_CATEGORIES", "DEFAULT_MATCHMAKING_GAMES",
    "pick_random_tip", "format_time", "get_speedrun_category",
]
