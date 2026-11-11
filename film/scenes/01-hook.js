export async function draw(g,t,{D,M,W,H,Q,intensity}){D.background(g,t,W,H);D.mast(g,W,'PHOTO → PART');
 if(Q){D.headline(g,'Snap a photo.',64,210,144,D.P.white,952);D.headline(g,'Get a printable part.',64,326,107,D.P.accent,952,.15);await M.picture(g,'gear',240,420,600,560,{push:1.02+t*.012*intensity,fill:'#FFFFFF'});D.brackets(g,240,420,600,560,t);}
 else{D.headline(g,'Snap a photo.',64,365,178,D.P.white,890);D.headline(g,'Get a printable',64,545,150,D.P.white,890,.15);D.headline(g,'part.',64,740,220,D.P.accent,800,.3);await M.picture(g,'gear',1050,200,760,710,{push:1.02+t*.012*intensity,fill:'#FFFFFF'});D.brackets(g,1050,200,760,710,t);}
}
