export async function draw(g,t,{D,M,W,H,Q,allCopy}){D.background(g,t,W,H);await M.backdrop(g,t,W,H,Q?.22:.18);D.mast(g,W,'A HERMES PLUGIN');
 D.headline(g,'photo-to-part,',64,Q?228:254,Q?155:190,D.P.white,Q?952:1260);D.headline(g,'a Hermes plugin',64,Q?325:364,Q?87:98,D.P.accent,Q?952:1200,.12);
 const x=64,y=Q?426:470,w=Q?952:1060,h=Q?560:430,entry=1-D.ease(t/.7);D.box(g,x,y+entry*28,w,h,D.P.panel,22);D.mono(g,'PROMPT EXAMPLE',x+32,y+50+entry*28,22,D.P.muted);await M.picture(g,'gear',x+32,y+85+entry*28,Q?245:255,Q?245:255,{fill:'#FFFFFF',round:12});
 D.wrap(g,allCopy.prompt,Q?x+316:x+325,y+160+entry*28,Q?590:680,Q?51:57,D.P.white,{maxLines:4});
 if(!Q){await M.picture(g,'banner',1250,394,570,600,{crop:[659,40,493,520],fill:'#FFFFFF',round:10,push:1.01});D.brackets(g,1250,394,570,600,t+.3,D.P.steel)}
}
