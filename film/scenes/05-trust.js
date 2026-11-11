export async function draw(g,t,{D,M,W,H,Q,copy}){D.background(g,t,W,H);D.mast(g,W,'PART STUDIO / TRUST');const k=Math.min(3,Math.floor(t/2.5)),u=t-k*2.5;g.__time=u;
 const lines=[['A validated STL','every time'],['Your measurements','stay locked'],['Weak photo matches','flagged untrusted'],['Live progress in the','Part studio pane']][k];
 D.headline(g,lines[0],64,Q?185:200,Q?96:116,D.P.white,W-128);D.headline(g,lines[1],64,Q?295:330,Q?106:136,k===2?D.P.accent:D.P.steel,W-128,.09);
 if(k===0){if(Q){await M.picture(g,'views',300,365,480,640,{push:1+u*.005,fill:'#FFFFFF'});D.brackets(g,300,365,480,640,u,D.P.steel)}else{const crops=[[0,0,726,794],[726,0,726,794],[0,794,726,794],[726,794,726,794]];for(let i=0;i<4;i++)await M.picture(g,'views',64+i*450,432,420,560,{crop:crops[i],fill:'#FFFFFF',round:4,push:1+u*.003})}}
 if(k===1){await M.picture(g,'hingePane',Q?95:320,Q?450:495,Q?890:1280,360,{crop:[0,360,720,120],fill:'#141311',round:10});D.brackets(g,Q?95:320,Q?450:495,Q?890:1280,360,u);}
 if(k===2){await M.picture(g,'weakPane',Q?95:320,Q?450:495,Q?890:1280,360,{crop:[0,360,720,150],fill:'#141311',round:10});D.brackets(g,Q?95:320,Q?450:495,Q?890:1280,360,u);}
 if(k===3){await M.picture(g,'gearPane',64,Q?440:460,W-128,Q?400:440,{crop:[0,0,720,116],fill:'#141311',round:10});D.brackets(g,64,Q?440:460,W-128,Q?400:440,u,D.P.steel)}
}
