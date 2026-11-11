from pathlib import Path
import json
r=Path(__file__).resolve().parents[1];c=json.loads((r/'copy.json').read_text());cues=[(0,5,c['hook']),(5,12,c['title']+'\n'+c['prompt']),(12,17,c['gear'][0]),(17,22,c['gear'][1]),(22,27,c['gear'][2]),(27,40,c['hinge']),(40,42.5,c['trust'][0]),(42.5,45,c['trust'][1]),(45,47.5,c['trust'][2]),(47.5,50,c['trust'][3]),(50,56,c['proof']),(56,60,'\n'.join(c['end']))]
def stamp(t):
 n=round(t*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'
(r/'captions').mkdir(exist_ok=True);(r/'captions/showcase.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{s}' for i,(a,b,s) in enumerate(cues))+'\n');print('Wrote 12 exact-caption SRT cues.')
