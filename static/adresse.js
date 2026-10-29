/* Saisie assistée : suggestions sous un champ texte, selon le motif ARIA « combobox » (clavier, lecteurs d'écran, souris, tactile).
   Les suggestions viennent de notre serveur, qui relaie la Base Adresse Nationale ou Photon. Si le service ne répond pas,
   ou si rien ne convient, on saisit à la main : le champ reste un champ texte ordinaire. */
(function () {
  if (!window.fetch) return;

  window.Autocompletion = function (opt) {
    var champ = opt.champ, parent = champ.parentNode;
    parent.classList.add('auto');
    var liste = document.createElement('ul');
    liste.className = 'auto-liste'; liste.id = champ.id + '-liste'; liste.hidden = true;
    liste.setAttribute('role', 'listbox'); liste.setAttribute('aria-label', 'Suggestions');
    var etat = document.createElement('span'); etat.className = 'sr-only'; etat.setAttribute('role', 'status');
    var note = document.createElement('span'); note.className = 'auto-note'; note.hidden = true;
    parent.appendChild(liste); parent.appendChild(etat); parent.appendChild(note);
    champ.setAttribute('role', 'combobox'); champ.setAttribute('aria-autocomplete', 'list');
    champ.setAttribute('aria-expanded', 'false'); champ.setAttribute('aria-controls', liste.id);
    champ.setAttribute('autocomplete', 'off');

    var items = [], actif = -1, minuteur = null, requete = null;

    function fermer() {
      liste.hidden = true; actif = -1;
      champ.setAttribute('aria-expanded', 'false'); champ.removeAttribute('aria-activedescendant');
    }

    function activer(n) {
      var lis = liste.querySelectorAll('li[role=option]');
      if (actif >= 0 && lis[actif]) lis[actif].setAttribute('aria-selected', 'false');
      actif = n;
      if (n >= 0 && lis[n]) {
        lis[n].setAttribute('aria-selected', 'true');
        champ.setAttribute('aria-activedescendant', lis[n].id);
        if (lis[n].scrollIntoView) lis[n].scrollIntoView({block: 'nearest'});
      } else champ.removeAttribute('aria-activedescendant');
    }

    function afficher(vide) {
      liste.textContent = '';
      items.forEach(function (it, i) {
        var li = document.createElement('li');
        li.id = champ.id + '-opt-' + i; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false'); li.dataset.i = i;
        var t = document.createElement('strong'); t.textContent = opt.titre(it); li.appendChild(t);
        var d = opt.detail ? opt.detail(it) : ''; if (d) { var s = document.createElement('small'); s.textContent = d; li.appendChild(s); }
        liste.appendChild(li);
      });
      if (!items.length && vide) {
        var v = document.createElement('li'); v.className = 'auto-vide'; v.setAttribute('role', 'presentation');
        v.textContent = opt.vide || 'Aucune suggestion : saisissez-la à la main.'; liste.appendChild(v);
      }
      if (!liste.children.length) { fermer(); return; }
      liste.style.top = (champ.offsetTop + champ.offsetHeight + 2) + 'px';
      liste.hidden = false; champ.setAttribute('aria-expanded', 'true'); actif = -1;
      etat.textContent = items.length ? items.length + ' suggestion' + (items.length > 1 ? 's' : '') + ' : flèches haut et bas, puis Entrée.' : 'Aucune suggestion.';
    }

    function choisir(n) {
      var it = items[n]; if (!it) return;
      fermer();
      var message = opt.choisi(it, champ);
      note.textContent = message || ''; note.hidden = !message;
      etat.textContent = 'Choix enregistré : ' + opt.titre(it) + '.' + (message ? ' ' + message : '');
    }

    function chercher() {
      var q = champ.value.trim();
      if (q.length < 3) { items = []; fermer(); return; }
      if (requete) requete.abort();
      requete = window.AbortController ? new AbortController() : null;
      fetch(opt.url + '?q=' + encodeURIComponent(q) + (opt.params ? opt.params() : ''),
            {signal: requete ? requete.signal : undefined, credentials: 'same-origin', headers: {Accept: 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (champ.value.trim() !== q) return;  // l'utilisateur a continué à taper : réponse périmée
          items = d.resultats || [];
          if (d.indisponible) { fermer(); return; }  // service en panne : aucun message, on tape à la main
          afficher(true);
        })
        .catch(function () { /* requête annulée ou réseau coupé : la saisie reste libre */ });
    }

    champ.addEventListener('input', function () {
      note.hidden = true; clearTimeout(minuteur); minuteur = setTimeout(chercher, 250);
    });
    champ.addEventListener('keydown', function (e) {
      var n = items.length, ouvert = !liste.hidden;
      if (e.key === 'ArrowDown' && n) { e.preventDefault(); if (!ouvert) afficher(false); activer((actif + 1) % n); }
      else if (e.key === 'ArrowUp' && n && ouvert) { e.preventDefault(); activer((actif - 1 + n) % n); }
      else if (e.key === 'Enter' && ouvert && actif >= 0) { e.preventDefault(); e.stopPropagation(); choisir(actif); }
      else if (e.key === 'Escape' && ouvert) { e.preventDefault(); e.stopPropagation(); fermer(); }
      else if (e.key === 'Tab') fermer();
    });
    champ.addEventListener('blur', function () { setTimeout(fermer, 150); });
    // mousedown (et non click) : le champ ne perd pas le focus avant le choix ; fonctionne aussi au toucher
    liste.addEventListener('mousedown', function (e) {
      var li = e.target.closest ? e.target.closest('li[role=option]') : null;
      if (li) { e.preventDefault(); choisir(+li.dataset.i); }
    });
  };
})();
