import json,re,shutil,os,sys
D=json.load(open('encyclo_en.json'));FR=json.load(open('fr/dico.json'));IM=json.load(open('carte_images.json'))
P=D['pages']
REGLES=[(r"^The current (?:spawn method|location) for (.+?) is (?:currently )?unknown\.?$",r"Apparition de \1 : inconnue"),
 (r"^The Items needed to spawn.*unknown.*$","Objets pour le faire apparaître : inconnus"),
 (r"^(?:His|Its|It's) (?:current )?location is (?:currently )?unknown\.?$","Emplacement : inconnu"),
 (r"^(?:Pre-release|pre-release|Pre-Release)$","Avant la sortie")]
def fr(x):
    if not x: return x
    if x in FR: return FR[x]
    for a,b in REGLES:
        if re.match(a,x,re.I): return re.sub(a,b,x,flags=re.I)
    return None
TITRES={"Races":"Les races","Human":"Humain","Giant":"Géant","Dwarf":"Nain","Leveling":"Niveaux","Stats":"Statistiques","Talents":"Talents","Class":"Classe","Reputation":"Réputation","Character Customisation":"Création du personnage","Illnesses":"Maladies","Status Effects":"Effets de statut","God Fruits":"Les Fruits du démon","Haki":"Le Haki","Armament Haki":"Haki de l'Armement","Observation Haki":"Haki de l'Observation","Conquerors Haki":"Haki des Rois","Fighting Styles":"Styles de combat","Posters":"Les affiches","Agile Posters":"Affiches Agile","Fierce Posters":"Affiches Fierce","Tactic Posters":"Affiches Tactic","Combat Mechanics":"Mécaniques de combat","Weapons":"Les armes","Upgrading":"Amélioration","Enchants":"Enchantements","Materials":"Matériaux","Equipment":"Équipement","Accessories":"Accessoires","Currencies":"Monnaies","Sailing":"Navigation","Navigation":"Orientation","Sea Exploration":"Exploration marine","The seven layers":"Les sept couches","Weather":"Météo","Ship Customisation":"Personnaliser son navire","Figurehead":"Figure de proue","Basic Sail":"Voile et emblème","Steering Wheel":"Barre du navire","Cannon":"Canons","Mortar Cannons":"Mortiers","Wood Plank":"Matériaux de coque","Submarines":"Sous-marins","Mounts":"Les montures","Cooking":"Cuisine","Fishing":"Pêche","Fishes":"Poissons et créatures","Crafting":"Artisanat","Mining":"Minage","Woodcutting":"Bûcheronnage","Thieving":"Vol","Dexes":"Les Dex","Open World":"Monde ouvert","Locations":"Lieux","Islands":"Îles","Marine Bases":"Bases de la Marine","Chests":"Coffres","Factions":"Les factions","Factions/World Seas Marine Corps":"La Marine","Factions/Pirates":"Les Pirates","Factions/World Seas Government":"Le Gouvernement mondial","Factions/Arms of Revolution":"Arms of Revolution","Official Crews":"Équipages officiels","NPCs":"PNJ","Tutorial":"Tutoriel","Missions":"Missions","Wildlife":"Faune","Enemies":"Ennemis","Land Events":"Événements terrestres","Camp event":"Événement de camp","Random Events":"Événements aléatoires","Sea Events":"Événements en mer","Bosses":"Les boss","Gamemodes":"Modes de jeu","UI Explanation":"L'interface","Settings":"Paramètres","Starter Guide":"Guide du débutant","Monetisation":"Boutique","Discord Subscriptions":"Abonnements Discord","Soundtracks":"Musiques","RELL Seas sounds":"Sons du jeu","Cut Content":"Contenu retiré","Parkour":"Parkour","Utility Tool":"Utility Tool","Hades asylum":"Hades' Asylum","Smoke Devil Fruit":"Smoke"}
CHAMPS={"classe":r"^(class|type)$","rarete":r"rarity","prix":r"price|cost","obtention":r"obtain|obtainment","lieu":r"location","pv":r"^hp$","difficulte":r"difficulty","classification":r"classification","recompenses":r"reward","apparition":r"spawn","type":r"weapon type|^type$","grade":r"grade","ameliorations":r"upgrade","effet":r"description|effect","places":r"seats","taux":r"race rate","bonus":r"buff","style":r"fighting style","apparence":r"appearance","surnom":r"aka"}
GAB={"fruit":[("classe","Classe","Class"),("rarete","Rareté","Rarity"),("prix","Prix","Price"),("obtention","Obtention","Obtainment"),("attaques","Attaques","Moves"),("dps","Dégâts / DPS","Damage / DPS")],
 "race":[("taux","Taux d'obtention","Race rate"),("sous","Sous-espèces","Subspecies"),("bonus","Bonus","Buffs"),("style","Style de combat","Fighting style"),("apparence","Apparence modifiable","Appearance changes")],
 "boss":[("surnom","Surnom","AKA"),("lieu","Emplacement","Location"),("pv","Points de vie","HP"),("difficulte","Difficulté","Difficulty"),("apparition","Apparition","Spawning"),("recompenses","Récompenses","Rewards"),("classification","Classification","Classification")],
 "arme":[("type","Type","Type"),("grade","Grade","Grade"),("obtention","Obtention","How to obtain"),("ameliorations","Améliorations","Upgrades"),("dps","Dégâts","Damage")],
 "carte":[("forme","Forme de Haki","Haki form"),("effet","Effet","Effect"),("obtention","Obtention","Obtainment")],
 "affiche":[("type","Type","Type"),("effet","Effet","Effect"),("obtention","Obtention","Obtainment")],
 "monture":[("classe","Classe","Class"),("places","Places","Seats"),("obtention","Obtention","Obtainment")]}
def slug(t): return re.sub(r'[^a-z0-9]+','-',t.lower()).strip('-')
def bloc(b):
    T=b['t'];o={'t':T}
    if T in('h','p'):
        o['x']=b['x'];f=fr(b['x'])
        if f and f!=b['x']: o['f']=f
        if T=='h': o['n']=b['n']
    elif T in('liste','cartes'):
        o['items']=[]
        for i in b['items']:
            it={'x':i['x']};f=fr(i['x'])
            if f and f!=i['x']: it['f']=f
            if i.get('img'): it['img']=i['img']
            o['items'].append(it)
    elif T=='galerie':
        o['items']=[]
        for i in b['items']:
            it={'img':i['src']}
            if i.get('leg'):
                it['x']=i['leg'];f=fr(i['leg'])
                if f and f!=i['leg']: it['f']=f
            o['items'].append(it)
    elif T=='table':
        o['lignes']=[[dict({'x':c['x']},**({'f':fr(c['x'])} if fr(c['x']) and fr(c['x'])!=c['x'] else {}),**({'img':c['img']} if c['img'] else {})) for c in r] for r in b['lignes']]
    elif T=='infobox':
        o['images']=b['images'];o['champs']=[[a,fr(a) or a,v,fr(v) or v] for a,v in b['champs']]
    return o
pages={};sous_de={}
for c in D['taxo']:
    for s in c[3]:
        for p in s[3]: sous_de.setdefault(p,s[0])
for k,p in P.items():
    if k not in sous_de: continue
    bl=[bloc(b) for b in p['blocs'] if not (b['t'] in('h','p') and re.search(r'(?i)placeholder|undergoing mantinence',b['x']))]
    ib=next((b for b in p['blocs'] if b['t']=='infobox'),None)
    img=(ib['images'][0] if ib and ib['images'] else None) or next((i['src'] for b in p['blocs'] if b['t']=='galerie' for i in b['items']),None)
    s=sous_de[k];g=D['sous_gabarit'].get(s);fiche=[]
    if k in ('Races','Weapons','Bosses','Posters','Agile Posters','Fierce Posters','Tactic Posters','Mounts'): g=None
    if g:
        vals={}
        for a,v in (ib['champs'] if ib else []):
            for cle,rx in CHAMPS.items():
                if re.search(rx,a,re.I) and cle not in vals: vals[cle]=v
        if g=='fruit': vals['classe']={'paramecia':'Paramecia','logia':'Logia','zoan':'Zoan'}[s] if 'Mythical' not in str(vals.get('classe','')) else vals['classe']
        if g=='fruit':
            mv=[i['leg'] for b in p['blocs'] if b['t']=='galerie' for i in b['items'] if i['src'].get('anim') and i.get('leg') and not re.search(r'(?i)cutscene|icon|status|gallery',i['leg'])]
            if mv: vals['attaques']=', '.join(dict.fromkeys(mv))
        if g=='race':
            for i,b in enumerate(p['blocs']):
                if b['t']=='h' and 'subspecies' in b['x'].lower():
                    nb=next((x for x in p['blocs'][i+1:] if x['t']=='liste'),None)
                    if nb: vals['sous']=', '.join(it['x'] for it in nb['items'])
        if g=='carte':
            for f2,lab in (('Observation','Observation'),('Conqueror','Rois'),('Armament','Armement')):
                if any(f2.lower() in json.dumps(b).lower() for b in p['blocs'][:4]): vals['forme']=lab;break
        for cle,lfr,len_ in GAB[g]:
            v=vals.get(cle);fiche.append([lfr,len_,(fr(v) or v) if v else None,v])
    pages[slug(k)]={'nom':k,'nom_fr':TITRES.get(k) if TITRES.get(k)!=k else None,'url':p['url'],'img':img,'fiche':fiche,'blocs':bl}
cats=[{'id':c[0],'fr':c[1],'en':c[2],'sous':[{'id':s[0],'fr':s[1],'en':s[2],'gabarit':D['sous_gabarit'].get(s[0]),'pages':[slug(x) for x in s[3] if slug(x) in pages]} for s in c[3]]} for c in D['taxo']]
EMO=re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u3164\u200b]")
def nettoie_txt(v):
    v=re.sub(r'\s+',' ',EMO.sub('',v)).strip()
    return '' if re.search(r'(?i)placeholder|___',v) else v
def propre(o):
    if isinstance(o,dict): return {k:(nettoie_txt(v) if isinstance(v,str) and k in('x','f') else propre(v)) for k,v in o.items()}
    if isinstance(o,list): return [propre(v) if not isinstance(v,str) else re.sub(r'\s+',' ',EMO.sub('',v)).strip() for v in o]
    return o
pages=propre(pages)
out={'source':'https://rellseas.fandom.com','licence':'CC BY-SA 3.0','releve':'2026-10-29','cats':cats,'pages':pages}
json.dump(out,open('encyclo.json','w'),ensure_ascii=False,separators=(',',':'))
# images utilisées
util=set()
def parcourt(o):
    if isinstance(o,dict):
        if 'src' in o and 'w' in o: util.add(o['src']); o.get('anim') and util.add(o['anim'])
        for v in o.values(): parcourt(v)
    elif isinstance(o,list):
        for v in o: parcourt(v)
parcourt(out)
os.makedirs('final/encyclo',exist_ok=True)
for f in os.listdir('final/encyclo'): os.remove('final/encyclo/'+f)
for f in util: shutil.copy('out/'+f,'final/encyclo/'+f)
print(len(pages),'pages',os.path.getsize('encyclo.json')//1024,'Ko',len(util),'images')
sans=[k for k,p in pages.items() if p['fiche'] and all(x[2] is None for x in p['fiche'])];print('fiches vides',len(sans))
nonfr=sum(1 for p in pages.values() for b in p['blocs'] if b['t']=='p' and 'f' not in b);print('paragraphes sans FR',nonfr)
