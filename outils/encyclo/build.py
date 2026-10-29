import json,re,collections,taxo
t=json.load(open('en.json'));IM=json.load(open('carte_images.json'))
# guides fusionnés
for k in list(t):
    m=re.match(r'(.+?) (?:Boss )?Fight Guide$',k)
    if m:
        cible=m.group(1)
        if cible in t:
            vus={json.dumps(b,sort_keys=True) for b in t[cible]['blocs']}
            t[cible]['blocs']+= [b for b in t[k]['blocs'] if json.dumps(b,sort_keys=True) not in vus and b['t']!='infobox']
        else: t[cible]=t[k]; t[cible]['titre']=cible
        del t[k]
BOSS=taxo.BOSS+["Green Leviathan","Black Leviathan"]
for c in taxo.TAXO:
    for s in c[3]:
        if s[0]=='liste_boss': s[3][:]=["Bosses"]+BOSS
# gabarit : textes répétés
def cle_ligne(r): return ' | '.join(c['x'] for c in r)
cnt=collections.Counter()
for p in t.values():
    s=set()
    for b in p['blocs']:
        if b['t']=='p': s.add(b['x'])
        for i in b.get('items',[]): s.add(i.get('x',''))
        for r in b.get('lignes',[]): s.add(cle_ligne(r))
    cnt.update(s)
VIDE=re.compile(r"^[\s?|ONXY/✔❌\-–—]*$|^(n/?a|none|\.\.\.|\?+|unknown|currently unknown\.?)$",re.I)
JUNK=re.compile(r"(?i)^https?://|\(placeholder|trafalgar|^placeholder|welcome to the .rell seas. wiki|control \+ f|upload mp3|undergoing mantinence|no trivia available|feel free to write|currect showcase|^rell seas rell seas is|^placeholder text|^missions\.\.\.$|^owl\.+$|javascript|discordintegrator|^contribute$|^join the discord$|duis aute|excepteur sint|ut enim ad|sed ut perspiciatis|tempor incididunt|^\((any|we do not|this is a place|tips and tricks will|some random|if any|there is no known|note: on release|this contents|more subspecies|exp gain)|^[.,\s]+$|^(advertisement|contribute)$|^\(.*\b(include|insert|add|describe|write)\b.*\)$|no trivia at the moment|feel free to share|insert gif|template:|lorem|ipsum|consectetur|this weapon can be obtained\.\.\.|is unknown, but we will keep|safe to assume|^obtainment: unknown$|\?\?\?")
def bon(x,n_ok=4): return x and not VIDE.match(x) and not JUNK.search(x) and cnt[x]<=n_ok
CH_KO=re.compile(r"(?i)^(\?+|\.\.\.|unknown|grade \?|0/20|★★★★☆|starter boss/unknown|phase 1: unknown phase 2: unknown)$|\?\?\?")
def nom_fichier(u):
    n=re.sub(r'.*/images/./../([^/]+)/.*',r'\1',u);n=re.sub(r'\.(gif|png|webp|jpe?g)$','',n,flags=re.I)
    n=re.sub(r'[_-]+',' ',n);n=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',n);n=re.sub(r'\s*\d+$','',n).strip()
    return n[:1].upper()+n[1:]
def img(u):
    if not u or re.search(r'(?i)frog|notice|construction|stub',u): return None
    e=IM.get(u); return e and dict(e)
def nettoie(p):
    out=[]
    for b in p['blocs']:
        T=b['t']
        if T=='p' and (not bon(b['x']) or b['x'].strip('" ')==p['titre']): continue
        if T=='liste':
            b['items']=[dict(i,img=img(i['img'])) for i in b['items'] if bon(i['x']) or (not i['x'] and img(i['img']))]
            if not b['items']: continue
        if T=='cartes':
            b['items']=[dict(i,img=img(i['img'])) for i in b['items'] if bon(i['x'],99)]
            if not b['items']: continue
        if T=='galerie':
            b['items']=[dict(i,src=img(i['src']),leg=i['leg'] or (nom_fichier(i['src']) if img(i['src']).get('anim') else '')) for i in b['items'] if img(i['src'])]
            if not b['items']: continue
        if T=='table':
            L=[]
            for r in b['lignes']:
                k=cle_ligne(r)
                if not bon(k) and not any(img(c['img']) for c in r): continue
                L.append([{'x':c['x'] if not VIDE.match(c['x']) else '','img':img(c['img'])} for c in r])
            if len(L)<2: continue
            b['lignes']=L
        if T=='infobox':
            b['champs']=[[a,v] for a,v in b['champs'] if not CH_KO.search(v.strip())]
            b['images']=[img(u) for u in b['images'] if img(u)]
        out.append(b)
    NOMI=re.compile(r"\s*\((?:the )?[A-Z][a-z]+ ?[A-Z]?[a-z]+ [Nn]o [Mm]i[^)]*\)|^The [A-Z][a-z]+ [A-Za-z]+ no Mi(, Model: [^ ]+( [^ ]+)*?)? (?=is)")
    for b in out:
        if b['t']=='p': b['x']=re.sub(r'\s+',' ',NOMI.sub(lambda m: '' if m.group(0).strip().startswith('(') else 'This fruit ',b['x'])).replace(' -type',' type').strip()
        if b['t']=='infobox': b['champs']=[[a,v] for a,v in b['champs'] if a.lower()!='japanese']
    # anecdotes One Piece (hors RELL) dans les sections Trivia
    OP=re.compile(r"(?i)\b(?:one piece|mihawk|kuraigana|thriller bark|cipher pol|chipher pol|anime|arlong|fishman island|trafalgar|kuma\b|marshall d|teach|the clown|empress|amazon lily|baroque|yomi yomi|mochi mochi|mero mero|suna suna|yami yami|bara bara no mi fruit|roronoa|nami|usopp|sanji|chopper|robin|franky|jinbe|shanks|garp|sengoku|rob lucci|smoker|fujitora|ryokugyu|luffy|straw hat|whitebeard|blackbeard|big mom|kizaru|borsalino|baggy|hancock|bartolomeo|katakuri|brook|sabo|portgas|akainu|aokiji|enel|crocodile, |doflamingo|law,|trafalgar|marco|kaido|zoro|cross guild|no mi fruit|possesses the power of|holds the power|wielder of the)\b")
    sec='';o2=[]
    for b in out:
        if b['t']=='h': sec=b['x'].lower()
        if b['t']=='p' and OP.search(b['x']): continue
        if b['t'] in('liste','galerie'):
            b['items']=[i for i in b['items'] if not OP.search(i.get('x','') or i.get('leg',''))]
            if not b['items']: continue
        o2.append(b)
    out=o2
    # quasi-doublons
    import difflib
    o2=[]
    for b in out:
        if b['t']=='p' and any(x['t']=='p' and difflib.SequenceMatcher(None,x['x'],b['x']).ratio()>.8 for x in o2): continue
        o2.append(b)
    out=o2
    # retire titres sans contenu
    res=[]
    for i,b in enumerate(out):
        if b['t']=='h':
            nxt=next((x for x in out[i+1:]),None)
            if nxt is None or (nxt['t']=='h' and nxt['n']<=b['n']): continue
        res.append(b)
    # images en double dans la page
    vus=set()
    for b in res:
        if b['t']=='galerie':
            b['items']=[i for i in b['items'] if i['src']['src'] not in vus and not vus.add(i['src']['src'])]
        for i in (b.get('images') or []): vus.add(i['src'])
        for i in b.get('items',[]) if b['t'] in('cartes','liste') else []:
            if i.get('img'): vus.add(i['img']['src'])
    res=[b for b in res if not (b['t']=='galerie' and not b['items'])]
    return res
pages={}
for k,p in t.items():
    pages[k]={'titre':k,'url':'https://rellseas.fandom.com/wiki/'+k.replace(' ','_'),'blocs':nettoie(p)}
json.dump({'taxo':taxo.TAXO,'gabarits':taxo.GABARITS,'sous_gabarit':taxo.SOUS_GABARIT,'pages':pages},open('encyclo_en.json','w'),ensure_ascii=False)
n=sum(len(json.dumps(p['blocs'],ensure_ascii=False)) for p in pages.values())
vides=[k for k,p in pages.items() if not any(b['t'] in('p','liste','table','cartes') for b in p['blocs'])]
print(len(pages),'pages',n//1024,'Ko ; sans texte:',len(vides),vides[:60])
