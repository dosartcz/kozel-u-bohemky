(function () {
  'use strict';

  var GA_ID       = 'G-4DNE8ES73C';
  var STORAGE_KEY = 'kub_consent';
  var bar         = document.getElementById('cookieBar');
  var acceptBtn   = document.getElementById('cookieAccept');
  var declineBtn  = document.getElementById('cookieDecline');

  // ── Helpers ──────────────────────────────────────────────────────────────────
  function getConsent() { return localStorage.getItem(STORAGE_KEY); } // 'yes' | 'no' | null
  function setConsent(v) { localStorage.setItem(STORAGE_KEY, v); }
  function isEN() { return localStorage.getItem('kub_lang') === 'en'; }

  // ── Google Analytics ─────────────────────────────────────────────────────────
  function loadAnalytics() {
    if (document.getElementById('ga-script')) return; // already loaded
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    gtag('js', new Date());
    gtag('config', GA_ID, { anonymize_ip: true });

    var s = document.createElement('script');
    s.id    = 'ga-script';
    s.async = true;
    s.src   = 'https://www.googletagmanager.com/gtag/js?id=' + GA_ID;
    document.head.appendChild(s);
  }

  // ── Google Maps ──────────────────────────────────────────────────────────────
  function loadMap() {
    var iframe = document.querySelector('iframe[data-src]');
    if (!iframe) return;
    iframe.src = iframe.dataset.src;
    var ph = document.getElementById('mapPlaceholder');
    if (ph) ph.hidden = true;
    iframe.hidden = false;
  }

  function blockMap() {
    var iframe = document.querySelector('iframe[data-src]');
    if (!iframe) return;
    iframe.hidden = true;

    if (!document.getElementById('mapPlaceholder')) {
      var ph = document.createElement('div');
      ph.id        = 'mapPlaceholder';
      ph.className = 'map-consent-placeholder';
      ph.innerHTML =
        '<p>' + (isEN()
          ? 'The map requires cookie consent.'
          : 'Pro zobrazení mapy udělte souhlas s cookies.') + '</p>' +
        '<button class="btn btn-primary" id="mapConsentBtn">' +
          (isEN() ? 'Accept cookies' : 'Přijmout cookies') +
        '</button>';
      iframe.parentElement.appendChild(ph);
      document.getElementById('mapConsentBtn').addEventListener('click', function () {
        setConsent('yes');
        applyConsent('yes');
      });
    } else {
      document.getElementById('mapPlaceholder').hidden = false;
    }
  }

  // ── Cookie bar ───────────────────────────────────────────────────────────────
  function showBar() { if (bar) bar.removeAttribute('hidden'); }
  function hideBar() { if (bar) bar.setAttribute('hidden', ''); }

  // ── Apply consent state ──────────────────────────────────────────────────────
  function applyConsent(value) {
    if (value === 'yes') {
      loadAnalytics();
      loadMap();
      hideBar();
    } else if (value === 'no') {
      blockMap();
      hideBar();
    } else {
      blockMap();
      showBar();
    }
  }

  // ── Button handlers ──────────────────────────────────────────────────────────
  if (acceptBtn) {
    acceptBtn.addEventListener('click', function () {
      setConsent('yes');
      applyConsent('yes');
    });
  }
  if (declineBtn) {
    declineBtn.addEventListener('click', function () {
      setConsent('no');
      applyConsent('no');
    });
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  applyConsent(getConsent());

})();
