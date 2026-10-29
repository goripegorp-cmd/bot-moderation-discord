import json,hashlib,os
from PIL import Image, ImageSequence
c=json.load(open('carte_images.json'));L=json.load(open('imgs.json'))
h={u:hashlib.sha1(u.encode()).hexdigest()[:16] for u in L};fait={}
for u,e in c.items():
    if 'video' not in e: continue
    nom=e['video'].replace('.mp4','-anim.webp')
    if nom not in fait:
        im=Image.open('brut/'+h[u]);W=min(560,im.size[0]);fr=[];du=[]
        for i,f in enumerate(ImageSequence.Iterator(im)):
            g=f.convert('RGBA');H=round(g.size[1]*W/g.size[0]);fr.append(g.resize((W,H),Image.LANCZOS));du.append(f.info.get('duration',80) or 80)
        fr[0].save('out/'+nom,'WEBP',save_all=True,append_images=fr[1:],duration=du,loop=0,quality=68,method=4)
        fait[nom]=1
    e['anim']=nom; e.pop('video',None)
json.dump(c,open('carte_images.json','w'),ensure_ascii=False)
for f in os.listdir('out'):
    if f.endswith('.mp4'): os.remove('out/'+f)
print(len(fait))
