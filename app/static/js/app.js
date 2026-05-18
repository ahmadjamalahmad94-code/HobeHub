function toggleBeneficiarySections(selectEl, scopeId){
  var container = document.getElementById(scopeId);
  if(!container) return;
  var value = (selectEl && selectEl.value) || '';
  var sections = container.querySelectorAll('.form-section');
  sections.forEach(function(sec){sec.classList.remove('active');});
  var target = container.querySelector('.section-' + value);
  if(target){target.classList.add('active');}
}
function syncTypeTabs(scopeId, value){
  var container = document.getElementById(scopeId);
  if(!container) return;
  container.querySelectorAll('.type-tab').forEach(function(btn){ btn.classList.toggle('active', btn.dataset.value === value); });
}
function setBeneficiaryType(scopeId, value){
  var container = document.getElementById(scopeId);
  if(!container) return false;
  var input = container.querySelector('select[name="user_type"], input[name="user_type"]');
  if(input){ input.value = value; toggleBeneficiarySections(input, scopeId); }
  syncTypeTabs(scopeId, value);
  return false;
}
function initBeneficiaryForms(){
  document.querySelectorAll('[data-beneficiary-scope]').forEach(function(scope){
    var input = scope.querySelector('select[name="user_type"], input[name="user_type"]');
    if(input){toggleBeneficiarySections(input, scope.id); syncTypeTabs(scope.id, input.value || 'tawjihi');}
  });
}
function applySidebarState(collapsed){
  var layout = document.getElementById('app-layout');
  if(!layout) return;
  layout.classList.toggle('sidebar-collapsed', !!collapsed);
}
function toggleSidebar(){
  var layout = document.getElementById('app-layout');
  if(!layout) return false;
  applySidebarState(!layout.classList.contains('sidebar-collapsed'));
  return false;
}
function closeSidebar(){
  applySidebarState(true);
  return false;
}

function initMobileSidebarState(){
  var layout = document.getElementById('app-layout');
  if(!layout) return;
  var isMobile = window.matchMedia && window.matchMedia('(max-width:900px)').matches;
  if(isMobile){
    applySidebarState(true);
  }
}

document.addEventListener('DOMContentLoaded', initMobileSidebarState);
window.addEventListener('resize', initMobileSidebarState);

function renderToast(message, category){
  const stack = document.getElementById('toast-stack');
  if(!stack || !message) return;
  const toast = document.createElement('div');
  toast.className = 'flash toast ' + (category || 'success');
  toast.textContent = message;
  stack.appendChild(toast);
  setTimeout(function(){ toast.style.opacity = '0'; toast.style.transform='translateY(8px)'; }, 3200);
  setTimeout(function(){ toast.remove(); }, 3600);
}
function showLiveFlash(message, category){
  var area = document.getElementById('live-flash-area');
  if(!area) return;
  var box = document.createElement('div');
  box.className = 'flash ' + (category || 'success');
  box.textContent = message;
  area.prepend(box);
  renderToast(message, category || 'success');
  setTimeout(function(){ box.remove(); }, 1800);
}
function guardSingleSubmit(form){
  if(form.dataset.submitting === '1') return false;
  form.dataset.submitting = '1';
  form.classList.add('ajax-saving');
  var btn = form.querySelector('button[type="submit"]');
  if(btn){ btn.disabled = true; }
  return true;
}
async function ajaxPost(url, body){
  const csrf = window.HOBEHUB_CSRF_TOKEN || (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const options = {method:'POST', headers:{'X-Requested-With':'XMLHttpRequest'}};
  if(csrf){ options.headers['X-CSRFToken'] = csrf; }
  if(body instanceof FormData){ options.body = body; }
  const response = await fetch(url, options);
  const data = await response.json();
  if(!response.ok || !data.ok){ throw new Error((data && data.message) || 'حدث خطأ'); }
  return data;
}
function replaceRowAndModal(data, rowId, modalId){
  if(data.remove_row){
    const row = document.getElementById('beneficiary-row-' + rowId);
    if(row) row.remove();
  } else if(data.row_html){
    const row = document.getElementById('beneficiary-row-' + rowId);
    if(row) row.outerHTML = data.row_html;
  }
  if(modalId && data.modal_html){
    const oldModal = document.getElementById(modalId);
    if(oldModal){ oldModal.outerHTML = data.modal_html; }
  }
  if(data.message){ showLiveFlash(data.message, data.category || 'success'); }
}
async function incrementUsageAjax(url, rowId, modalId){
  try{
    const data = await ajaxPost(url);
    replaceRowAndModal(data, rowId, modalId);
  }catch(err){ showLiveFlash(err.message || 'تعذر إضافة البطاقة', 'error'); }
  return false;
}
async function submitBeneficiaryEdit(form, rowId, modalId){
  form.classList.add('ajax-saving');
  try{
    const data = await ajaxPost(form.action, new FormData(form));
    replaceRowAndModal(data, rowId, modalId);
    window.location.hash = '#!';
  }catch(err){
    showLiveFlash(err.message || 'تعذر حفظ التعديل', 'error');
  }finally{
    form.classList.remove('ajax-saving');
  }
  return false;
}

function sortChoiceCards(containerId){
  const wrap = document.getElementById(containerId);
  if(!wrap) return;
  const cards = Array.from(wrap.querySelectorAll('.choice-card'));
  cards.sort((a,b)=>parseInt(b.dataset.rank||'0',10)-parseInt(a.dataset.rank||'0',10));
  cards.forEach(card=>wrap.appendChild(card));
}
function selectChoice(containerId, hiddenId, card){
  const wrap = document.getElementById(containerId);
  const hidden = document.getElementById(hiddenId);
  if(!wrap || !hidden || !card) return;
  wrap.querySelectorAll('.choice-card').forEach(c=>c.classList.remove('active'));
  card.classList.add('active');
  hidden.value = card.dataset.value || '';
}
function selectReason(card){ selectChoice('usage-reason-grid', 'usage_reason', card); }
function selectCardType(card){ selectChoice('card-type-grid', 'card_type', card); }
function openGlobalUsageModal(rowId, submitUrl){
  const modal = document.getElementById('global-usage-modal');
  const form = document.getElementById('global-usage-form');
  if(!modal || !form) return false;
  form.action = submitUrl;
  form.dataset.rowId = String(rowId);
  form.reset();
  form.dataset.submitting = '0';
  const notes = form.querySelector('textarea[name="usage_notes"]');
  if(notes) notes.value = '';
  sortChoiceCards('usage-reason-grid');
  const defaultReason = document.querySelector('#usage-reason-grid .choice-card');
  const defaultCard = document.querySelector('#card-type-grid .choice-card[data-value="ساعة"]') || document.querySelector('#card-type-grid .choice-card');
  if(defaultReason) selectReason(defaultReason);
  if(defaultCard) selectCardType(defaultCard);
  modal.classList.add('show-modal');
  return false;
}

function closeGlobalUsageModal(){
  const modal = document.getElementById('global-usage-modal');
  const form = document.getElementById('global-usage-form');
  if(modal) modal.classList.remove('show-modal');
  if(form){
    form.reset();
    form.action = '';
    form.dataset.rowId = '';
    form.dataset.submitting = '0';
  }
  document.querySelectorAll('#usage-reason-grid .choice-card, #card-type-grid .choice-card').forEach(c=>c.classList.remove('active'));
  return false;
}

function updateBulkSelectedCount(){
  const checks = Array.from(document.querySelectorAll('.row-select'));
  const count = checks.filter(cb => cb.checked).length;
  const box = document.getElementById('selected-count');
  if(box){ box.textContent = String(count); }
  const master = document.getElementById('select-all');
  if(master){
    master.checked = checks.length > 0 && count === checks.length;
    master.indeterminate = count > 0 && count < checks.length;
  }
}
function toggleSelectAll(master){
  document.querySelectorAll('.row-select').forEach(function(cb){ cb.checked = !!master.checked; });
  updateBulkSelectedCount();
  return true;
}
function getSelectedBeneficiaryIds(){
  return Array.from(document.querySelectorAll('.row-select:checked')).map(cb => cb.value);
}
function submitBulkDelete(){
  const ids = getSelectedBeneficiaryIds();
  if(!ids.length){ showLiveFlash('حدد مستفيدًا واحدًا على الأقل.', 'error'); return false; }
  if(!confirm('هل تريد حذف المستفيدين المحددين؟')) return false;
  const form = document.getElementById('bulk-delete-form');
  form.querySelector('input[name="ids"]').value = ids.join(',');
  form.submit();
  return false;
}
function submitBulkExport(){
  const ids = getSelectedBeneficiaryIds();
  if(!ids.length){ showLiveFlash('حدد مستفيدًا واحدًا على الأقل.', 'error'); return false; }
  const form = document.getElementById('bulk-export-form');
  form.querySelector('input[name="ids"]').value = ids.join(',');
  form.submit();
  return false;
}

let powerTimerPollHandle = null;
let powerTimerBeepHandle = null;
let lastPowerTimerAlertKey = null;
function formatTimerSeconds(total){
  total = Math.max(0, parseInt(total || 0, 10));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if(h > 0){ return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0'); }
  return String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}
function timerStateLabel(state){
  return ({running:'يعمل الآن', paused:'متوقف مؤقتًا', stopped:'متوقف', alarm:'انتهى الوقت'}[state] || 'حالة غير محددة');
}
function timerStateClass(state){
  return 'timer-status-' + (state || 'stopped');
}
function stopPowerTimerSound(){
  if(powerTimerBeepHandle){ clearInterval(powerTimerBeepHandle); powerTimerBeepHandle = null; }
  const audio = document.getElementById('power-timer-audio');
  if(audio){ try{ audio.pause(); audio.currentTime = 0; }catch(e){} }
}
function startPowerTimerSound(){
  const audio = document.getElementById('power-timer-audio');
  if(!audio) return;
  if(powerTimerBeepHandle) return;
  const playNow = function(){ audio.play().catch(function(){}); };
  playNow();
  powerTimerBeepHandle = setInterval(playNow, 2500);
}
function showPowerTimerAlert(message, sticky){
  const box = document.getElementById('power-timer-alert');
  const text = document.getElementById('power-timer-alert-text');
  if(!box || !text) return;
  text.textContent = message;
  box.classList.add('show');
  if(!sticky){
    clearTimeout(box._hideTimeout);
    box._hideTimeout = setTimeout(function(){ box.classList.remove('show'); }, 7000);
  }
}
function dismissPowerTimerAlert(){
  const box = document.getElementById('power-timer-alert');
  if(box) box.classList.remove('show');
  stopPowerTimerSound();
  return false;
}
async function postPowerTimer(url, bodyObj){
  const fd = new URLSearchParams();
  Object.keys(bodyObj || {}).forEach(function(k){ fd.append(k, bodyObj[k]); });
  const csrf = window.HOBEHUB_CSRF_TOKEN || (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const headers = {'X-Requested-With':'XMLHttpRequest'};
  if(csrf){ headers['X-CSRFToken'] = csrf; }
  const res = await fetch(url, {method:'POST', headers:headers, body:fd});
  const data = await res.json();
  if(!res.ok || !data.ok){ throw new Error(data.message || 'حدث خطأ'); }
  return data;
}
function requestPowerTimerNotificationPermission(){
  if(typeof Notification === 'undefined') return;
  if(Notification.permission === 'default'){ Notification.requestPermission().catch(function(){}); }
}
function notifyPowerTimerDone(key){
  if(lastPowerTimerAlertKey === key) return;
  lastPowerTimerAlertKey = key;
  showPowerTimerAlert('انتهى وقت دورة الكهرباء. سيبدأ العد من جديد بعد 10 ثوانٍ.', true);
  startPowerTimerSound();
  if(typeof Notification !== 'undefined' && Notification.permission === 'granted'){
    try{ new Notification('مؤقت الكهرباء', {body:'انتهى الوقت. سيبدأ عد جديد تلقائيًا بعد 10 ثوانٍ.'}); }catch(e){}
  }
}
function updateLiveClock(){
  const now = new Date();
  const timeText = now.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  const dateText = now.toLocaleDateString('en-GB');
  const ids = ['global-live-clock-time','timer-page-live-time'];
  ids.forEach(function(id){ const el = document.getElementById(id); if(el) el.textContent = timeText; });
  const dates = ['global-live-clock-date','timer-page-live-date'];
  dates.forEach(function(id){ const el = document.getElementById(id); if(el) el.textContent = dateText; });
}
function updateTimerProgressVisual(data){
  const duration = Math.max(60, parseInt(data.duration_seconds || ((data.duration_minutes || 30) * 60), 10));
  let progress = 0;
  if(data.state === 'running'){ progress = ((duration - (data.display_remaining_seconds || 0)) / duration) * 100; }
  else if(data.state === 'alarm'){ progress = 100; }
  else if(data.state === 'paused'){ progress = ((duration - (data.display_remaining_seconds || 0)) / duration) * 100; }
  progress = Math.max(0, Math.min(100, progress));
  const circle = document.getElementById('timer-ring-progress');
  if(circle){
    const radius = 130;
    const circumference = 2 * Math.PI * radius;
    circle.style.strokeDasharray = String(circumference);
    circle.style.strokeDashoffset = String(circumference - (progress / 100) * circumference);
  }
  const strip = document.getElementById('timer-progress-fill');
  if(strip) strip.style.width = progress.toFixed(1) + '%';
  const mini = document.getElementById('dashboard-timer-progress-fill');
  if(mini) mini.style.width = progress.toFixed(1) + '%';
}
function updatePowerTimerWidgets(data){
  const badge = document.getElementById('timer-global-badge');
  const badgeState = document.getElementById('timer-global-badge-state');
  const badgeRemain = document.getElementById('timer-global-badge-remaining');
  if(badge && badgeState && badgeRemain){
    badge.className = 'timer-mini ' + timerStateClass(data.state) + (data.state === 'running' ? ' timer-pulse' : '');
    badgeState.textContent = timerStateLabel(data.state);
    badgeRemain.textContent = data.state === 'stopped' ? '--:--' : formatTimerSeconds(data.display_remaining_seconds || 0);
  }
  const ids = ['dashboard-timer-remaining','timer-page-remaining'];
  ids.forEach(function(id){ const el = document.getElementById(id); if(el) el.textContent = data.state === 'stopped' ? '--:--' : formatTimerSeconds(data.display_remaining_seconds || 0); });
  const states = ['dashboard-timer-state','timer-page-state'];
  states.forEach(function(id){ const el = document.getElementById(id); if(el){ el.textContent = timerStateLabel(data.state); el.className = 'timer-state-badge ' + timerStateClass(data.state) + (data.state === 'running' ? ' timer-pulse' : ''); } });
  const cycle = document.getElementById('timer-page-cycle-minutes');
  if(cycle) cycle.textContent = String(data.duration_minutes || 30);
  const phase = document.getElementById('timer-page-phase');
  if(phase) phase.textContent = data.phase_label || '-';
  const restart = document.getElementById('timer-page-restart');
  if(restart) restart.textContent = String(data.auto_restart_delay_seconds || 10);
  const minutesInput = document.getElementById('timer-minutes-input');
  if(minutesInput && document.activeElement !== minutesInput){ minutesInput.value = String(data.duration_minutes || 30); }
  const pauseBtn = document.getElementById('timer-pause-btn');
  const resumeBtn = document.getElementById('timer-resume-btn');
  const stopBtn = document.getElementById('timer-stop-btn');
  if(pauseBtn) pauseBtn.style.display = data.state === 'running' ? 'inline-flex' : 'none';
  if(resumeBtn) resumeBtn.style.display = data.state === 'paused' ? 'inline-flex' : 'none';
  if(stopBtn) stopBtn.style.display = data.state === 'stopped' ? 'none' : 'inline-flex';
  updateTimerProgressVisual(data);
  if(data.state === 'alarm'){
    notifyPowerTimerDone(data.alert_key || 'alarm');
  } else {
    if(lastPowerTimerAlertKey && data.state === 'running'){ dismissPowerTimerAlert(); }
  }
}
async function refreshPowerTimerStatus(){
  try{
    const res = await fetch('/api/power-timer/status', {headers:{'X-Requested-With':'XMLHttpRequest'}});
    const data = await res.json();
    if(!res.ok || !data.ok){ return; }
    updatePowerTimerWidgets(data);
  }catch(e){}
}
async function startPowerTimer(){
  const input = document.getElementById('timer-minutes-input');
  const minutes = input ? parseInt(input.value || '30', 10) : 30;
  try{ const data = await postPowerTimer('/api/power-timer/start', {minutes: minutes}); showLiveFlash(data.message || 'تم تشغيل المؤقت.', 'success'); refreshPowerTimerStatus(); }
  catch(err){ showLiveFlash(err.message || 'تعذر تشغيل المؤقت', 'error'); }
  return false;
}
async function pausePowerTimer(){ try{ const data = await postPowerTimer('/api/power-timer/pause', {}); showLiveFlash(data.message || 'تم الإيقاف المؤقت.', 'success'); refreshPowerTimerStatus(); }catch(err){ showLiveFlash(err.message || 'تعذر الإيقاف المؤقت', 'error'); } return false; }
async function resumePowerTimer(){ try{ const data = await postPowerTimer('/api/power-timer/resume', {}); showLiveFlash(data.message || 'تم الاستئناف.', 'success'); refreshPowerTimerStatus(); }catch(err){ showLiveFlash(err.message || 'تعذر الاستئناف', 'error'); } return false; }
async function stopPowerTimer(){ if(!confirm('هل تريد إيقاف المؤقت نهائيًا لهذا اليوم؟')) return false; try{ const data = await postPowerTimer('/api/power-timer/stop', {}); showLiveFlash(data.message || 'تم الإيقاف النهائي.', 'success'); dismissPowerTimerAlert(); refreshPowerTimerStatus(); }catch(err){ showLiveFlash(err.message || 'تعذر الإيقاف النهائي', 'error'); } return false; }


async function refreshDashboardLive(){
  const root = document.getElementById('dashboard-live-root');
  if(!root) return;
  try{
    const res = await fetch('/api/dashboard/live', {headers:{'X-Requested-With':'XMLHttpRequest'}});
    const data = await res.json();
    if(!res.ok || !data.ok) return;
    ['all_count','today_usage','month_usage','archive_total','active_week'].forEach(function(key){
      document.querySelectorAll('[data-live-key="'+key+'"]').forEach(function(el){ el.textContent = String(data[key] ?? '0'); });
    });
  }catch(e){}
}
function initPhoneCounters(){
  document.querySelectorAll('input[name="phone"]').forEach(function(input){
    if(input.dataset.counterReady === '1') return;
    input.dataset.counterReady = '1';
    input.setAttribute('maxlength','10');
    input.setAttribute('inputmode','numeric');
    input.setAttribute('autocomplete','off');
    const helper = document.createElement('div');
    helper.className = 'phone-helper';
    helper.innerHTML = '<span>رقم الجوال يجب أن يكون 10 أرقام.</span><span class="remaining"></span>';
    input.insertAdjacentElement('afterend', helper);
    const remaining = helper.querySelector('.remaining');
    const sync = function(){
      input.value = (input.value || '').replace(/\D/g,'').slice(0,10);
      const len = input.value.length;
      const left = Math.max(0, 10 - len);
      remaining.textContent = left === 0 ? 'مكتمل 10/10' : ('باقي ' + left + ' أرقام');
      helper.classList.toggle('good', len === 10);
      helper.classList.toggle('bad', len > 0 && len < 10);
    };
    input.addEventListener('input', sync);
    sync();
  });
}

document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('#live-flash-area .flash').forEach(function(el){ renderToast(el.textContent || '', el.classList.contains('error') ? 'error' : (el.classList.contains('info') ? 'info' : 'success')); setTimeout(function(){ el.remove(); }, 1000); });
  initBeneficiaryForms();
  initPhoneCounters();
  refreshDashboardLive();
  setInterval(refreshDashboardLive, 15000);
  applySidebarState(true);
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  requestPowerTimerNotificationPermission();
  refreshPowerTimerStatus();
  powerTimerPollHandle = setInterval(refreshPowerTimerStatus, 5000);
});
