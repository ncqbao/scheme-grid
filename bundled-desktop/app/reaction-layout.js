/* Reaction-aware Scheme Grid layout. Existing chemical fragments are translated only. */
(function (root) {
  'use strict';
  var VERSION = '0.2.1';
  var COORDS = {p:2,xyz:3,BoundingBox:2,Head3D:3,Tail3D:3,Center3D:3,MajorAxisEnd3D:3,MinorAxisEnd3D:3,TopLeft:2,TopRight:2,BottomLeft:2,BottomRight:2,CurvePoints:2,CurvePoints3D:3};
  function fail(s) { throw new Error(s); }
  function tag(e) { return e.localName || e.nodeName; }
  function kids(e) { var a=[],n=e.firstChild; for(;n;n=n.nextSibling){if(n.nodeType===1){a.push(n);}} return a; }
  function walk(e,f) { f(e); var a=kids(e),i;for(i=0;i<a.length;i++){walk(a[i],f);} }
  function num(s) { if(!s){return null;} var a=String(s).replace(/^\s+|\s+$/g,'').split(/[\s,]+/),r=[],i,n;for(i=0;i<a.length;i++){n=Number(a[i]);if(!isFinite(n)){return null;}r.push(n);}return r; }
  function fmt(n) { var a=Math.round(n*1000000)/1000000;return String(a===0?0:a); }
  function box(a) { return a&&a.length>=4?[Math.min(a[0],a[2]),Math.min(a[1],a[3]),Math.max(a[0],a[2]),Math.max(a[1],a[3])]:null; }
  function join(a,b) { if(!a){return b&&b.slice(0);}if(!b){return a.slice(0);}return[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])]; }
  function center(b) { return{x:(b[0]+b[2])/2,y:(b[1]+b[3])/2}; }
  function width(b) { return b[2]-b[0]; }
  function height(b) { return b[3]-b[1]; }
  function med(a) { var b=a.slice(0).sort(function(x,y){return x-y;}),m=Math.floor(b.length/2);return b.length?(b.length%2?b[m]:(b[m-1]+b[m])/2):0; }
  function content(e) { return(e.textContent||'').replace(/\s+/g,' ').replace(/^\s+|\s+$/g,''); }
  function visible(e) { return e.getAttribute('Visible')!=='no'; }
  function bounds(e) {
    var b=box(num(e.getAttribute('BoundingBox'))),p,a,i,s,lines,m=1,j;
    if(b){return b;}
    p=num(e.getAttribute('p'));
    if(p&&p.length>=2){
      if(tag(e)==='t'){
        a=e.getElementsByTagName('s');s=a.length?Number(a[0].getAttribute('size'))||10:10;
        lines=(e.textContent||'').split(/\r?\n/);for(j=0;j<lines.length;j++){m=Math.max(m,lines[j].length);}
        var w=m*s*0.56,left=p[0],just=e.getAttribute('Justification');if(just==='Center'){left-=w/2;}else if(just==='Right'){left-=w;}
        return[left,p[1]-s,left+w,p[1]+(lines.length-1)*s*1.15+2];
      }
      b=[p[0]-3,p[1]-3,p[0]+3,p[1]+3];
    }
    if(tag(e)==='arrow') { a=ends(e);if(a){return[Math.min(a[0],a[2]),Math.min(a[1],a[3])-3,Math.max(a[0],a[2]),Math.max(a[1],a[3])+3];} }
    a=kids(e);for(i=0;i<a.length;i++){if(visible(a[i])&&tag(a[i])!=='objecttag'){b=join(b,bounds(a[i]));}}return b;
  }
  function ends(e) {var h=num(e.getAttribute('Head3D')),t=num(e.getAttribute('Tail3D')),b;if(h&&t){return[t[0],t[1],h[0],h[1]];}b=num(e.getAttribute('BoundingBox'));return b&&b.length>=4?b.slice(0,4):null;}
  function head(e) { if(tag(e)==='arrow'){return /^(Full|Half|Hollow|Angle|Equilibrium)/.test(e.getAttribute('ArrowheadHead')||'')||/^(Full|Half|Hollow|Angle|Equilibrium)/.test(e.getAttribute('ArrowheadTail')||'');}return tag(e)==='graphic'&&e.getAttribute('GraphicType')==='Line'&&!!e.getAttribute('ArrowType')&&e.getAttribute('ArrowType')!=='None'; }
  function translate(e,dx,dy) {
    if(Math.abs(dx)<0.0000001&&Math.abs(dy)<0.0000001){return;}
    walk(e,function(n){var k,v,s,start,j;for(k in COORDS){if(!Object.prototype.hasOwnProperty.call(COORDS,k)||!n.hasAttribute(k)){continue;}v=num(n.getAttribute(k));s=COORDS[k];start=0;if(v&&(k==='CurvePoints'||k==='CurvePoints3D')&&v.length%s===1){start=1;}if(!v||(v.length-start)%s){fail('Unsupported coordinates in '+(n.getAttribute('id')||tag(n)));}for(j=start;j<v.length;j+=s){v[j]+=dx;v[j+1]+=dy;}n.setAttribute(k,v.map(fmt).join(' '));}});
  }
  function numeric(e) {return /^(?:\(?\d+[a-z]?\)?)$/.test(content(e));}
  function plan(source,options) {
    options=options||{};
    if(typeof source!=='string'||source.length>15000000||/<!ENTITY/i.test(source)){fail('Use a valid CDXML drawing smaller than 15 MB, without XML entities.');}
    var doc=new DOMParser().parseFromString(source,'application/xml'),r=doc.documentElement;
    if(!r||tag(r)!=='CDXML'||doc.getElementsByTagName('parsererror').length){fail('This is not valid ChemDraw CDXML.');}
    var pages=doc.getElementsByTagName('page');if(pages.length!==1){fail('Reaction cleanup currently needs one drawing page.');}
    var page=pages[0],items=[],molecules=[],arrows=[],texts=[],decor=[],aliases={},index={},primitiveById={},maxId=0,maxZ=0,i,j,k,warnings=[],moves=[],changes=[],numbering=[],groups=[];
    var bond=Number(r.getAttribute('BondLength'))||14.4,gap=Number(options.gap)||18,captionGap=6,stackGap=3;
    walk(page,function(e){var id=e.getAttribute('id');if(id){if(index[id]){fail('Duplicate drawing ID '+id+'.');}index[id]=e;maxId=Math.max(maxId,Number(id)||0);}maxZ=Math.max(maxZ,Number(e.getAttribute('Z'))||0);});
    function add(e,type) {var b=bounds(e);if(!b){warnings.push('Unpositioned '+tag(e)+' was left unchanged.');return null;}var id=e.getAttribute('id');if(!id){fail('A visible '+tag(e)+' is missing its object ID.');}var a={id:id,el:e,type:type,b:b,c:center(b),owner:null,parts:[],captions:[],numbers:[],decor:[],aliases:[],selected:false};items.push(a);walk(e,function(n){var q=n.getAttribute('id');if(q){primitiveById[q]=a;}});if(type==='molecule'){molecules.push(a);}else if(type==='arrow'){var ep=ends(e);if(!ep||Math.abs(ep[3]-ep[1])>Math.max(4,Math.abs(ep[2]-ep[0])*0.12)||Number(e.getAttribute('AngularSize')||0)!==0){fail('Reaction cleanup needs straight horizontal arrows; curved and diagonal pathways are not changed.');}a.end=ep;a.c={x:(ep[0]+ep[2])/2,y:(ep[1]+ep[3])/2};arrows.push(a);}else if(type==='text'){texts.push(a);}else{decor.push(a);}return a;}
    function scan(e) {
      var n=tag(e),a,z;
      if(!visible(e)||n==='scheme'||n==='step'||n==='objecttag'||n==='annotation'||n==='represent'){return;}
      if(n==='group'){a=kids(e);for(z=0;z<a.length;z++){scan(a[z]);}return;}
      if(n==='fragment'){add(e,'molecule');return;}
      if(e.getAttribute('SupersededBy')){aliases[e.getAttribute('id')]=e.getAttribute('SupersededBy');return;}
      if(head(e)){add(e,'arrow');return;}
      if(n==='t'){add(e,'text');return;}
      if(n==='graphic'||n==='arrow'||n==='curve'){add(e,'decoration');return;}
      if(n==='border'){return;}
      fail('Reaction cleanup does not yet support '+n+' objects.');
    }
    var ch=kids(page);for(i=0;i<ch.length;i++){scan(ch[i]);}
    function resolve(id){var n=id,seen={};while(aliases[n]&&!seen[n]){seen[n]=true;n=aliases[n];}return primitiveById[n]||null;}
    function own(a){var seen={};while(a.owner){if(seen[a.id]){fail('Conflicting object associations.');}seen[a.id]=true;a=a.owner;}return a;}
    function attach(a,b,why){if(!a||!b){return;}a=own(a);b=own(b);if(a===b){return;}if(a.type==='arrow'){fail('A reaction arrow cannot be attached to another object.');}a.owner=b;a.evidence=why;}
    for(var aid in aliases){if(Object.prototype.hasOwnProperty.call(aliases,aid)){var real=resolve(aid);if(real&&index[aid]){real.aliases.push(index[aid]);primitiveById[aid]=real;}else{fail('An arrow fallback points to a missing drawing object.');}}}
    // Separate fragments used to draw one crossing-bond assembly must travel together.
    for(i=0;i<molecules.length;i++){(function(a){walk(a.el,function(n){var ids=(n.getAttribute('CrossingBonds')||'').split(/\s+/),z,b,aa,bb;for(z=0;z<ids.length;z++){b=resolve(ids[z]);if(!b||b.type!=='molecule'){continue;}aa=own(a);bb=own(b);if(aa===bb){continue;}attach(width(aa.b)*height(aa.b)<width(bb.b)*height(bb.b)?aa:bb,width(aa.b)*height(aa.b)<width(bb.b)*height(bb.b)?bb:aa,'native crossing-bond assembly');}});}(molecules[i]));}
    function nearestArrow(b,fragment) {
      var c=center(b),best=null,score=Infinity,a,xmin,xmax,dy,s,z;
      for(z=0;z<arrows.length;z++){
        a=arrows[z];xmin=Math.min(a.end[0],a.end[2]);xmax=Math.max(a.end[0],a.end[2]);dy=Math.abs(c.y-a.c.y);
        if(c.x<xmin-8||c.x>xmax+8||dy>Math.max(100,bond*7)){continue;}
        if(fragment&&!(b[3]<=a.c.y+1||b[1]>=a.c.y-1)){continue;}
        s=Math.abs(c.x-a.c.x)*0.3+dy;
        if(s<score){score=s;best=a;}
      }
      return best;
    }
    var roleHints={},reagentHints={},roleSteps=doc.getElementsByTagName('step');
    for(i=0;i<roleSteps.length;i++){
      var roleNames=['ReactionStepReactants','ReactionStepProducts'],roleRefs,z;
      for(j=0;j<roleNames.length;j++){
        roleRefs=(roleSteps[i].getAttribute(roleNames[j])||'').split(/\s+/);
        for(z=0;z<roleRefs.length;z++){
          var roleElement=index[roleRefs[z]],rolePrimitive=resolve(roleRefs[z]);
          if(roleElement&&tag(roleElement)==='fragment'&&rolePrimitive&&rolePrimitive.type==='molecule'&&rolePrimitive.el===roleElement){roleHints[own(rolePrimitive).id]=true;}
        }
      }
      var roleArrowRefs=(roleSteps[i].getAttribute('ReactionStepArrows')||'').split(/\s+/),roleArrow=null;
      for(j=0;j<roleArrowRefs.length;j++){var candidateArrow=resolve(roleArrowRefs[j]);if(candidateArrow&&candidateArrow.type==='arrow'){if(roleArrow&&roleArrow!==candidateArrow){roleArrow=null;break;}roleArrow=candidateArrow;}}
      if(!roleArrow){continue;}
      var reagentNames=['ReactionStepObjectsAboveArrow','ReactionStepObjectsBelowArrow'];
      for(j=0;j<reagentNames.length;j++){
        roleRefs=(roleSteps[i].getAttribute(reagentNames[j])||'').split(/\s+/);
        for(z=0;z<roleRefs.length;z++){
          var reagentElement=index[roleRefs[z]],reagentPrimitive=resolve(roleRefs[z]);
          if(reagentElement&&tag(reagentElement)==='fragment'&&reagentPrimitive&&reagentPrimitive.type==='molecule'&&reagentPrimitive.el===reagentElement){reagentHints[own(reagentPrimitive).id]=roleArrow;}
        }
      }
    }
    for(i=0;i<molecules.length;i++){
      var m=molecules[i];if(m.owner){continue;}
      var mb=m.b.slice(0);for(j=0;j<molecules.length;j++){if(molecules[j]!==m&&own(molecules[j])===m){mb=join(mb,molecules[j].b);}}
      m.b=mb;m.c=center(mb);
      var reagentArrow=reagentHints[m.id]||(!roleHints[m.id]?nearestArrow(m.b,true):null);
      if(reagentArrow){attach(m,reagentArrow,'molecule positioned on reaction arrow');}
    }
    // Native step links are useful for captions, but mixed group reactant/product
    // references are deliberately not expanded into numbering candidates.
    var steps=doc.getElementsByTagName('step'),explicit={};
    for(i=0;i<steps.length;i++){
      var ar=(steps[i].getAttribute('ReactionStepArrows')||'').split(/\s+/),known=[];
      for(j=0;j<ar.length;j++){var arItem=resolve(ar[j]);if(arItem&&arItem.type==='arrow'&&known.indexOf(arItem)<0){known.push(arItem);}}
      if(known.length!==1){continue;}
      var names=['ReactionStepObjectsAboveArrow','ReactionStepObjectsBelowArrow'];
      for(j=0;j<names.length;j++){var refs=(steps[i].getAttribute(names[j])||'').split(/\s+/);for(k=0;k<refs.length;k++){var linked=resolve(refs[k]);if(linked&&linked.type==='text'){explicit[linked.id]=known[0];}}}
    }
    function nearestMolecule(b,number) {
      var c=center(b),best=null,bestS=Infinity,a,dx,dy,s,z;
      for(z=0;z<molecules.length;z++){
        a=molecules[z];if(a.owner){continue;}dx=Math.abs(c.x-a.c.x);dy=Math.max(a.b[1]-b[3],b[1]-a.b[3],0);
        if(dx>Math.max(55,width(a.b)/2+20)||dy>Math.max(85,bond*6)){continue;}
        if(number&&b[3]<a.c.y){continue;}
        s=dx*0.9+dy;if(s<bestS){bestS=s;best=a;}
      }
      return best;
    }
    for(i=0;i<texts.length;i++){
      var t=texts[i],a=explicit[t.id]||nearestArrow(t.b,false);
      if(numeric(t.el)){var nm=nearestMolecule(t.b,true);if(nm){t.owner=nm;t.number=true;nm.numbers.push(t);continue;}}
      if(a){t.owner=a;t.evidence=explicit[t.id]?'native arrow-caption reference':'caption positioned on reaction arrow';}
      else {var pm=nearestMolecule(t.b,false);if(pm){t.owner=pm;t.evidence='nearby molecule caption';}else{warnings.push('Caption “'+content(t.el).slice(0,45)+'” was left in place.');}}
    }
    // Associate frames and small symbols with the single enclosed/overlapping molecule.
    for(i=0;i<decor.length;i++){
      var d=decor[i];
      if(tag(d.el)==='arrow'&&!head(d.el)){continue;}
      var possible=[];
      for(j=0;j<molecules.length;j++){
        m=molecules[j];if(m.owner){continue;}
        if(m.c.x>=d.b[0]-3&&m.c.x<=d.b[2]+3&&m.c.y>=d.b[1]-3&&m.c.y<=d.b[3]+3){possible.push(m);}
      }
      if(possible.length===1&&width(d.b)<width(possible[0].b)*2.5+30&&height(d.b)<height(possible[0].b)*2.5+30){d.owner=possible[0];d.evidence='molecule frame';}
    }
    var principals=molecules.filter(function(a){return !a.owner;}),units=principals.concat(arrows);
    if(!principals.length){fail('No principal reactants or products were found outside the arrows.');}
    for(i=0;i<items.length;i++){
      if(items[i].owner){var o=own(items[i]);if(o.type==='arrow'){o.parts.push(items[i]);}else if(items[i].number){/* Number captions have their own common row baseline. */}else{o.parts.push(items[i]);}}
    }
    var selectedIds=options.selectedIds||[],requested={},hasSelection=selectedIds.length>0;
    for(i=0;i<selectedIds.length;i++){
      var si=String(selectedIds[i]);requested[si]=true;
      var pe=resolve(si);if(pe){own(pe).selected=true;}
      if(index[si]&&tag(index[si])==='group'){walk(index[si],function(n){var found=resolve(n.getAttribute('id'));if(found){own(found).selected=true;}});}
    }
    if(!hasSelection){for(i=0;i<units.length;i++){units[i].selected=true;}}
    var selectedCount=units.filter(function(a){return a.selected;}).length,globalLayout=!hasSelection||selectedCount===units.length;
    // Rows come from arrow baselines and are not merged transitively across a wrap.
    var rows=[],orderedArrows=arrows.slice(0).sort(function(a,b){return a.c.y-b.c.y||a.c.x-b.c.x;}),rowTolerance=Math.max(18,bond*1.5);
    for(i=0;i<orderedArrows.length;i++){
      a=orderedArrows[i];var rr=null,delta=Infinity;
      for(j=0;j<rows.length;j++){var dd=Math.abs(a.c.y-rows[j].y);if(dd<rowTolerance&&dd<delta){rr=rows[j];delta=dd;}}
      if(!rr){rr={y:a.c.y,arrows:[],molecules:[],members:[]};rows.push(rr);}rr.arrows.push(a);a.row=rr;rr.y=med(rr.arrows.map(function(x){return x.c.y;}));
    }
    for(i=0;i<principals.length;i++){
      m=principals[i];var near=null,dist=Infinity;
      for(j=0;j<rows.length;j++){var md=Math.abs(m.c.y-rows[j].y);if(md<dist){dist=md;near=rows[j];}}
      if(!near||dist>Math.max(70,height(m.b))){near={y:m.c.y,arrows:[],molecules:[],members:[]};rows.push(near);}near.molecules.push(m);m.row=near;
    }
    rows.sort(function(x,y){return x.y-y.y;});
    for(i=0;i<decor.length;i++){
      d=decor[i];if(d.owner||width(d.b)<bond*5||height(d.b)>bond){continue;}
      for(j=0;j<rows.length-1;j++){if(d.c.y>rows[j].y&&d.c.y<rows[j+1].y){d.bandAfter=j;break;}}
    }
    var used={},next=Number(options.startNumber)||1;
    for(i=0;i<texts.length;i++){if(numeric(texts[i].el)){var nv=parseInt(content(texts[i].el),10);if(isFinite(nv)){used[nv]=true;}}}
    var font=r.getAttribute('CaptionFont')||'3',size=Number(r.getAttribute('CaptionSize'))||10;
    var readOrder=principals.slice(0).sort(function(x,y){return rows.indexOf(x.row)-rows.indexOf(y.row)||x.c.x-y.c.x;});
    for(i=0;i<readOrder.length;i++){
      m=readOrder[i];if(m.numbers.length){for(j=0;j<m.numbers.length;j++){numbering.push({moleculeId:m.id,captionId:m.numbers[j].id,number:content(m.numbers[j].el),added:false});}continue;}
      if(options.numbering===false||!m.selected){continue;}
      while(used[next]){next++;}used[next]=true;
      var nt=doc.createElement('t'),ns=doc.createElement('s'),id=String(++maxId),nb=[m.c.x-String(next).length*size*0.3,m.b[3]+12,m.c.x+String(next).length*size*0.3,m.b[3]+12+size];
      nt.setAttribute('id',id);nt.setAttribute('p',fmt(m.c.x)+' '+fmt(nb[3]-2));nt.setAttribute('BoundingBox',nb.map(fmt).join(' '));nt.setAttribute('Z',String(++maxZ));nt.setAttribute('CaptionJustification','Center');nt.setAttribute('Justification','Center');nt.setAttribute('LineHeight','auto');ns.setAttribute('font',font);ns.setAttribute('size',String(size));ns.setAttribute('face','1');ns.appendChild(doc.createTextNode(String(next)));nt.appendChild(ns);page.appendChild(nt);
      var numberItem={id:id,el:nt,type:'text',b:nb,c:center(nb),owner:m,number:true,added:true,parts:[],aliases:[]};m.numbers.push(numberItem);texts.push(numberItem);items.push(numberItem);primitiveById[id]=numberItem;numbering.push({moleculeId:m.id,captionId:id,number:String(next),added:true});next++;
    }
    function unitBounds(u) {var b=u.b.slice(0),z;for(z=0;z<u.parts.length;z++){b=join(b,u.parts[z].b);}return b;}
    var common=Number(options.arrowLength)||Math.max(5*bond,72);
    for(i=0;i<arrows.length;i++) {for(j=0;j<arrows[i].parts.length;j++){common=Math.max(common,width(arrows[i].parts[j].b)+captionGap*2);}}
    common=Math.ceil(common);
    // Unit local footprints after standardizing arrows and centering their contents.
    for(i=0;i<units.length;i++){
      var u=units[i];u.original=u.c;u.local=[];
      if(u.type==='arrow'){
        var above=[],below=[],cross=[],z;
        for(j=0;j<u.parts.length;j++){
          var part=u.parts[j],raw=part.el.textContent||'';
          if(part.type==='text'&&part.b[1]<u.c.y&&part.b[3]>u.c.y&&/\r?\n\s*\r?\n/.test(raw)){cross.push(part);}
          else if(part.b[3]<=u.c.y+1||part.c.y<u.c.y){above.push(part);}else{below.push(part);}
        }
        above.sort(function(x,y){return x.b[1]-y.b[1];});below.sort(function(x,y){return x.b[1]-y.b[1];});
        var top=-captionGap,bottom=captionGap;
        for(j=0;j<cross.length;j++){part=cross[j];u.local.push({part:part,x:0,y:part.c.y-u.c.y});top=Math.min(top,part.b[1]-u.c.y-captionGap);bottom=Math.max(bottom,part.b[3]-u.c.y+captionGap);}
        for(j=above.length-1;j>=0;j--){part=above[j];u.local.push({part:part,x:0,y:top-height(part.b)/2});top-=height(part.b)+stackGap;}
        for(j=0;j<below.length;j++){part=below[j];u.local.push({part:part,x:0,y:bottom+height(part.b)/2});bottom+=height(part.b)+stackGap;}
        // Measure actual packed content, excluding the cursor's trailing gap.
        // This keeps the global origin stable on repeated runs.
        u.left=common/2;u.right=common/2;u.above=5;u.below=5;
        for(j=0;j<u.local.length;j++){var fp=u.local[j];u.above=Math.max(u.above,height(fp.part.b)/2-fp.y);u.below=Math.max(u.below,fp.y+height(fp.part.b)/2);}
      }else{
        var ub=unitBounds(u);u.left=u.c.x-ub[0];u.right=ub[2]-u.c.x;u.above=u.c.y-ub[1];u.below=ub[3]-u.c.y;
      }
    }
    var leading=false;
    for(i=0;i<rows.length;i++){
      rr=rows[i];rr.members=rr.molecules.concat(rr.arrows).sort(function(x,y){return x.c.x-y.c.x;});
      if(rr.members.length&&rr.members[0].type==='arrow'){leading=true;}
    }
    var columns=[],allBox=null;
    for(i=0;i<rows.length;i++){
      rr=rows[i];var mi=-1;rr.above=0;rr.below=0;rr.numberBelow=0;
      for(j=0;j<rr.members.length;j++){
        // Put each arrow between consecutive molecule columns, including leading-arrow rows.
        u=rr.members[j];if(u.type==='molecule'){mi++;u.column=mi*2+(leading?1:0);}else{u.column=mi*2+(leading?2:1);}
        if(u.column<0){u.column=0;}
        if(!columns[u.column]){columns[u.column]={left:0,right:0};}columns[u.column].left=Math.max(columns[u.column].left,u.left);columns[u.column].right=Math.max(columns[u.column].right,u.right);
        rr.above=Math.max(rr.above,u.above);rr.below=Math.max(rr.below,u.below);if(u.type==='molecule'){rr.numberBelow=Math.max(rr.numberBelow,u.below);}allBox=join(allBox,unitBounds(u));
      }
      if(rr.molecules.some(function(x){return x.numbers.length>0;})){rr.numberBelow+=size+12;rr.below=Math.max(rr.below,rr.numberBelow+3);}
    }
    var columnX=[],rowY=[];
    for(i=0;i<columns.length;i++){if(!columns[i]){columns[i]={left:0,right:0};}columnX[i]=i?columnX[i-1]+columns[i-1].right+gap+columns[i].left:Math.max(24,allBox[0])+columns[i].left;}
    for(i=0;i<rows.length;i++){
      rr=rows[i];var unaffected=rr.molecules.filter(function(x){return !x.selected;});
      var baseline=unaffected.length?med(unaffected.map(function(x){return x.c.y;})):med(rr.molecules.map(function(x){return x.c.y;}));
      if(!baseline){baseline=rr.y;}
      rowY[i]=globalLayout?(i?rowY[i-1]+rows[i-1].below+gap*2+rr.above:Math.max(24,allBox[1])+rr.above):baseline;rr.targetY=rowY[i];
    }
    var affected=[];
    function record(part,dx,dy,owner,evidence){translate(part.el,dx,dy);for(var ai=0;ai<(part.aliases||[]).length;ai++){translate(part.aliases[ai],dx,dy);affected.push(part.aliases[ai].getAttribute('id'));}part.b=[part.b[0]+dx,part.b[1]+dy,part.b[2]+dx,part.b[3]+dy];part.c={x:part.c.x+dx,y:part.c.y+dy};affected.push(part.id);moves.push({id:part.id,ownerId:owner.id,dx:dx,dy:dy,evidence:evidence||part.evidence||'reaction component'});}
    function centerCaption(part,cx,cy,owner) {
      var dx=cx-part.c.x,dy=cy-part.c.y,old=part.b.slice(0),p=num(part.el.getAttribute('p'));
      translate(part.el,dx,dy);part.el.setAttribute('CaptionJustification','Center');part.el.setAttribute('Justification','Center');
      var np=num(part.el.getAttribute('p'))||[cx,cy];np[0]=cx;part.el.setAttribute('p',np.map(fmt).join(' '));
      part.el.setAttribute('BoundingBox',[cx-width(old)/2,cy-height(old)/2,cx+width(old)/2,cy+height(old)/2].map(fmt).join(' '));
      part.b=[cx-width(old)/2,cy-height(old)/2,cx+width(old)/2,cy+height(old)/2];part.c={x:cx,y:cy};affected.push(part.id);moves.push({id:part.id,ownerId:owner.id,dx:dx,dy:dy,evidence:part.number?'molecule number':'centered arrow condition'});
      changes.push({id:part.id,type:'caption-centered',ownerId:owner.id});
    }
    function resizeArrow(a,cx,cy,length) {
      var ep=a.end,sign=ep[2]>=ep[0]?1:-1,dx=cx-a.c.x,dy=cy-a.c.y;
      translate(a.el,dx,dy);
      var h=num(a.el.getAttribute('Head3D')),t=num(a.el.getAttribute('Tail3D'));
      if(h&&t){h[0]=cx+sign*length/2;h[1]=cy;t[0]=cx-sign*length/2;t[1]=cy;a.el.setAttribute('Head3D',h.map(fmt).join(' '));a.el.setAttribute('Tail3D',t.map(fmt).join(' '));}
      var raw=num(a.el.getAttribute('BoundingBox'));
      if(raw){var top=raw[1]-cy,bot=raw[3]-cy;if(tag(a.el)==='graphic'){raw=[cx+sign*length/2,cy,cx-sign*length/2,cy];}else{raw=[cx-length/2,cy+top,cx+length/2,cy+bot];}a.el.setAttribute('BoundingBox',raw.map(fmt).join(' '));}
      // Curvature control geometry for a straight arrow is translated; its two
      // shaft endpoints and legacy fallback determine its displayed length.
      for(var z=0;z<a.aliases.length;z++){
        var alias=a.aliases[z];translate(alias,dx,dy);var ab=num(alias.getAttribute('BoundingBox'));
        if(ab){alias.setAttribute('BoundingBox',[cx+sign*length/2,cy,cx-sign*length/2,cy].map(fmt).join(' '));}
        affected.push(alias.getAttribute('id'));
      }
      affected.push(a.id);moves.push({id:a.id,ownerId:a.id,dx:dx,dy:dy,evidence:'standard reaction arrow'});changes.push({id:a.id,type:'arrow-normalized',length:length});
      a.c={x:cx,y:cy};a.b=[cx-length/2,cy-5,cx+length/2,cy+5];a.targetLength=length;
    }
    for(i=0;i<rows.length;i++){
      rr=rows[i];
      for(j=0;j<rr.members.length;j++){
        u=rr.members[j];if(!u.selected){continue;}
        var tx=globalLayout?columnX[u.column]:u.c.x,ty=rr.targetY,dx=tx-u.c.x,dy=ty-u.c.y;
        if(u.type==='arrow'){
          var len=common;
          if(!globalLayout){
            var leftLimit=-Infinity,rightLimit=Infinity;
            for(k=0;k<rr.molecules.length;k++){m=rr.molecules[k];if(m.selected){continue;}if(m.c.x<tx){leftLimit=Math.max(leftLimit,m.b[2]+8);}else{rightLimit=Math.min(rightLimit,m.b[0]-8);}}
            var allowed=2*Math.min(tx-leftLimit,rightLimit-tx);
            if(isFinite(allowed)&&allowed<len){
              var required=12;for(var pi=0;pi<u.parts.length;pi++){required=Math.max(required,width(u.parts[pi].b)+captionGap*2);}
              if(allowed<required){fail('Selected arrow '+u.id+' needs more space for its conditions. Include its adjacent structures in the selection, or run the whole scheme.');}
              len=allowed;warnings.push('Selected arrow '+u.id+' was limited by nearby unselected structures.');
            }
          }
          resizeArrow(u,tx,ty,len);
          for(k=0;k<u.local.length;k++){var loc=u.local[k];if(loc.part.type==='text'){centerCaption(loc.part,tx,ty+loc.y,u);}else{record(loc.part,tx-loc.part.c.x,ty+loc.y-loc.part.c.y,u,'centered on-arrow reagent');}}
        }else{
          record(u,dx,dy,u);for(k=0;k<u.parts.length;k++){record(u.parts[k],dx,dy,u);}
          for(k=0;k<u.numbers.length;k++){
            var number=u.numbers[k],ny=ty+rr.numberBelow-height(number.b)/2;
            centerCaption(number,tx,ny,u);
          }
        }
        groups.push({id:u.id,type:u.type,elementIds:[u.id].concat(u.parts.map(function(x){return x.id;})),annotationIds:u.parts.map(function(x){return x.id;}),anchor:u.original,target:{x:tx,y:ty},row:i,column:u.column});
      }
    }
    // Long separator lines belong in the gap between reaction rows. Their
    // style and horizontal extent are preserved; a selected-only operation
    // leaves an unselected separator untouched.
    if(globalLayout){
      for(i=0;i<decor.length;i++){
        d=decor[i];if(typeof d.bandAfter!=='number'){continue;}
        var upper=rows[d.bandAfter],lower=rows[d.bandAfter+1];
        var bandY=(upper.targetY+upper.below+lower.targetY-lower.above)/2;
        var bandDY=bandY-d.c.y;record(d,0,bandDY,d,'separator in inter-row gap');changes.push({id:d.id,type:'decoration-moved'});
      }
    }
    // Only bounding boxes of containers enclosing changed children are refreshed.
    var groupEls=page.getElementsByTagName('group');
    for(i=groupEls.length-1;i>=0;i--){var gb=null,gc=kids(groupEls[i]),touch=false;walk(groupEls[i],function(e){if(affected.indexOf(e.getAttribute('id'))>=0){touch=true;}});if(!touch){continue;}for(j=0;j<gc.length;j++){if(visible(gc[j])&&tag(gc[j])!=='scheme'){gb=join(gb,bounds(gc[j]));}}if(gb&&groupEls[i].hasAttribute('BoundingBox')){groupEls[i].setAttribute('BoundingBox',gb.map(fmt).join(' '));}}
    var whole=null;ch=kids(page);for(i=0;i<ch.length;i++){if(visible(ch[i])&&tag(ch[i])!=='scheme'&&tag(ch[i])!=='annotation'){whole=join(whole,bounds(ch[i]));}}
    if(whole&&r.hasAttribute('BoundingBox')){r.setAttribute('BoundingBox',whole.map(fmt).join(' '));}
    // Whole-drawing cleanup can widen or lengthen the layout. Add complete
    // sheets so ChemDraw exports every structure without changing sheet size.
    // Any explicit selection keeps the original page format.
    if(whole&&!hasSelection){
      var pb=box(num(page.getAttribute('BoundingBox'))),wp=Number(page.getAttribute('WidthPages')||1),hp=Number(page.getAttribute('HeightPages')||1);
      if(pb&&width(pb)>0&&height(pb)>0&&wp>=1&&hp>=1&&wp%1===0&&hp%1===0){
        var sw=width(pb)/wp,sh=height(pb)/hp,nwp=Math.max(wp,Math.ceil((whole[2]-pb[0])/sw-0.000000001)),nhp=Math.max(hp,Math.ceil((whole[3]-pb[1])/sh-0.000000001));
        if(nwp>1000||nhp>1000){fail('The arranged drawing needs more than 1000 sheets in one direction. Use a smaller drawing.');}
        if(nwp>wp||nhp>hp){
          if(nwp>wp){pb[2]=pb[0]+sw*nwp;page.setAttribute('WidthPages',String(nwp));}
          if(nhp>hp){pb[3]=pb[1]+sh*nhp;page.setAttribute('HeightPages',String(nhp));}
          page.setAttribute('BoundingBox',pb.map(fmt).join(' '));changes.push({type:'page-expanded',widthPages:nwp,heightPages:nhp});
        }
      }
    }
    return{cdxml:new XMLSerializer().serializeToString(doc),groups:groups,moves:moves,warnings:warnings,numbering:numbering,changes:changes,scope:{selected:hasSelection,affectedIds:affected},stats:{molecules:principals.length,reagents:molecules.length-principals.length,arrows:arrows.length,rows:rows.length,numbered:numbering.filter(function(x){return x.added;}).length,arrowLength:common,version:VERSION}};
  }
  root.ReactionLayout={version:VERSION,plan:plan};
}(typeof window!=='undefined'?window:this));
