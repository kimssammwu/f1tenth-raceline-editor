(() => {
  const $ = id => document.getElementById(id);
  const base = $('base');
  const overlay = $('overlay');
  const stage = $('stage');
  const viewport = $('viewport');
  const mapPanel = $('mapPanel');
  if (!base || !overlay || !stage || !viewport || !mapPanel) return;

  const diagCanvas = document.createElement('canvas');
  diagCanvas.id = 'diagnosticOverlay';
  diagCanvas.style.position = 'absolute';
  diagCanvas.style.inset = '0';
  diagCanvas.style.pointerEvents = 'none';
  diagCanvas.style.zIndex = '4';
  stage.appendChild(diagCanvas);
  const ctx = diagCanvas.getContext('2d');

  const panel = document.createElement('div');
  panel.className = 'group';
  panel.innerHTML = `
    <h3>최적화 실패 위치</h3>
    <div class="row">
      <button id="diagToggleBtn" type="button">실패 위치 숨기기</button>
      <button id="diagRefreshBtn" type="button">진단 새로고침</button>
    </div>
    <label for="diagAttemptSelect" style="margin-top:9px">실패 시도</label>
    <select id="diagAttemptSelect" style="width:100%;background:#0e1116;color:#e8edf2;border:1px solid #414955;border-radius:6px;padding:6px 7px"></select>
    <div id="diagSummary" class="hint" style="margin-top:8px">실패한 최적화 진단이 있으면 맵 위에 표시됩니다.</div>
    <div id="diagDetail" class="progress hidden"></div>
  `;
  const commandGroup = $('generateCommand')?.closest('.group');
  if (commandGroup) commandGroup.before(panel); else mapPanel.appendChild(panel);

  const toggleBtn = $('diagToggleBtn');
  const refreshBtn = $('diagRefreshBtn');
  const attemptSelect = $('diagAttemptSelect');
  const summary = $('diagSummary');
  const detail = $('diagDetail');

  let payload = null;
  let visible = true;
  let selectedId = null;
  let statusTimer = null;
  let lastStatus = null;

  function syncCanvas() {
    if (diagCanvas.width !== base.width) diagCanvas.width = base.width;
    if (diagCanvas.height !== base.height) diagCanvas.height = base.height;
    diagCanvas.style.width = `${base.width}px`;
    diagCanvas.style.height = `${base.height}px`;
  }

  function selectedAttempt() {
    if (!payload?.available || !payload.attempts?.length) return null;
    return payload.attempts.find(a => a.id === selectedId) || payload.attempts[0];
  }

  function markerStyle(kind) {
    if (kind === 'curvature') return { color: '#ff5b69', shape: 'ring' };
    if (kind === 'width_jump') return { color: '#ffad4a', shape: 'diamond' };
    return { color: '#b58cff', shape: 'square' };
  }

  function drawMarker(marker) {
    const { color, shape } = markerStyle(marker.kind);
    const x = marker.x, y = marker.y;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 3;
    if (shape === 'diamond') {
      ctx.beginPath(); ctx.moveTo(x, y - 8); ctx.lineTo(x + 8, y); ctx.lineTo(x, y + 8); ctx.lineTo(x - 8, y); ctx.closePath(); ctx.stroke();
    } else if (shape === 'square') {
      ctx.strokeRect(x - 7, y - 7, 14, 14);
    } else {
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.font = '12px system-ui';
    ctx.lineWidth = 4;
    ctx.strokeStyle = 'rgba(10,12,15,.92)';
    const label = `${marker.label} #${marker.index}`;
    ctx.strokeText(label, x + 11, y - 10);
    ctx.fillStyle = color;
    ctx.fillText(label, x + 11, y - 10);
    ctx.restore();
  }

  function redrawDiagnostics() {
    syncCanvas();
    ctx.clearRect(0, 0, diagCanvas.width, diagCanvas.height);
    if (!visible) return;
    const attempt = selectedAttempt();
    if (!attempt) return;

    if (attempt.polyline?.length > 1) {
      ctx.save();
      ctx.strokeStyle = 'rgba(255,91,105,.42)';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(attempt.polyline[0][0], attempt.polyline[0][1]);
      for (const p of attempt.polyline.slice(1)) ctx.lineTo(p[0], p[1]);
      ctx.closePath();
      ctx.stroke();
      ctx.restore();
    }
    for (const marker of attempt.markers || []) drawMarker(marker);
  }

  function showDetail(marker) {
    if (!marker) { detail.classList.add('hidden'); return; }
    detail.classList.remove('hidden');
    detail.innerHTML = `<strong>${marker.label} · index ${marker.index}</strong><span>${marker.detail}</span>`;
  }

  function focusMarker(marker) {
    syncCanvas();
    if (!marker || !overlay.width) return;
    const rect = overlay.getBoundingClientRect();
    const scaleX = rect.width / overlay.width || 1;
    const scaleY = rect.height / overlay.height || scaleX;
    viewport.scrollLeft = Math.max(0, marker.x * scaleX - viewport.clientWidth / 2);
    viewport.scrollTop = Math.max(0, marker.y * scaleY - viewport.clientHeight / 2);
  }

  function renderPayload({ focus = false } = {}) {
    attemptSelect.innerHTML = '';
    if (!payload?.available || !payload.attempts?.length) {
      summary.textContent = payload?.message || '현재 생성 작업에서 시각화할 solver 실패 진단이 없습니다.';
      attemptSelect.disabled = true;
      toggleBtn.disabled = true;
      selectedId = null;
      showDetail(null);
      redrawDiagnostics();
      return;
    }
    attemptSelect.disabled = false;
    toggleBtn.disabled = false;
    for (const attempt of payload.attempts) {
      const option = document.createElement('option');
      option.value = attempt.id;
      option.textContent = attempt.label;
      attemptSelect.appendChild(option);
    }
    if (!selectedId || !payload.attempts.some(a => a.id === selectedId)) selectedId = payload.selected_attempt_id || payload.attempts[0].id;
    attemptSelect.value = selectedId;
    const attempt = selectedAttempt();
    summary.textContent = `${payload.message} 현재 표시: ${attempt.label} / ${attempt.point_count}개 reftrack 점.`;
    showDetail(attempt.markers?.[0] || null);
    redrawDiagnostics();
    if (focus && attempt.markers?.length) focusMarker(attempt.markers[0]);
  }

  async function loadDiagnostics({ focus = false } = {}) {
    try {
      const res = await fetch(`/api/optimizer-diagnostics?t=${Date.now()}`, { cache: 'no-store' });
      payload = await res.json();
      renderPayload({ focus });
    } catch (err) {
      payload = null;
      summary.textContent = `진단 조회 실패: ${err.message}`;
      redrawDiagnostics();
    }
  }

  function clearDiagnosticsView() {
    payload = null;
    selectedId = null;
    summary.textContent = '새 레이스라인 생성 중입니다. 이전 실패 위치를 지웠습니다.';
    showDetail(null);
    renderPayload();
  }

  function canvasPoint(evt) {
    const rect = overlay.getBoundingClientRect();
    return [(evt.clientX - rect.left) * overlay.width / rect.width, (evt.clientY - rect.top) * overlay.height / rect.height];
  }

  overlay.addEventListener('click', evt => {
    if (!visible) return;
    const attempt = selectedAttempt();
    if (!attempt?.markers?.length) return;
    const [x, y] = canvasPoint(evt);
    let best = null, bestD = Infinity;
    for (const marker of attempt.markers) {
      const d = Math.hypot(marker.x - x, marker.y - y);
      if (d < bestD) { bestD = d; best = marker; }
    }
    if (best && bestD <= 14) {
      evt.preventDefault();
      evt.stopImmediatePropagation();
      showDetail(best);
    }
  }, true);

  toggleBtn.addEventListener('click', () => {
    visible = !visible;
    toggleBtn.textContent = visible ? '실패 위치 숨기기' : '실패 위치 표시';
    redrawDiagnostics();
  });
  refreshBtn.addEventListener('click', () => loadDiagnostics({ focus: false }));
  attemptSelect.addEventListener('change', () => {
    selectedId = attemptSelect.value;
    const attempt = selectedAttempt();
    showDetail(attempt?.markers?.[0] || null);
    redrawDiagnostics();
    if (attempt?.markers?.length) focusMarker(attempt.markers[0]);
  });

  async function pollStatus() {
    clearTimeout(statusTimer);
    try {
      const res = await fetch(`/api/regeneration-status?t=${Date.now()}`, { cache: 'no-store' });
      const status = await res.json();
      if (status.state !== lastStatus) {
        if (status.state === 'running') clearDiagnosticsView();
        if (status.state === 'failed') await loadDiagnostics({ focus: true });
        if (status.state === 'completed') {
          payload = null;
          selectedId = null;
          summary.textContent = '최근 레이스라인 생성이 성공했습니다. 표시할 실패 위치가 없습니다.';
          renderPayload();
        }
        lastStatus = status.state;
      }
      statusTimer = setTimeout(pollStatus, status.state === 'running' ? 500 : 1200);
    } catch (_) {
      statusTimer = setTimeout(pollStatus, 2000);
    }
  }

  window.addEventListener('resize', redrawDiagnostics);
  new MutationObserver(redrawDiagnostics).observe(base, { attributes: true, attributeFilter: ['width', 'height'] });
  loadDiagnostics({ focus: false });
  pollStatus();
})();
