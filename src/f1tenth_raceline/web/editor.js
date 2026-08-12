(() => {
  const $ = id => document.getElementById(id);
  const base = $('base'), overlay = $('overlay');
  const bctx = base.getContext('2d', { alpha: false });
  const octx = overlay.getContext('2d');
  const stage = $('stage');
  let mode = 'map';
  let tool = 'free';
  let operations = [], redoStack = [], currentStroke = null;
  let centerline = [], showCenterline = true;
  let sectorData = null;
  let img = new Image();
  let previewTimer = null, validateTimer = null;
  let regenerating = false;
  const palette = ['#70a7ff','#d9a45f','#8bd17c','#cf83e8','#5fc8c8','#e98181','#c7c75e','#8f9ed9'];

  function mapProfile() { return { version: 1, operations }; }
  function currentSectorKey() { return mode === 'speed' ? 'speed' : 'overtaking'; }
  function setStatus(el, text, error=false) { el.textContent = text; el.style.color = error ? '#ff8d97' : '#aab4c0'; }
  function setRegenerating(value) {
    regenerating = value;
    $('regenerateBtn').disabled = value;
    $('saveBtn').disabled = value;
    $('previewBtn').disabled = value;
    $('speedModeBtn').disabled = value || !sectorData?.available;
    $('otModeBtn').disabled = value || !sectorData?.available || !sectorData?.shortest_available;
  }
  function setMode(next) {
    if (regenerating) return;
    if (next !== 'map' && !sectorData?.available) return;
    if (next === 'ot' && !sectorData?.shortest_available) return;
    mode = next;
    $('mapPanel').classList.toggle('hidden', mode !== 'map');
    $('sectorPanel').classList.toggle('hidden', mode === 'map');
    $('speedGlobals').classList.toggle('hidden', mode !== 'speed');
    $('otGlobals').classList.toggle('hidden', mode !== 'ot');
    $('mapModeBtn').classList.toggle('active', mode === 'map');
    $('speedModeBtn').classList.toggle('active', mode === 'speed');
    $('otModeBtn').classList.toggle('active', mode === 'ot');
    overlay.style.cursor = mode === 'map' ? 'crosshair' : 'cell';
    redoStack = [];
    if (mode !== 'map') renderSectorControls();
    redraw(); updateButtons();
  }
  function updateButtons() {
    $('undoBtn').disabled = mode !== 'map' || operations.length === 0 || regenerating;
    $('redoBtn').disabled = mode !== 'map' || redoStack.length === 0 || regenerating;
    $('freeBtn').classList.toggle('active', tool === 'free');
    $('occupiedBtn').classList.toggle('active', tool === 'occupied');
  }
  function drawStroke(ctx, op, alpha=0.52) {
    if (!op.points?.length) return;
    const color = op.tool === 'free' ? `rgba(74,163,255,${alpha})` : `rgba(255,91,105,${alpha})`;
    ctx.save(); ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=op.radius*2; ctx.lineCap='round'; ctx.lineJoin='round';
    ctx.beginPath(); ctx.moveTo(op.points[0][0], op.points[0][1]); for (const p of op.points.slice(1)) ctx.lineTo(p[0], p[1]); ctx.stroke();
    for (const p of [op.points[0], op.points[op.points.length-1]]) { ctx.beginPath(); ctx.arc(p[0],p[1],op.radius,0,Math.PI*2); ctx.fill(); }
    ctx.restore();
  }
  function sectorIndexAtS(s, splits) { let i=0; while (i < splits.length && s > splits[i]) i++; return i; }
  function drawPolyline(points, color, width=1.5, dashed=false) {
    if (!points || points.length < 2) return;
    octx.save(); octx.strokeStyle=color; octx.lineWidth=width; if (dashed) octx.setLineDash([7,5]);
    octx.beginPath(); octx.moveTo(points[0][1], points[0][2]); for (const p of points.slice(1)) octx.lineTo(p[1],p[2]); octx.stroke(); octx.restore();
  }
  function drawXYPolyline(points, color, width=1) {
    if (!points || points.length < 2) return;
    octx.save(); octx.strokeStyle=color; octx.lineWidth=width; octx.globalAlpha=.6;
    octx.beginPath(); octx.moveTo(points[0][0],points[0][1]); for(const p of points.slice(1)) octx.lineTo(p[0],p[1]); octx.stroke(); octx.restore();
  }
  function drawSectors() {
    if (!sectorData?.available) return;
    drawXYPolyline(sectorData.bounds?.right, '#5b6772', 1); drawXYPolyline(sectorData.bounds?.left, '#5b6772', 1);
    if (mode === 'ot' && sectorData.shortest?.length) drawPolyline(sectorData.shortest, '#ff6b6b', 1.3, true);
    const group = sectorData.profile[currentSectorKey()], splits = group.splits_s_m || [], points = sectorData.raceline || [];
    for (let i=1;i<points.length;i++) {
      const sec = sectorIndexAtS(points[i][0], splits); let color = palette[sec % palette.length], width = 3;
      if (mode === 'ot' && !group.sectors[sec]?.ot_flag) { color='#7f8994'; width=2; }
      octx.save(); octx.strokeStyle=color; octx.lineWidth=width; octx.beginPath(); octx.moveTo(points[i-1][1],points[i-1][2]); octx.lineTo(points[i][1],points[i][2]); octx.stroke(); octx.restore();
    }
    for (let i=0;i<splits.length;i++) {
      const split=splits[i]; let nearest=points[0]; for(const p of points) if(Math.abs(p[0]-split)<Math.abs(nearest[0]-split)) nearest=p;
      octx.save(); octx.fillStyle='#fff'; octx.strokeStyle='#101318'; octx.lineWidth=2; octx.beginPath(); octx.arc(nearest[1],nearest[2],5,0,Math.PI*2); octx.fill(); octx.stroke(); octx.fillStyle='#fff'; octx.font='12px system-ui'; octx.fillText(`S${i+1}`,nearest[1]+7,nearest[2]-7); octx.restore();
    }
  }
  function redraw() {
    octx.clearRect(0,0,overlay.width,overlay.height);
    if(mode==='map') {
      for(const op of operations) drawStroke(octx,op); if(currentStroke) drawStroke(octx,currentStroke,.7);
      if(showCenterline&&centerline.length>1){octx.save();octx.strokeStyle='#42e29c';octx.lineWidth=2;octx.beginPath();octx.moveTo(centerline[0][0],centerline[0][1]);for(const p of centerline.slice(1))octx.lineTo(p[0],p[1]);octx.closePath();octx.stroke();octx.restore();}
    } else drawSectors();
    updateButtons();
  }
  function canvasPoint(evt){const rect=overlay.getBoundingClientRect();return[(evt.clientX-rect.left)*overlay.width/rect.width,(evt.clientY-rect.top)*overlay.height/rect.height];}
  function schedulePreview(){clearTimeout(previewTimer);previewTimer=setTimeout(previewCenterline,350);}
  async function previewCenterline(){
    if(mode!=='map'||regenerating)return;
    setStatus($('status'),'편집된 맵 기준으로 중심선을 다시 계산하는 중...'); $('previewBtn').disabled=true;
    try {
      const res=await fetch('/api/preview-centerline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mapProfile())});
      const data=await res.json(); if(!data.ok)throw new Error(data.error||'중심선 미리보기 계산 실패');
      centerline=data.points||[]; redraw(); setStatus($('status'),`중심선 미리보기: ${centerline.length}개 점`);
    } catch(e) {
      centerline=[]; redraw(); setStatus($('status'),`미리보기 실패: ${e.message}`,true);
    } finally { $('previewBtn').disabled=regenerating; }
  }
  async function saveMap(){
    if(regenerating)return;
    setStatus($('status'),'맵 편집 내용을 저장하는 중...');
    try {
      const res=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mapProfile())});
      const data=await res.json(); if(!data.ok)throw new Error(data.error||'저장 실패');
      setStatus($('status'),`맵 편집 저장 완료: 브러시 작업 ${data.operations}개`);
    } catch(e) { setStatus($('status'),`저장 실패: ${e.message}`,true); }
  }
  async function regenerateRaceline(){
    if(regenerating)return;
    setRegenerating(true); updateButtons();
    setStatus($('status'),'편집 내용을 저장하고 레이스라인을 재생성하는 중입니다. 최적화 계산이 끝날 때까지 이 화면을 유지하세요.');
    try {
      const res=await fetch('/api/regenerate-raceline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mapProfile())});
      const data=await res.json(); if(!data.ok)throw new Error(data.error||'레이스라인 재생성 실패');
      sectorData=data.sectors;
      $('speedModeBtn').disabled=!sectorData.available;
      $('otModeBtn').disabled=!sectorData.available||!sectorData.shortest_available;
      const lap=Number(data.summary?.estimated_lap_time_iqp_s);
      const lapText=Number.isFinite(lap)?` / IQP 예상 랩타임 ${lap.toFixed(3)}초`:'';
      setStatus($('status'),`레이스라인 재생성 완료${lapText}. 속도/추월 섹터에 새 결과가 반영되었습니다.`);
      if(mode!=='map')renderSectorControls();
      redraw();
    } catch(e) {
      setStatus($('status'),`레이스라인 재생성 실패: ${e.message}`,true);
      await loadSectors();
    } finally { setRegenerating(false); updateButtons(); }
  }
  function clone(v){return JSON.parse(JSON.stringify(v));}
  function addSplit(s){const key=currentSectorKey(),group=sectorData.profile[key];if(group.splits_s_m.some(v=>Math.abs(v-s)<1e-9))return;let pos=group.splits_s_m.findIndex(v=>v>s);if(pos<0)pos=group.splits_s_m.length;group.splits_s_m.splice(pos,0,s);const src=group.sectors[Math.min(pos,group.sectors.length-1)]||(key==='speed'?{scaling:.5,only_FTG:false,no_FTG:false}:{ot_flag:false});group.sectors.splice(pos+1,0,clone(src));renderSectorControls();redraw();scheduleValidate();}
  function removeSplit(index){const group=sectorData.profile[currentSectorKey()];group.splits_s_m.splice(index,1);if(group.sectors.length>1)group.sectors.splice(index+1,1);renderSectorControls();redraw();scheduleValidate();}
  function nearestRacelinePoint(x,y){let best=null,bestD=Infinity;for(const p of sectorData.raceline){const d=(p[1]-x)**2+(p[2]-y)**2;if(d<bestD){bestD=d;best=p;}}return bestD <= 35*35 ? best : null;}
  function sectorRangeText(group,i){const start=i===0?0:group.splits_s_m[i-1],end=i<group.splits_s_m.length?group.splits_s_m[i]:sectorData.s_max;return`${start.toFixed(2)} m → ${end.toFixed(2)} m`;}
  function warningText(w){
    const names={speed_sector_short:'속도 섹터가 너무 짧아 전환 블렌딩 구간이 서로 겹칠 수 있습니다.',ftg_conflict:'같은 속도 섹터에서 only_FTG와 no_FTG를 동시에 켤 수 없습니다.',scaling_above_global_limit:'섹터 속도 배율이 전체 속도 상한보다 커서 ROS 실행 시 상한값으로 제한됩니다.',ot_sector_short:'추월 섹터가 너무 짧아 진입/이탈 보간 구간이 겹칠 수 있습니다.',raceline_stale:'맵 편집 내용이 현재 레이스라인보다 최신입니다. 레이스라인을 재생성하세요.'};
    const prefix=Number.isInteger(w.sector)?`섹터 ${w.sector}: `:'';
    return prefix+(names[w.code]||w.message||'알 수 없는 검증 경고');
  }
  function renderWarnings(warnings){const box=$('warningList');box.innerHTML='';if(!warnings?.length){box.textContent='검증 경고가 없습니다.';return;}for(const w of warnings){const d=document.createElement('div');d.className='warning'+(w.severity==='error'?' error':'');d.textContent=warningText(w);box.appendChild(d);}}
  function renderSectorControls(){
    if(!sectorData?.available)return;const key=currentSectorKey(),group=sectorData.profile[key];$('sectorTitle').textContent=mode==='speed'?'속도 섹터':'추월 섹터';
    if(mode==='speed')$('globalLimit').value=group.global_limit;else{$('yeetFactor').value=group.yeet_factor;$('splineLen').value=group.spline_len;$('otSectorBegin').value=group.ot_sector_begin;}
    const list=$('sectorList');list.innerHTML='';group.sectors.forEach((sec,i)=>{const card=document.createElement('div');card.className='sector-card';const title=document.createElement('div');title.className='title';const name=document.createElement('strong');name.textContent=(mode==='speed'?'속도 섹터 ':'추월 섹터 ')+i;name.style.color=palette[i%palette.length];title.appendChild(name);if(i>0){const del=document.createElement('button');del.textContent='분할점 제거';del.addEventListener('click',()=>removeSplit(i-1));title.appendChild(del);}card.appendChild(title);const meta=document.createElement('div');meta.className='meta';meta.textContent=sectorRangeText(group,i);card.appendChild(meta);
      if(mode==='speed'){const label=document.createElement('label');label.textContent='속도 배율';const inp=document.createElement('input');inp.type='number';inp.min='0';inp.max='1';inp.step='.01';inp.value=sec.scaling;inp.addEventListener('change',()=>{sec.scaling=Number(inp.value);scheduleValidate();redraw();});label.appendChild(inp);card.appendChild(label);const checks=document.createElement('div');checks.className='check-row';for(const field of['only_FTG','no_FTG']){const lab=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=!!sec[field];c.addEventListener('change',()=>{sec[field]=c.checked;scheduleValidate();});lab.appendChild(c);lab.append(field);checks.appendChild(lab);}card.appendChild(checks);}else{const checks=document.createElement('div');checks.className='check-row';const lab=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=!!sec.ot_flag;c.addEventListener('change',()=>{sec.ot_flag=c.checked;scheduleValidate();redraw();});lab.appendChild(c);lab.append('최단경로 기반 추월 활성화');checks.appendChild(lab);card.appendChild(checks);}list.appendChild(card);});renderWarnings(sectorData.warnings||[]);
  }
  async function validateSectors(){if(!sectorData?.available)return;try{const res=await fetch('/api/sectors/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sectorData.profile)});const data=await res.json();if(!data.ok)throw new Error(data.error||'검증 실패');sectorData.warnings=data.warnings||[];renderWarnings(sectorData.warnings);}catch(e){setStatus($('sectorStatus'),`검증 실패: ${e.message}`,true);}}
  function scheduleValidate(){clearTimeout(validateTimer);validateTimer=setTimeout(validateSectors,200);}
  async function saveSectors(){setStatus($('sectorStatus'),'섹터 설정을 저장하고 ROS YAML을 내보내는 중...');try{const res=await fetch('/api/sectors/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sectorData.profile)});const data=await res.json();if(!data.ok)throw new Error(data.error||'저장 실패');sectorData.profile=data.profile;sectorData.warnings=data.warnings||[];renderSectorControls();redraw();setStatus($('sectorStatus'),`섹터 저장 완료\n속도 YAML: ${data.speed_yaml_path}\n추월 YAML: ${data.ot_yaml_path}`);}catch(e){setStatus($('sectorStatus'),`섹터 저장 실패: ${e.message}`,true);}}
  async function loadSectors(){try{const data=await fetch('/api/sectors?t='+Date.now()).then(r=>r.json());sectorData=data;$('speedModeBtn').disabled=regenerating||!data.available;$('otModeBtn').disabled=regenerating||!data.available||!data.shortest_available;if(!data.available){setStatus($('sectorStatus'),data.message||'먼저 레이스라인을 생성하세요.');if(mode!=='map')setMode('map');return;}if(!data.shortest_available)setStatus($('sectorStatus'),'최단경로 레이스라인이 없어 추월 섹터 편집이 비활성화되었습니다.');if(mode==='ot'&&!data.shortest_available){setMode('speed');setStatus($('sectorStatus'),'raceline_shortest.csv가 없어 추월 섹터를 편집할 수 없습니다.',true);}if(mode!=='map')renderSectorControls();redraw();}catch(e){sectorData={available:false};$('speedModeBtn').disabled=true;$('otModeBtn').disabled=true;setStatus($('sectorStatus'),`섹터 데이터 불러오기 실패: ${e.message}`,true);}}

  overlay.addEventListener('pointerdown',evt=>{if(regenerating)return;if(mode!=='map'){const[x,y]=canvasPoint(evt),p=nearestRacelinePoint(x,y);if(!p){setStatus($('sectorStatus'),'최소 곡률 레이스라인에 더 가까운 위치를 클릭하세요.',true);return;}if(p[3]<=0||p[3]>=sectorData.n_points-1){setStatus($('sectorStatus'),'시작/끝 기준점이 아닌 내부 waypoint를 선택하세요.',true);return;}addSplit(p[0]);setStatus($('sectorStatus'),`분할점 추가: s=${p[0].toFixed(2)} m, waypoint ${p[3]}`);return;}overlay.setPointerCapture(evt.pointerId);currentStroke={tool,radius:Number($('radius').value),points:[canvasPoint(evt).map(Math.round)]};redoStack=[];redraw();});
  overlay.addEventListener('pointermove',evt=>{if(mode!=='map'||!currentStroke||regenerating)return;const p=canvasPoint(evt).map(Math.round),last=currentStroke.points.at(-1);if(Math.hypot(p[0]-last[0],p[1]-last[1])>=1.5)currentStroke.points.push(p);redraw();});
  function finishStroke(evt){if(mode!=='map'||!currentStroke||regenerating)return;currentStroke.points.push(canvasPoint(evt).map(Math.round));operations.push(currentStroke);currentStroke=null;centerline=[];redraw();schedulePreview();}
  overlay.addEventListener('pointerup',finishStroke);overlay.addEventListener('pointercancel',()=>{currentStroke=null;redraw();});
  $('mapModeBtn').addEventListener('click',()=>setMode('map'));$('speedModeBtn').addEventListener('click',()=>setMode('speed'));$('otModeBtn').addEventListener('click',()=>setMode('ot'));
  $('freeBtn').addEventListener('click',()=>{tool='free';updateButtons();});$('occupiedBtn').addEventListener('click',()=>{tool='occupied';updateButtons();});
  $('undoBtn').addEventListener('click',()=>{if(mode==='map'&&operations.length&&!regenerating){redoStack.push(operations.pop());centerline=[];redraw();schedulePreview();}});$('redoBtn').addEventListener('click',()=>{if(mode==='map'&&redoStack.length&&!regenerating){operations.push(redoStack.pop());centerline=[];redraw();schedulePreview();}});
  $('clearBtn').addEventListener('click',()=>{if(operations.length&&!regenerating&&confirm('모든 맵 편집 내용을 초기화할까요?')){redoStack=[];operations=[];centerline=[];redraw();schedulePreview();}});$('radius').addEventListener('input',()=>$('radiusValue').textContent=$('radius').value);
  $('zoom').addEventListener('input',()=>{$('zoomValue').textContent=$('zoom').value;const scale=Number($('zoom').value)/100;stage.style.transform=`scale(${scale})`;stage.style.marginRight=`${stage.offsetWidth*(scale-1)}px`;stage.style.marginBottom=`${stage.offsetHeight*(scale-1)}px`;});
  $('previewBtn').addEventListener('click',previewCenterline);$('toggleCenterBtn').addEventListener('click',()=>{showCenterline=!showCenterline;$('toggleCenterBtn').textContent=showCenterline?'중심선 숨기기':'중심선 보이기';redraw();});$('saveBtn').addEventListener('click',saveMap);$('regenerateBtn').addEventListener('click',regenerateRaceline);$('saveSectorsBtn').addEventListener('click',saveSectors);$('refreshSectorsBtn').addEventListener('click',loadSectors);
  $('globalLimit').addEventListener('change',()=>{sectorData.profile.speed.global_limit=Number($('globalLimit').value);scheduleValidate();});$('yeetFactor').addEventListener('change',()=>{sectorData.profile.overtaking.yeet_factor=Number($('yeetFactor').value);scheduleValidate();});$('splineLen').addEventListener('change',()=>{sectorData.profile.overtaking.spline_len=Number($('splineLen').value);scheduleValidate();});$('otSectorBegin').addEventListener('change',()=>{sectorData.profile.overtaking.ot_sector_begin=Number($('otSectorBegin').value);scheduleValidate();});
  window.addEventListener('keydown',evt=>{if((evt.ctrlKey||evt.metaKey)&&evt.key.toLowerCase()==='z'&&mode==='map'&&!regenerating){evt.preventDefault();evt.shiftKey?$('redoBtn').click():$('undoBtn').click();}});
  fetch('/api/state').then(r=>r.json()).then(state=>{operations=state.operations||[];$('generateCommand').textContent=state.generate_command;img.onload=()=>{base.width=overlay.width=state.width;base.height=overlay.height=state.height;bctx.drawImage(img,0,0,state.width,state.height);redraw();previewCenterline();loadSectors();};img.src='/map.png?t='+Date.now();}).catch(e=>setStatus($('status'),`초기화 실패: ${e.message}`,true));
})();
