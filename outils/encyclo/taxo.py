B=lambda *n:[x for x in n]
BOSS=["Big Boss Man","Crab","Octopusman","Yahu","Shark Sea King","Sharkman","Giant Squid","True Kraken","Kraken","Hippo","Kentucky Chicken","Sea Cow King","Alucard","Ugly Thanos","Monster","Praying Mantis","Aegon","Demon","Mink Boss","Blugori","Baldur","Golem","Brogy","Katame","Pica","Cat","Lion","Man Lee","Skypiean Boss 2","Skypiean Boss 3","Leviathan Mossando","Leviathan Taurus","Sky Serpent","Oars","Moria","Crocodile","Humandrill","Puffy the Goofy Dragon","King Neptune","Trench Boss"]
GUIDES={"Big Boss Man":"Big Boss Man Fight Guide","Green Leviathan":"Green Leviathan Boss Fight Guide","Black Leviathan":"Black Leviathan Boss Fight Guide"}
TAXO=[
 ("personnage","Personnage","Character",[
   ("races","Races","Races",["Races","Human","Beastman","Avalonian","Marinian","Cyborg","Lunars","Oni","Three Eyes","Giant","Dwarf"]),
   ("progression","Progression","Progression",["Leveling","Stats","Talents","Class","Reputation"]),
   ("apparence","Apparence","Appearance",["Character Customisation"]),
   ("sante","Santé","Health",["Illnesses","Status Effects","Cough Syrup"])]),
 ("pouvoirs","Pouvoirs","Powers",[
   ("fruits","Fruits du démon","God Fruits",["God Fruits"]),
   ("paramecia","Paramecia","Paramecia",["Rubber","Quake","Dough","Operation","Venom","Soul","Paw","Gravity","String","Barrier","Love","Revive","Bomb","Chop"]),
   ("logia","Logia","Logia",["Flame","Ice","Sand","Smoke Devil Fruit","Light","Dark","Rumble","Magma"]),
   ("zoan","Zoan","Zoan",["Dragon","Phoenix","Buddha","Mythical Wolf","Allosaurus","Leopard","Wolf","Giraffe","Falcon","Bison"]),
   ("haki","Haki","Haki",["Haki","Armament Haki","Observation Haki","Conquerors Haki"]),
   ("cartes_haki","Cartes de Haki","Haki cards",["Opp E. Heimer","Tom E. Dison","Ein S. Tein","Dar D. Win","New D. Ton","Geng D. Khan","Go D. Zilla","Julius C. Zar"]),
   ("styles","Styles de combat","Fighting styles",["Fighting Styles"]),
   ("affiches","Affiches","Posters",["Posters","Agile Posters","Fierce Posters","Tactic Posters","Flash Dash","Mr Widestep","Sir Pitcher","Geppo Master","Jumper","Faster Punch","Strong Tilt","M1 God","Ronaldo Trip"])]),
 ("combat","Combat & armes","Combat & weapons",[
   ("mecaniques","Mécaniques de combat","Combat mechanics",["Combat Mechanics","Parkour"]),
   ("armes","Armes","Weapons",["Weapons","Katana","Great Axe","Flintlock","Ignis Dagger","Golden Hook","Katakuri's Trident","Soul Cane","Leviathan Sword","Leviathan Katana","Leviathan Cutlass","Leviathan Cleaver","Leviathan Bazooka"]),
   ("ameliorer","Améliorer & enchanter","Upgrade & enchant",["Upgrading","Enchants","Materials"]),
   ("equipement","Équipement & objets","Gear & items",["Equipment","Accessories","Utility Tool","Grappling hook","Paraglider","Shell Phone","Lock Pick","Handcuffs","Shovel","Traders bag","Fishing rod","Ship in a bottle","Currencies"])]),
 ("mer","Mer & navires","Sea & ships",[
   ("naviguer","Naviguer","Sailing",["Sailing","Navigation","Sea Exploration","The seven layers","Weather"]),
   ("navires","Navires","Ships",["Ship Customisation","Basic Sail","Figurehead","Steering Wheel","Cannon","Mortar Cannons","Wood Plank"]),
   ("sousmarins","Sous-marins","Submarines",["Submarines"]),
   ("montures","Montures","Mounts",["Mounts","Owl","Whale"])]),
 ("metiers","Métiers","Professions",[
   ("cuisine","Cuisine","Cooking",["Cooking"]),
   ("peche","Pêche","Fishing",["Fishing","Fishes"]),
   ("artisanat","Artisanat & récolte","Crafting & gathering",["Crafting","Mining","Woodcutting"]),
   ("vol","Vol","Thieving",["Thieving"]),
   ("dex","Dex","Dexes",["Dexes","Dexes/Adventure Dex","Dexes/Fishing Dex","Dexes/Recipe Dex","Dexes/Craftsman Dex"])]),
 ("monde","Monde","World",[
   ("monde_ouvert","Monde & lieux","World & places",["Open World","Locations","Islands","Marine Bases","Hades asylum","Chests"]),
   ("factions","Factions","Factions",["Factions","Factions/World Seas Marine Corps","Factions/Pirates","Factions/World Seas Government","Factions/Arms of Revolution","Official Crews"]),
   ("pnj","Personnages non joueurs","NPCs",["NPCs","Rell C. Sparrow","Riven A. Graves","Rambo","Tutorial","Missions"]),
   ("faune","Faune & ennemis","Wildlife & enemies",["Wildlife","Sea Beast","Enemies"]),
   ("evenements","Événements","Events",["Land Events","Camp event","Random Events","Sea Events"])]),
 ("boss","Boss","Bosses",[("liste_boss","Tous les boss","All bosses",["Bosses"]+BOSS)]),
 ("modes","Modes & interface","Modes & interface",[
   ("modes_jeu","Modes de jeu","Game modes",["Gamemodes","Crew Battles","Battlegrounds","Ranked"]),
   ("interface","Interface","Interface",["UI Explanation","Settings","Starter Guide"]),
   ("boutique","Boutique & abonnements","Store & subscriptions",["Monetisation","Discord Subscriptions"]),
   ("ambiance","Musique & sons","Music & sound",["Soundtracks","RELL Seas sounds"]),
   ("retire","Contenu retiré","Cut content",["Cut Content"])]),
]
GABARITS={
 "fruit":[("Classe","Class"),("Rareté","Rarity"),("Prix","Price"),("Obtention","Obtainment"),("Attaques","Moves"),("Dégâts / DPS","Damage / DPS"),("Passif","Passive")],
 "race":[("Taux d'obtention","Race rate"),("Sous-espèces","Subspecies"),("Bonus","Buffs"),("Style de combat","Fighting style"),("Apparence modifiée","Appearance changes")],
 "boss":[("Lieu","Location"),("Points de vie","HP"),("Difficulté","Difficulty"),("Apparition","Spawning"),("Récompenses","Rewards"),("Classification","Classification")],
 "arme":[("Type","Weapon type"),("Grade","Grade"),("Obtention","How to obtain"),("Améliorations","Upgrades"),("Dégâts","Damage")],
 "carte":[("Forme de Haki","Haki form"),("Effet","Effect"),("Obtention","Obtainment")],
 "affiche":[("Type","Type"),("Effet","Effect"),("Obtention","Obtainment")],
 "monture":[("Classe","Class"),("Places","Seats"),("Obtention","Obtainment")],
}
SOUS_GABARIT={"paramecia":"fruit","logia":"fruit","zoan":"fruit","races":"race","liste_boss":"boss","armes":"arme","cartes_haki":"carte","affiches":"affiche","montures":"monture"}
