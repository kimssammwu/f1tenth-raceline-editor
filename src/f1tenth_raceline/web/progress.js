(() => {
  const regenerate = document.getElementById('regenerateBtn');
  const download = document.getElementById('downloadOutputBtn');
  const status = document.getElementById('status');
  const progress = document.getElementById('generationProgress');
  const stage = document.getElementById('generationStage');
  const message = document.getElementById('generationMessage');
  const elapsed = document.getElementById('generationElapsed');
  if (!regenerate || !download || !progress) return;

  const api = name => name;
  let timer = null;
  let busy = false;

  function stageName(value) {
    return ({idle:'대기',saving:'편집 저장',optimizer:'레이스라인 최적화',export:'산출물 저장',finalizing:'최종 반영',completed:'완료',failed:'실패'})[value] || value || '처리 중';
  }

  async function poll() {
    try {
      const res = await fetch(api('api/regeneration-status') + '?t=' + Date.now(), {cache:'no-store'});
      const data = await res.json();
      progress.classList.toggle('hidden', data.state === 'idle');
      stage.textContent = stageName(data.stage);
      message.textContent = data.error || data.message || '';
      elapsed.textContent = `경과 시간 ${Number(data.elapsed_s || 0).toFixed(1)}초`;
      download.disabled = !data.output_available || data.state === 'running';
      if (data.state === 'running') {
        timer = setTimeout(poll, 500);
      }
    } catch (_) {
      if (busy) timer = setTimeout(poll, 1000);
    }
  }

  regenerate.addEventListener('click', async event => {
    if (busy) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    busy = true;
    regenerate.disabled = true;
    progress.classList.remove('hidden');
    stage.textContent = '편집 저장';
    message.textContent = '요청을 시작하는 중입니다.';
    elapsed.textContent = '경과 시간 0.0초';
    timer = setTimeout(poll, 150);
    try {
      const operations = window.__racelineOperations ? window.__racelineOperations() : null;
      const body = operations || {version:1, operations:[]};
      const res = await fetch(api('api/regenerate-raceline'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || '레이스라인 재생성 실패');
      const lap = Number(data.summary?.estimated_lap_time_iqp_s);
      status.textContent = `레이스라인 재생성 완료${Number.isFinite(lap) ? ` / IQP 예상 랩타임 ${lap.toFixed(3)}초` : ''}. output ZIP을 다운로드할 수 있습니다.`;
      status.style.color = '#aab4c0';
      download.disabled = false;
      window.dispatchEvent(new CustomEvent('raceline-regenerated'));
    } catch (error) {
      status.textContent = `레이스라인 재생성 실패: ${error.message}`;
      status.style.color = '#ff8d97';
    } finally {
      busy = false;
      regenerate.disabled = false;
      clearTimeout(timer);
      await poll();
    }
  }, true);

  download.addEventListener('click', () => {
    window.location.href = api('api/output.zip');
  });

  fetch(api('api/state'), {cache:'no-store'}).then(r=>r.json()).then(data=>{download.disabled=!data.output_available;}).catch(()=>{});
  poll();
})();
