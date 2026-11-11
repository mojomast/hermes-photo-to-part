from pathlib import Path
import urllib.request,urllib.parse,hashlib,shutil,json
from PIL import Image
r=Path(__file__).resolve().parents[1];repo=r.parent;commit='be886d0f57f803e4ef9019db03af7014f67c2b4f';items=[]
def record(p,url,license):
 item={'path':str(p.relative_to(r)),'url':url,'license':license,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'transform':'unchanged'}
 if p.suffix.lower() in ['.jpg','.png']:item['dimensions']=list(Image.open(p).size)
 items.append(item)
def download(url,p,license):
 p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists():
  req=urllib.request.Request(url,headers={'User-Agent':'PhotoToPartShowcase/1.0 (public CC0 video production)'})
  with urllib.request.urlopen(req,timeout=60) as q:p.write_bytes(q.read())
 record(p,url,license)
for source in ['video-kit/assets/gear-pane-ready.png','video-kit/assets/strap-hinge-pane-ready.png','video-kit/assets/strap-hinge-pane-ready-2.png','docs/catalog-banner.png','docs/screenshot-views.png']:
 p=r/'assets/images'/Path(source).name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/source,p);record(p,f'https://github.com/mojomast/hermes-photo-to-part/blob/{commit}/{source}','User-supplied video kit; repository MIT')
for url,name,credit in [('https://upload.wikimedia.org/wikipedia/commons/6/6b/Zahnrad.jpg','gear-photo.jpg','Paolo Neo, CC0'),('https://upload.wikimedia.org/wikipedia/commons/2/2d/Strap_Hinge_MET_cdi55-61-56.jpg','hinge-photo.jpg','The Metropolitan Museum of Art, CC0')]:download(url,r/'assets/images'/name,credit)
for family,file,role in [('barlowcondensed','BarlowCondensed-Bold.ttf','Display'),('manrope','Manrope[wght].ttf','Sans'),('dmmono','DMMono-Medium.ttf','Mono')]:
 base=f'https://raw.githubusercontent.com/google/fonts/main/ofl/{family}/';download(base+urllib.parse.quote(file),r/f'assets/fonts/{role}.ttf','SIL Open Font License 1.1');download(base+'OFL.txt',r/f'assets/fonts/{family}-OFL.txt','SIL Open Font License 1.1')
(r/'assets/licenses').mkdir(exist_ok=True);shutil.copy2(repo/'LICENSE',r/'assets/licenses/repository-MIT.txt');shutil.copy2(repo/'video-kit/README.md',r/'assets/BRIEF.md');(r/'assets/provenance.json').write_text(json.dumps({'commit':commit,'assets':items},indent=2)+'\n');print('Imported',len(items),'original assets.')
