export async function draw(g,t,{D,M,W,H,Q,copy}){D.background(g,t,W,H);D.mast(g,W,'GEAR / PART STUDIO');const stage=t<5?0:t<10?1:2,local=t-stage*5;g.__time=local;
 if(Q){
  const lines=stage===0?['Spots a spur gear and uses','a parametric template']:stage===1?['Matches the photo:','IoU 0.94']:['Delivered in','under 5 minutes'];D.headline(g,lines[0],64,196,stage===0?73:96,D.P.white,952);D.headline(g,lines[1],64,300,stage===0?94:120,D.P.accent,952,.1);
  const crop=stage===1?[0,350+D.smooth(local/5)*20,720,330]:[0,D.smooth(local/5)*45,720,750];await M.picture(g,'gearPane',70,370,940,620,{crop,round:10});D.brackets(g,70,370,940,620,local,D.P.accent);
 }else{
  if(stage===0){D.headline(g,'Spots a spur gear',64,280,112,D.P.white,910);D.headline(g,'and uses a',64,418,112,D.P.white,910,.1);D.headline(g,'parametric',64,598,155,D.P.accent,910,.18);D.headline(g,'template',64,747,155,D.P.accent,910,.25)}
  if(stage===1){D.headline(g,'Matches the photo:',64,320,109,D.P.white,920);D.headline(g,'IoU 0.94',64,544,208,D.P.accent,920,.1)}
  if(stage===2){D.headline(g,'Delivered in',64,330,138,D.P.white,920);D.headline(g,'under 5',64,553,210,D.P.accent,920,.1);D.headline(g,'minutes',64,742,190,D.P.accent,920,.2)}
  const crop=stage===1?[0,110+D.smooth(local/5)*18,720,600]:[0,D.smooth(local/5)*45,720,750],y=stage===1?210:146,h=stage===1?650:830;await M.picture(g,'gearPane',1045,y,775,h,{crop,round:10});D.brackets(g,1045,y,775,h,local);
 }
}
