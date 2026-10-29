import json, os, re, urllib.parse, sys
from bs4 import BeautifulSoup, NavigableString, Tag
BROU = re.compile(r"(?i)lorem ipsum|placeholder|nothing is true|nothing here yet|to be (?:added|written)|\bwip\b|^\s*(unknown|example|tba|tbd|n/?a|\?+)\s*$|page under construction|undergoing mantinence")
def img_src(im):
    s = im.get("data-src") or im.get("src") or ""
    if s.startswith("data:"): return None
    m = re.match(r"(https://static\.wikia\.nocookie\.net/[^/]+/images/[^/]+/[^/]+/[^/]+)", s)
    if not m: return None
    nom = urllib.parse.unquote(m.group(1).rsplit("/",1)[1])
    if re.search(r"(?i)NavigationBG|site-logo|Wiki-wordmark|favicon|Frame|Button|Placeholder|No_image|Noimage", nom): return None
    return m.group(1) + "/revision/latest"
def txt(n):
    for br in n.find_all("br"): br.replace_with(" ")
    return re.sub(r"\s+", " ", n.get_text(" ")).strip().replace(" ,", ",").replace(" .", ".").replace("( ", "(").replace(" )", ")")
def ok(t): return t and not BROU.search(t)
def cellule(td):
    ims = [img_src(i) for i in td.find_all("img")]; ims = [i for i in ims if i]
    return {"x": txt(td), "img": ims[0] if ims else None}
def parcours(racine, out):
    for n in list(racine.children):
        if isinstance(n, NavigableString):
            continue
        if not isinstance(n, Tag): continue
        cl = " ".join(n.get("class", []))
        if n.name in ("script","style") or "mw-editsection" in cl or "custom-tabs" in cl or "toc" == n.get("id") or "notice" in cl.lower() or "hatnote" in cl.lower(): continue
        if n.name == "aside" and "portable-infobox" in cl:
            ib = {"t":"infobox","titre":"", "images":[], "champs":[]}
            h = n.find(class_="pi-title"); ib["titre"] = txt(h) if h else ""
            for f in n.find_all("figure"):
                for im in f.find_all("img"):
                    s = img_src(im)
                    if s and s not in ib["images"]: ib["images"].append(s)
            for d in n.find_all(class_="pi-data"):
                l = d.find(class_="pi-data-label"); v = d.find(class_="pi-data-value")
                if l and v and ok(txt(v)): ib["champs"].append([txt(l), txt(v)])
            out.append(ib); continue
        if n.name in ("h2","h3","h4"):
            t = txt(n.find(class_="mw-headline") or n)
            if t: out.append({"t":"h", "n": int(n.name[1]), "x": t})
            continue
        if n.name == "p":
            ims = [img_src(i) for i in n.find_all("img")]; ims=[i for i in ims if i]
            t = txt(n)
            if ok(t) and len(t) > 1: out.append({"t":"p","x":t})
            for i in ims: out.append({"t":"img","src":i,"leg":""})
            continue
        if n.name in ("ul","ol"):
            items = []
            for li in n.find_all("li", recursive=False):
                t = txt(li)
                ims=[img_src(i) for i in li.find_all("img")]; ims=[i for i in ims if i]
                if ok(t) or ims: items.append({"x": t if ok(t) else "", "img": ims[0] if ims else None})
            if items: out.append({"t":"liste","items":items})
            continue
        if n.name == "table":
            lignes = []
            for tr in n.find_all("tr"):
                c = [cellule(td) for td in tr.find_all(["td","th"], recursive=False)]
                if c and any(x["x"] or x["img"] for x in c): lignes.append(c)
            if lignes: out.append({"t":"table","lignes":lignes})
            continue
        if "NavButton" in cl:
            lab = n.find(class_="NavLabel"); im = n.find(class_="NavImage")
            s = img_src(im.find("img")) if im and im.find("img") else None
            if lab and ok(txt(lab)): out.append({"t":"carte","x":txt(lab),"img":s})
            continue
        if "HomepageFrameHeaderInside" in cl:
            t = txt(n).strip("[] ")
            if ok(t): out.append({"t":"h","n":4,"x":t.title() if t.isupper() else t})
            continue
        if "wds-tabs__wrapper" in cl:
            continue
        if "wds-tab__content" in cl:
            # étiquette de l'onglet
            continue_label = n.get("data-label")
        if n.name == "figure" or "thumb" in cl.split() or "gallerybox" in cl or "wikia-gallery-item" in cl:
            ims=[img_src(i) for i in n.find_all("img")]; ims=[i for i in ims if i]
            cap = n.find(["figcaption"]) or n.find(class_=re.compile("caption|gallerytext|lightbox-caption"))
            for i in ims[:1]: out.append({"t":"img","src":i,"leg":txt(cap) if cap and ok(txt(cap)) else ""})
            continue
        if n.name == "img":
            s = img_src(n)
            if s: out.append({"t":"img","src":s,"leg":""})
            continue
        # onglets : récupérer les libellés
        if "tabber" in cl:
            labs = [txt(li) for li in n.select(".wds-tabs__tab")]
            conts = n.find_all(class_="wds-tab__content", recursive=False) or n.select(":scope > div > .wds-tab__content")
            if not conts: conts = n.find_all(class_="wds-tab__content")
            for i, c in enumerate(conts):
                if i < len(labs) and labs[i]: out.append({"t":"h","n":4,"x":labs[i]})
                parcours(c, out)
            continue
        parcours(n, out)
def page(d):
    s = BeautifulSoup(d["text"], "html.parser")
    racine = s.find(class_="mw-parser-output") or s
    out = []; parcours(racine, out)
    # fusion des cartes et images consécutives
    res = []
    for b in out:
        if b["t"] == "carte":
            if res and res[-1]["t"] == "cartes": res[-1]["items"].append(b)
            else: res.append({"t":"cartes","items":[b]})
        elif b["t"] == "img":
            if res and res[-1]["t"] == "galerie": res[-1]["items"].append(b)
            else: res.append({"t":"galerie","items":[b]})
        else: res.append(b)
    # sections vides
    final = []
    for i,b in enumerate(res):
        if b["t"] == "h":
            suite = next((x for x in res[i+1:] if not (x["t"]=="h" and x["n"]>b["n"])), None)
            j = res.index(b)+1
            if j >= len(res) or (res[j]["t"]=="h" and res[j]["n"]<=b["n"]): continue
        final.append(b)
    return {"titre": d["title"], "cats":[c["category"] for c in d.get("categories",[]) if not c.get("hidden")], "blocs": final}
if __name__ == "__main__":
    for t in sys.argv[1:]:
        d = json.load(open("pages/"+urllib.parse.quote(t,safe="")+".json"))
        print(json.dumps(page(d), ensure_ascii=False, indent=0)[:4000]); print("=====")
