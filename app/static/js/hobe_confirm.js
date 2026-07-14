/* hobe_confirm.js — نافذة تأكيد عائمة موديرن موحّدة لكل لوحة الإدارة.
 * تحلّ محلّ confirm() التقليديّة.
 *
 *  الاستخدام:
 *   - برمجيًّا:   hobeConfirm('رسالة', {danger:true}).then(ok => { if(ok){...} })
 *   - مختصر:     if(!(await hcAsk('حذف نهائي؟'))) return;   // يكتشف الخطورة تلقائيًّا
 *   - تعريفيًّا:  <form data-confirm="متأكد؟" data-confirm-danger> … </form>
 *                 (يعترضها المستمع العامّ فيُظهر النافذة قبل الإرسال)
 */
(function () {
  'use strict';

  var CSS =
    '.hc-backdrop{position:fixed;inset:0;background:rgba(18,20,26,.55);backdrop-filter:blur(5px);' +
    '-webkit-backdrop-filter:blur(5px);display:none;align-items:center;justify-content:center;' +
    'z-index:2147483000;padding:20px;opacity:0;transition:opacity .2s ease;font-family:inherit}' +
    '.hc-backdrop.open{display:flex;opacity:1}' +
    '.hc-modal{background:#fff;border-radius:20px;max-width:400px;width:100%;padding:26px 24px 20px;' +
    'text-align:center;box-shadow:0 30px 70px -18px rgba(0,0,0,.5);border:1px solid rgba(0,0,0,.05);' +
    'transform:translateY(16px) scale(.95);opacity:0;' +
    'transition:transform .28s cubic-bezier(.2,1.25,.35,1),opacity .2s ease;direction:rtl}' +
    '.hc-backdrop.open .hc-modal{transform:none;opacity:1}' +
    '.hc-ic{width:62px;height:62px;border-radius:50%;margin:0 auto 16px;display:flex;align-items:center;' +
    'justify-content:center;font-size:27px;background:rgba(244,186,42,.16);color:#c8951a}' +
    '.hc-danger .hc-ic{background:rgba(239,68,68,.13);color:#dc2626}' +
    '.hc-title{font-size:18px;font-weight:800;margin:0 0 8px;color:#1e2530}' +
    '.hc-msg{font-size:14px;line-height:1.65;color:#5b6472;margin:0 0 22px;word-break:break-word}' +
    '.hc-acts{display:flex;gap:10px}' +
    '.hc-btn{flex:1;border:0;border-radius:12px;padding:12px 16px;font-family:inherit;font-weight:800;' +
    'font-size:14px;cursor:pointer;transition:.15s ease}' +
    '.hc-btn:focus-visible{outline:2px solid #F4BA2A;outline-offset:2px}' +
    '.hc-cancel{background:#f0f1f3;color:#4b5563}.hc-cancel:hover{background:#e5e8eb}' +
    '.hc-ok{background:linear-gradient(135deg,#c8951a,#F4BA2A);color:#1e1e1e}' +
    '.hc-ok:hover{filter:brightness(1.04);transform:translateY(-1px)}' +
    '.hc-danger .hc-ok{background:linear-gradient(135deg,#dc2626,#ef4444);color:#fff}' +
    '@media (prefers-color-scheme:dark){' +
    '.hc-modal{background:#1f242c;border-color:rgba(255,255,255,.08)}' +
    '.hc-title{color:#f1f3f5}.hc-msg{color:#aab2bd}' +
    '.hc-cancel{background:#2c333c;color:#cbd2da}.hc-cancel:hover{background:#353d47}}';

  var HTML =
    '<div class="hc-backdrop" id="hobe-confirm" role="alertdialog" aria-modal="true">' +
    '<div class="hc-modal">' +
    '<div class="hc-ic"><i class="fa-solid fa-circle-question"></i></div>' +
    '<h3 class="hc-title"></h3><p class="hc-msg"></p>' +
    '<div class="hc-acts">' +
    '<button type="button" class="hc-btn hc-cancel"></button>' +
    '<button type="button" class="hc-btn hc-ok"></button>' +
    '</div></div></div>';

  var bd, elTitle, elMsg, elOk, elCancel, elIc, resolver = null, prevFocus = null;

  function build() {
    if (bd || document.getElementById('hobe-confirm')) { bd = bd || document.getElementById('hobe-confirm'); return; }
    if (!document.body) return;
    var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    var wrap = document.createElement('div'); wrap.innerHTML = HTML;
    bd = wrap.firstChild; document.body.appendChild(bd);
    elTitle = bd.querySelector('.hc-title'); elMsg = bd.querySelector('.hc-msg');
    elOk = bd.querySelector('.hc-ok'); elCancel = bd.querySelector('.hc-cancel'); elIc = bd.querySelector('.hc-ic');
    elOk.addEventListener('click', function () { finish(true); });
    elCancel.addEventListener('click', function () { finish(false); });
    bd.addEventListener('click', function (e) { if (e.target === bd) finish(false); });
    document.addEventListener('keydown', function (e) {
      if (!bd.classList.contains('open')) return;
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
      else if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    });
  }

  function finish(val) {
    if (!bd) return;
    bd.classList.remove('open');
    var r = resolver; resolver = null;
    if (prevFocus && prevFocus.focus) { try { prevFocus.focus(); } catch (e) {} }
    if (r) r(val);
  }

  window.hobeConfirm = function (message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      build();
      if (!bd) { resolve(true); return; }               // fallback آمن
      if (resolver) finish(false);                        // نافذة سابقة مفتوحة
      resolver = resolve;
      var danger = !!opts.danger;
      bd.classList.toggle('hc-danger', danger);
      elTitle.textContent = opts.title || (danger ? 'تأكيد إجراء حسّاس' : 'تأكيد الإجراء');
      elMsg.textContent = message || 'هل أنت متأكّد من المتابعة؟';
      elOk.textContent = opts.confirmText || (danger ? 'نعم، تابِع' : 'تأكيد');
      elCancel.textContent = opts.cancelText || 'إلغاء';
      elIc.innerHTML = '<i class="fa-solid fa-' + (danger ? 'triangle-exclamation' : 'circle-question') + '"></i>';
      prevFocus = document.activeElement;
      bd.classList.add('open');
      setTimeout(function () { try { elOk.focus(); } catch (e) {} }, 60);
    });
  };

  // مختصر يكتشف الخطورة من نصّ الرسالة (حذف/نهائي/تصفير…)
  window.hcAsk = function (message, opts) {
    opts = opts || {};
    if (opts.danger === undefined) {
      opts.danger = /حذف|نهائ|تصفير|إلغاء|تعطيل|قطع|مسح|إزالة/.test(String(message || ''));
    }
    return window.hobeConfirm(message, opts);
  };

  // اعتراض عامّ: أيّ <form data-confirm="…"> يُظهر النافذة قبل الإرسال الفعليّ.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.nodeName !== 'FORM' || !form.hasAttribute('data-confirm')) return;
    if (form.__hcPassed) { form.__hcPassed = false; return; }  // مرور الإرسال البرمجيّ
    e.preventDefault(); e.stopPropagation();
    var msg = form.getAttribute('data-confirm');
    window.hobeConfirm(msg, {
      danger: form.hasAttribute('data-confirm-danger'),
      title: form.getAttribute('data-confirm-title') || undefined,
      confirmText: form.getAttribute('data-confirm-ok') || undefined
    }).then(function (ok) {
      if (!ok) return;
      form.__hcPassed = true;
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    });
  }, true);
})();
