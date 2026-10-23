// Landing page: today's figures and plan prices from Arzish's public data, the billing toggle, and
// small touches (header border, referral code, signed-in shortcut). The page reads fine without it.
(function () {
  var URL_ = 'https://qgmltrboyhnwnugyrcek.supabase.co/rest/v1/';
  var KEY = 'sb_publishable_abmBtcqUF7AiTFJ2-J3eIg_Ny0nqKCk';
  var $ = function (s) { return document.querySelector(s); };
  var get = function (path) {
    return fetch(URL_ + path, { headers: { apikey: KEY, Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  };
  var num = function (v, d) { return Number(v).toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); };
  var rs = function (v) { return 'Rs ' + num(Math.round(v)); };
  var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var day = function (iso) { if (!iso) return ''; var p = iso.slice(0, 10).split('-'); return Number(p[2]) + ' ' + months[Number(p[1]) - 1]; };

  var top = $('#top');
  var onScroll = function () { top.classList.toggle('scrolled', window.scrollY > 8); };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  var q = new URLSearchParams(location.search);
  if (q.get('deleted')) $('#deleted').hidden = false;
  var ref = q.get('ref');
  try {
    if (ref && /^[a-z0-9]{4,16}$/i.test(ref)) localStorage.setItem('arzish.ref', ref.toLowerCase());
    if (localStorage.getItem('arzish-auth')) {
      $('#nav-signin').hidden = true;
      var app = $('#nav-app');
      app.textContent = 'Open the app';
    }
  } catch (e) { /* storage blocked */ }

  // Today's figures.
  get('market_docs?id=eq.latest&select=doc').then(function (rows) {
    var doc = rows && rows[0] && rows[0].doc;
    if (!doc || !doc.market) return;
    var m = doc.market;
    var set = function (k, html) { var el = document.querySelector('[data-k="' + k + '"]'); if (el && html) el.innerHTML = html; };
    var idx = doc.extra && doc.extra.psx && doc.extra.psx.indices && doc.extra.psx.indices.KSE100;
    if (m.kse100) {
      var ch = idx && typeof idx.chgPct === 'number' ? idx.chgPct : null;
      set('kse100', num(m.kse100) + (ch === null ? '' : '<small class="' + (ch < 0 ? 'down' : 'up') + '">' + (ch > 0 ? '+' : '') + ch.toFixed(2) + '%</small>'));
    }
    if (m.fx && m.fx.USD) set('usd', 'Rs ' + num(m.fx.USD, 2));
    if (m.goldTola) set('gold', rs(m.goldTola));
    if (typeof m.policyRate === 'number') set('policy', num(m.policyRate, 2).replace(/\.?0+$/, '') + '%');
    if (m.tbill && m.tbill.m12) set('tbill', num(m.tbill.m12, 2) + '%');
    if (m.nss && m.nss.BSC) set('bsc', num(m.nss.BSC, 2) + '%');
    var note = $('#today-note');
    if (note) note.textContent = 'As of ' + day(m.kse100Date || m.asOf) + (m.fxDate ? ', dollar rate of ' + day(m.fxDate) : '') + '. Arzish updates these each morning and after the PSX close.';
  }).catch(function () { /* keep the dashes */ });

  // Plans and prices.
  var plans = {};
  var period = 'year';
  var render = function () {
    var pro = plans.pro;
    if (!pro) return;
    var amt = document.querySelector('[data-plan="pro"] [data-amt]');
    var per = document.querySelector('[data-plan="pro"] [data-per]');
    if (period === 'year' && pro.price_pkr_year) {
      amt.innerHTML = rs(pro.price_pkr_year) + '<small> a year</small>';
      var save = pro.price_pkr_month ? pro.price_pkr_month * 12 - pro.price_pkr_year : 0;
      per.textContent = rs(pro.price_pkr_year / 12) + ' a month' + (save > 0 ? ', save ' + rs(save) : '');
    } else if (pro.price_pkr_month) {
      amt.innerHTML = rs(pro.price_pkr_month) + '<small> a month</small>';
      per.textContent = pro.price_usd_month ? 'About $' + pro.price_usd_month + ' a month' : 'Billed monthly';
    }
    ['free', 'pro'].forEach(function (id) {
      var p = plans[id];
      var ul = document.querySelector('[data-plan="' + id + '"] [data-features]');
      if (!p || !ul || !Array.isArray(p.features) || !p.features.length) return;
      ul.innerHTML = '';
      p.features.forEach(function (f) { var li = document.createElement('li'); li.textContent = f; ul.appendChild(li); });
    });
  };
  document.querySelectorAll('.period button').forEach(function (b) {
    b.addEventListener('click', function () {
      period = b.getAttribute('data-period');
      document.querySelectorAll('.period button').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      render();
    });
  });
  get('plans?select=id,name,price_pkr_month,price_pkr_year,price_usd_month,features&public=eq.true&order=sort').then(function (rows) {
    (rows || []).forEach(function (p) { plans[p.id] = p; });
    render();
  }).catch(function () { /* keep the static prices */ });

  // Contact address from the public settings.
  get('app_settings?key=eq.support_email&select=value').then(function (rows) {
    var v = rows && rows[0] && rows[0].value;
    var a = $('#contact');
    if (typeof v === 'string' && v.indexOf('@') > 0 && a) { a.href = 'mailto:' + v; a.hidden = false; }
  }).catch(function () { /* no contact link */ });
})();
