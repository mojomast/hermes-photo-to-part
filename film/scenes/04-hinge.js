export async function draw(g,t,{D,M,W,H,Q}){D.background(g,t,W,H);D.mast(g,W,'STRAP HINGE');
 if(Q){D.headline(g,'Strap hinge: 70 mm,',64,193,111,D.P.accent,952);D.headline(g,'exactly as measured',64,292,96,D.P.white,952,.12);if(t<4){await M.picture(g,'hinge',64,480,952,310,{push:1+t*.006,fill:'#E7E7E3'});D.rule(g,120,868,840,t)}else{await M.picture(g,'hingePane',230,350,620,680,{crop:[0,(t-4)/9*30,720,780],round:9});D.brackets(g,230,350,620,680,t-4)}}
 else{D.headline(g,'Strap hinge:',64,235,138,D.P.white,920);D.headline(g,'70 mm,',64,443,216,D.P.accent,920,.1);D.headline(g,'exactly as measured',64,554,98,D.P.white,920,.18);
  if(t<4){await M.picture(g,'hinge',100,650,1720,300,{push:1+t*.006,fill:'#E7E7E3'});D.rule(g,260,992,1400,t)}else{await M.picture(g,'hingePane',1050,148,770,830,{crop:[0,(t-4)/9*25,720,780],round:10});D.brackets(g,1050,148,770,830,t-4)}
 }
}
