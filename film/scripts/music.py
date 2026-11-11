"""PRECISION: original 120 BPM instrumental composition. CC0, no samples or VO."""
from pathlib import Path
import numpy as np,wave,json,subprocess
r=Path(__file__).resolve().parents[1];out=r/'assets/audio';out.mkdir(exist_ok=True);SR=48000;N=60*SR;rng=np.random.default_rng(12224828);mix=np.zeros((N,2),np.float32)
def clock(d):return np.arange(round(d*SR),dtype=np.float32)/SR
def add(a,start,gain,pan=0):
 s=round(start*SR);e=min(N,s+len(a));p=(pan+1)*np.pi/4
 if s>=0 and e>s:mix[s:e,0]+=a[:e-s]*gain*np.cos(p);mix[s:e,1]+=a[:e-s]*gain*np.sin(p)
def hz(n):return 440*2**((n-69)/12)
def pluck(n,d=.45):
 x=clock(d);f=hz(n);w=np.sin(2*np.pi*f*x)+.22*np.sin(4*np.pi*f*x)+.12*np.sin(6*np.pi*f*x);return w*np.minimum(1,x/.006)*np.exp(-x*7)*np.minimum(1,(d-x)/.05)
def bass(n,d=.4):
 x=clock(d);f=hz(n);return (np.sin(2*np.pi*f*x)+.2*np.sin(4*np.pi*f*x))*np.minimum(1,x/.012)*np.exp(-x*3.4)*np.minimum(1,(d-x)/.05)
def pad(n,d=1.9):
 x=clock(d);f=hz(n);return (np.sin(2*np.pi*f*x)+.3*np.sin(2*np.pi*f*1.002*x))*np.minimum(1,x/.18)*np.minimum(1,(d-x)/.35)
def kick():
 x=clock(.36);return np.sin(2*np.pi*(46*x+3.4*(1-np.exp(-x*30))))*np.exp(-x*13)*np.minimum(1,x/.002)
def clap():
 x=clock(.16);n=rng.normal(0,.25,len(x));env=sum(np.where(x>=d,np.exp(-np.maximum(0,x-d)*70),0) for d in [0,.012,.026]);return n*env*np.minimum(1,x/.001)
def hat(open=False):
 x=clock(.16 if open else .045);n=rng.normal(0,.14,len(x));return np.diff(n,prepend=0)*np.exp(-x*(26 if open else 100))*np.minimum(1,x/.001)
chords=[[42,49,57,61],[45,52,57,61],[40,47,56,59],[47,54,59,63]]
for bar in range(28):
 start=bar*2;ch=chords[(bar//2)%4];energy=.5 if start<5 else (.72 if start<12 else 1)
 if 40<=start<50:energy=.85
 for i,n in enumerate(ch[1:]):add(pad(n),start,.025*energy,(i-1)*.55)
 for j in range(8):
  n=ch[[1,2,3,2,1,3,2,3][j]]+(12 if start>=27 else 0);add(pluck(n,.38),start+j*.25,.058*energy,(-1)**j*.4)
 if start>=5:
  for beat in range(4):add(kick(),start+beat*.5,.35*energy)
  for beat in [1,3]:add(clap(),start+beat*.5,.22*energy,.1)
  for beat in range(8):add(hat(beat%2==1),start+beat*.25,.09*energy,(-1)**beat*.65)
  for beat in [0,.75,1,1.75]:add(bass(ch[0]-12),start+beat,.2*energy,-.1)
 if 27<=start<40 or start>=50:
  for j,n in enumerate([ch[2]+12,ch[3]+12,ch[2]+12,ch[1]+12]):add(pluck(n,.7),start+j*.5,.045,(-1)**j*.3)
# Deliberate hits at all editorial boundaries and trust-card cuts; no clock resets.
hits=[0,5,12,17,22,27,31,40,42.5,45,47.5,50,56]
for s in hits:
 x=clock(.14);add(rng.normal(0,.12,len(x))*np.exp(-x*40)*np.minimum(1,x/.001),s,.35);add(pluck(90,.15),s,.035,.5)
for s in [4.5,11.5,26.5,39.5,49.5,55.5]:
 x=clock(.5);add(rng.normal(0,.05,len(x))*np.linspace(0,1,len(x))*np.minimum(1,(.5-x)/.01),s,.7,.25)
add(kick(),56,.35)
for i,n in enumerate([42,49,57,61,66]):add(pad(n,3.8),56,.055,(i-2)*.3)
for j,n in enumerate([78,73,69,66]):add(pluck(n,1.3),56+j*.25,.065,(-1)**j*.3)
fade=np.minimum(1,np.arange(N)/SR/.008)*np.minimum(1,(60-np.arange(N)/SR)/1.3);mix*=fade[:,None]
with wave.open(str(out/'raw.wav'),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())
base=['ffmpeg','-hide_banner','-nostdin','-threads','2','-filter_threads','2']
def measure(p):
 q=subprocess.run(base+['-i',str(p),'-af','loudnorm=I=-14:TP=-3:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,check=True).stderr;return json.JSONDecoder().raw_decode(q[q.rfind('{'):])[0]
j=measure(out/'raw.wav');f=f"loudnorm=I=-14:TP=-3:LRA=9:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=false"
subprocess.run(base+['-y','-loglevel','error','-i',str(out/'raw.wav'),'-af',f,'-ar','48000','-c:a','pcm_s16le',str(out/'precision.wav')],check=True);(out/'raw.wav').unlink();j=measure(out/'precision.wav');gain=-14-float(j['input_i']);assert float(j['input_tp'])+gain<=-1.8
subprocess.run(base+['-y','-loglevel','error','-i',str(out/'precision.wav'),'-af',f'volume={gain}dB','-c:a','pcm_s16le',str(out/'trim.wav')],check=True);(out/'trim.wav').replace(out/'precision.wav');report={'title':'PRECISION','seed':12224828,'bpm':120,'downbeatSeconds':0,'hitsSeconds':hits,'license':'CC0-1.0','pcm':measure(out/'precision.wav')};(out/'mastering.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
