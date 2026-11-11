export async function draw(g,t,{D,M,W,H,Q,copy}){D.background(g,t,W,H);await M.backdrop(g,0,W,H,.12);D.mast(g,W,'HERMES AGENT');g.__time=2;
 D.headline(g,copy[0],64,Q?375:433,Q?105:174,D.P.white,W-128);D.line(g,64,Q?438:503,W-64,Q?438:503,D.P.accent,5);
 D.text(g,copy[1],64,Q?585:670,Q?36:59,D.P.accent,'Sans',650);D.text(g,copy[2],64,Q?758:849,Q?37:51,D.P.white,'Sans',600);
}
