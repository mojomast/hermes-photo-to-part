export async function draw(g,t,{D,M,W,H,Q,copy}){D.background(g,t,W,H);await M.backdrop(g,t,W,H,.08);D.mast(g,W,'BUILT TO BE CHECKED');
 if(Q){const fields=[['248','tests'],['28/28','sealed evals'],['CI','green']];fields.forEach(([n,label],i)=>{const y=275+i*250;g.__time=Math.max(0,t-i*.5);D.headline(g,n,75,y,152,i===2?D.P.green:D.P.accent,500);D.text(g,label,620,y-30,43,D.P.white);D.line(g,64,y+60,W-64,y+60,D.P.line,2)})}
 else{const fields=[['248','tests'],['28/28','sealed evals'],['CI','green']];fields.forEach(([n,label],i)=>{const x=64+i*610;g.__time=Math.max(0,t-i*.5);D.headline(g,n,x,535,230,i===2?D.P.green:D.P.accent,560);D.text(g,label,x+5,635,62,D.P.white);D.line(g,x,700,x+530,700,D.P.line,3)});D.wrap(g,copy,64,895,W-128,52,D.P.white,{maxLines:1})}
}
