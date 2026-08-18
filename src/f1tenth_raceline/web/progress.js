(() => {
  const regenerate = document.getElementById('regenerateBtn');
  const download = document.getElementById('downloadOutputBtn');
  const progress = document.getElementById('generationProgress');
  const stage = document.getElementById('generationStage');
  const message = document.getElementById('generationMessage');
  const elapsed = document.getElementById('generationElapsed');
  if (!regenerate || !download || !progress) return;

  let timer = null;
  function stageName(value) {
    return ({idle:'대기',saving:'편집 저장',optimizer:'레이스라인 최적화',export:'산출물 저장',finalizing:'최종 반영',completed:'완료',failed:'실패'})[value] || value || '처리 중';
  }
  async function poll(force=false) {
    clearTimeout(timer);
    try {
      const res = await fetch('api/regeneration-status?t=' + Date.now(), {cache:'no-store'});
      const data = await res.json();
      progress.classList.toggle('hidden', data.state === 'idle' && !force);
      stage.textContent = stageName(data.stage);
      message.textContent = data.error || data.message || '';
      elapsed.textContent = `경과 시간 ${Number(data.elapsed_s || 0).toFixed(1)}초`;
      download.disabled = !data.output_available || data.state === 'running';
      if (data.state === 'running' || force) timer = setTimeout(() => poll(false), 500);
    } catch (_) {
      if (force) timer = setTimeout(() => poll(true), 1000);
    }
  }
  regenerate.addEventListener('click', () => {
    progress.classList.remove('hidden');
    stage.textContent = '요청 시작';
    message.textContent = '편집 내용을 저장하고 생성 작업을 시작합니다.';
    elapsed.textContent = '경과 시간 0.0초';
    setTimeout(() => poll(true), 100);
  });
  download.addEventListener('click', () => { window.location.href = 'api/output.zip'; });
  fetch('api/state', {cache:'no-store'}).then(r=>r.json()).then(data=>{download.disabled=!data.output_available;}).catch(()=>{});
  poll(false);
})();
