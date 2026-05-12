(function () {
  'use strict';

  // ── English translations ────────────────────────────────────────────────────
  var EN = {
    // Info bar
    'info.email':   'Email',
    'info.phone':   'Phone',
    'info.address': 'Address',

    // Navigation
    'nav.lunch':        'Lunch Menu',
    'nav.food_menu':    'Food Menu',
    'nav.drinks_menu':  'Drinks Menu',
    'nav.gallery':      'Gallery',
    'nav.contact':      'Contact',
    'nav.reservation':  'Reservation',

    // Sidebar
    'sidebar.hours_title': 'Opening Hours',
    'sidebar.hours_value': 'Monday to Sunday  11:00 – 23:00',
    'sidebar.lunch_title': 'Lunch Menu',
    'sidebar.lunch_value': 'Monday to Friday  11:00 – 14:00',
    'sidebar.cards':       'Cards accepted',
    'sidebar.social':      'Follow us',

    // Cookie bar
    'cookie.text':    'This site uses third-party cookies for Google Maps (interactive map) and Google Analytics (anonymous visitor statistics).',
    'cookie.accept':  'Accept',
    'cookie.decline': 'Decline',

    // Shared note shown under menu headings in EN mode
    'menu.lang_note': 'Dish and drink names are listed in their original Czech — thank you for your understanding.',

    // Index — lunch menu heading & empty state
    'index.menu_empty': 'Today\'s lunch menu has not been entered yet.<br>Please check back shortly.',

    // Jídelní lístek — category headings
    'jl.title':             'Food Menu',
    'jl.cat.beer_snacks':   'Beer Snacks',
    'jl.cat.soups':         'Soups',
    'jl.cat.burgers':       'Burgers & Bagels',
    'jl.cat.czech':         'Czech Classics',
    'jl.cat.grill':         'From the Pan & Grill',
    'jl.cat.fried':         'Deep Fried',
    'jl.cat.pasta':         'Pasta & Salads',
    'jl.cat.desserts':      'Desserts',
    'jl.cat.sides':         'Sides',
    'jl.cat.sauces':        'Sauces',

    // Nápojový lístek — category headings
    'nl.title':          'Drinks Menu',
    'nl.cat.tank':       'Kozel Tank Beer',
    'nl.cat.beer':       'Beer',
    'nl.cat.soft':       'Non-alcoholic Drinks',
    'nl.cat.hot':        'Hot Drinks',
    'nl.cat.wine':       'Wine & Sparkling',
    'nl.cat.herbal':     'Herbal Liqueurs',
    'nl.cat.rum':        'Rum',
    'nl.cat.tequila':    'Tequila',
    'nl.cat.whisky':     'Whisky',
    'nl.cat.brandy':     'Brandy & Cognac',
    'nl.cat.gin':        'Gin',
    'nl.cat.vodka':      'Vodka',
    'nl.cat.fruit':      'Fruit Spirits',

    // Fotogalerie
    'fg.title':           'Gallery',
    'fg.filter.all':      'All',
    'fg.filter.interior': 'Interior',
    'fg.filter.food':     'Food',

    // Kontakt
    'kt.title': 'Contact',

    // Rezervace
    'rz.title':         'Reservation',
    'rz.success_title': 'Thank you for your reservation!',
    'rz.success_text':  'We will be in touch shortly to confirm.',
    'rz.date':          'Date',
    'rz.time':          'Time',
    'rz.time_ph':       'Select time',
    'rz.guests':        'Number of guests',
    'rz.guests_ph':     'Select number',
    'rz.name':          'Name',
    'rz.name_ph':       'Jane Smith',
    'rz.email':         'E-mail',
    'rz.phone':         'Phone',
    'rz.note':          'For reservations for larger groups, please call us at <a href="tel:+420777710712">+420 777 710 712</a>.',
    'rz.add_message':   'Add a message',
    'rz.message_label': 'Message',
    'rz.message_ph':    'Birthday party, allergies, requests…',
    'rz.submit':        'Submit Reservation',
    'rz.gdpr':          'By submitting, you agree to the processing of your personal data for the purpose of handling your reservation. Data will not be shared with third parties.',
  };

  // ── Czech day name → English ────────────────────────────────────────────────
  var DAY_MAP = {
    'Pondělí': 'Monday',
    'Úterý':   'Tuesday',
    'Středa':  'Wednesday',
    'Čtvrtek': 'Thursday',
    'Pátek':   'Friday',
    'Sobota':  'Saturday',
    'Neděle':  'Sunday',
  };

  var STORAGE_KEY = 'kub_lang';

  function getLang() {
    return localStorage.getItem(STORAGE_KEY) || 'cs';
  }

  function setLang(lang) {
    localStorage.setItem(STORAGE_KEY, lang);
  }

  // ── Core translation applier ────────────────────────────────────────────────
  function applyLang(lang) {
    var isEN = lang === 'en';
    document.documentElement.lang = isEN ? 'en' : 'cs';

    // innerHTML elements
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.dataset.i18n;
      // Cache original Czech on first call
      if (el.dataset.i18nCs === undefined) {
        el.dataset.i18nCs = el.innerHTML;
      }
      el.innerHTML = isEN ? (EN[key] !== undefined ? EN[key] : el.dataset.i18nCs)
                           : el.dataset.i18nCs;
    });

    // placeholder attributes
    document.querySelectorAll('[data-i18n-ph]').forEach(function (el) {
      var key = el.dataset.i18nPh;
      if (el.dataset.i18nPhCs === undefined) {
        el.dataset.i18nPhCs = el.placeholder;
      }
      el.placeholder = isEN ? (EN[key] !== undefined ? EN[key] : el.dataset.i18nPhCs)
                             : el.dataset.i18nPhCs;
    });

    // ── Guest-count select: rebuild option labels ──────────────────────────────
    var pocet = document.getElementById('pocet');
    if (pocet) {
      Array.from(pocet.options).forEach(function (opt) {
        if (opt.disabled) return;
        var n = parseInt(opt.value, 10);
        if (isNaN(n)) return;
        if (isEN) {
          opt.textContent = n === 1 ? '1 person' : n + ' people';
        } else {
          var suffix = n === 1 ? 'osoba' : (n < 5 ? 'osoby' : 'osob');
          opt.textContent = n + ' ' + suffix;
        }
      });
    }

    // ── Day name on index page ────────────────────────────────────────────────
    var daySpan = document.querySelector('.menu-date-day[data-day-cs]');
    if (daySpan) {
      var dayCS  = daySpan.dataset.dayCs;
      var dateFmt = daySpan.dataset.dateFmt;
      if (isEN) {
        var dayEN = DAY_MAP[dayCS] || dayCS;
        daySpan.textContent = dayEN + ' ' + dateFmt;
      } else {
        daySpan.textContent = dayCS + ' ' + dateFmt;
      }
    }

    // ── Kč → CZK v cenových elementech ──────────────────────────────────────
    document.querySelectorAll('.row-price, .pivo-druh-info, .item-price').forEach(function (el) {
      if (el.dataset.priceCs === undefined) {
        el.dataset.priceCs = el.innerHTML;
      }
      el.innerHTML = isEN ? el.dataset.priceCs.replace(/\s*Kč/g, ' CZK')
                          : el.dataset.priceCs;
    });

    // ── Lang button: show the OTHER language ──────────────────────────────────
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.textContent = isEN ? 'CS' : 'EN';
    });
  }

  // ── Init ────────────────────────────────────────────────────────────────────
  function init() {
    var lang = getLang();

    // Apply translation on load (always, so CS restores correctly too)
    applyLang(lang);

    // Bind lang toggle
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        var next = getLang() === 'cs' ? 'en' : 'cs';
        setLang(next);
        applyLang(next);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
