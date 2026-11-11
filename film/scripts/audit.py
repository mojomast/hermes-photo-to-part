from pathlib import Path
import json,hashlib
r=Path(__file__).resolve().parents[1];s=json.loads((r/'settings.json').read_text());p=json.loads((r/'assets/provenance.json').read_text());copy=json.loads((r/'copy.json').read_text());brief=(r/'assets/BRIEF.md').read_text()
assert (s['duration'],s['fps'],s['frames'])==(60,30,1800)
assert [(x['start'],x['end']) for x in s['scenes']]==[(0,150),(150,360),(360,810),(810,1200),(1200,1500),(1500,1680),(1680,1800)]
for value in copy.values():
 for text in value if isinstance(value,list) else [value]:assert text in brief,text
allowed={'gear-photo.jpg','hinge-photo.jpg','gear-pane-ready.png','strap-hinge-pane-ready.png','strap-hinge-pane-ready-2.png','catalog-banner.png','screenshot-views.png'}
assert {f.name for f in (r/'assets/images').iterdir()}==allowed
for a in p['assets']:assert hashlib.sha256((r/a['path']).read_bytes()).hexdigest()==a['sha256'],a['path']
print('PASS: exact scene timing, all approved captions, seven allowed images, all original asset hashes.')
