import os,json,hashlib,re,subprocess,urllib.parse
from PIL import Image, ImageSequence
L=json.load(open('imgs.json'));m={hashlib.sha1(u.encode()).hexdigest()[:16]:u for u in L}
def dh(im):
    g=im.convert('L').resize((17,16));p=list(g.getdata())
    return sum(1<<i for i in range(256) if p[(i//16)*17+i%16]>p[(i//16)*17+i%16+1])
def slug(u):
    n=urllib.parse.unquote(u.split('/images/')[1].split('/')[2]);n=re.sub(r'\.(png|jpe?g|gif|webp)$','',n,flags=re.I)
    return re.sub(r'[^a-z0-9]+','-',n.lower()).strip('-')[:60]
carte={};vus=[];noms=set()
for h,u in sorted(m.items(),key=lambda x:x[1]):
    f='brut/'+h
    if not os.path.exists(f): continue
    try: im=Image.open(f)
    except Exception: continue
    w,hh=im.size;anim=getattr(im,'n_frames',1)>1
    if max(w,hh)<32: continue
    im.seek(0);fr=im.convert('RGBA');d=dh(fr.convert('RGB'))
    dup=next((v for v in vus if bin(v[0]^d).count('1')<=3 and abs(v[2]/v[3]-w/hh)<.05),None)
    if dup:
        carte[u]=carte[dup[1]];continue
    s=slug(u);base=s;i=2
    while s in noms: s=f'{base}-{i}';i+=1
    noms.add(s)
    W=min(960,w);H=round(hh*W/w)
    poster=fr.resize((W,H),Image.LANCZOS) if W!=w else fr
    poster.save(f'out/{s}.webp','WEBP',quality=84,method=6)
    e={'src':f'{s}.webp','w':W,'h':H}
    if anim:
        VW=min(640,w)//2*2
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',f,'-movflags','+faststart','-pix_fmt','yuv420p','-vf',f'scale={VW}:-2:flags=lanczos','-c:v','libx264','-crf','27','-preset','slow','-an',f'out/{s}.mp4'],check=False)
        if os.path.exists(f'out/{s}.mp4'): e['video']=f'{s}.mp4'
    carte[u]=e;vus.append((d,u,w,hh))
json.dump(carte,open('carte_images.json','w'),ensure_ascii=False)
print(len(carte),'liens',len(vus),'uniques')
