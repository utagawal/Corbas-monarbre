# Mon arbre à Corbas – « Un enfant, un arbre » (prototype)

Application indépendante (Flask + SQLite) : formulaire public de parrainage, back-office pour les agents et l'administrateur, certificat PDF avec carte OpenStreetMap, export Excel.

La conception détaillée (parcours, textes des écrans et des e-mails, règles de gestion) est dans [docs/conception.md](docs/conception.md).

## Démarrage rapide (test en local)

```bash
cp .env.example .env     # puis éditer : ADMIN_EMAIL, ADMIN_PASSWORD, adresses de la mairie
# pour tester avec des données d'exemple : DEMO=1 dans .env
docker compose up --build
```

- Formulaire public : `https://<domaine>/`
- Back-office : `https://<domaine>/admin/` (compte `ADMIN_EMAIL` / `ADMIN_PASSWORD`, créé au premier démarrage seulement)
- Sans `ADMIN_PASSWORD`, un mot de passe aléatoire est généré et affiché dans les journaux (`docker compose logs app`).
- `SECRET_KEY` est facultatif : sans valeur, une clé aléatoire est créée et conservée dans le volume (`/data/secret.key`).
- Sans domaine (test) : retirer le service `caddy` du compose, publier `8000:8000` sur le service `app` et retirer `TRUST_PROXY`.

En production : `DEMO=0`, `HTTPS=1`, vrai nom de domaine dans le `Caddyfile`, serveur SMTP renseigné.

### Hébergement sous un sous-chemin

Pour servir l'application sous un sous-chemin d'un domaine déjà utilisé (par exemple `https://maps.utagawavtt.com/monarbre/`) derrière un nginx existant, renseignez `URL_PREFIX=/monarbre` dans `.env`, publiez le port de l'application en local seulement (par exemple `127.0.0.1:8010:8000` dans un `docker-compose.override.yml`) et lancez uniquement l'application (`docker compose up -d --build app`, sans le Caddy du projet). Le serveur web doit **retirer** le préfixe avant de transmettre la requête (barre oblique finale dans `proxy_pass`). L'application remet le préfixe dans tous ses liens, formulaires et redirections, et donne à son cookie de session le chemin `/monarbre` (nom `monarbre_session`) : il ne se mélange pas à ceux des autres applications du domaine. Dans le bloc `server` du domaine :

```nginx
location = /monarbre { return 301 /monarbre/; }

location ^~ /monarbre/ {
    proxy_pass http://127.0.0.1:8010/;   # la barre finale retire /monarbre avant de transmettre
    client_max_body_size 6m;             # copie du livret de famille : 5 Mo maximum
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
}
```

`^~` garantit que ce bloc passe avant d'éventuels blocs `location` à expression régulière du domaine (par exemple pour le cache des images). `APP_URL`, s'il est renseigné, est l'adresse du site **sans** le sous-chemin (`https://maps.utagawavtt.com`) ; si le sous-chemin y figure, il n'est pas doublé.

**Serveur maps.utagawavtt.com** (derrière Cloudflare, avec le module headers-more) : le fichier prêt à inclure est [deploy/nginx/MonArbre.conf](deploy/nginx/MonArbre.conf), construit comme `ATCorbas.conf`. Il retire aussi les en-têtes CORS `*` et `X-Frame-Options` hérités du bloc `server`, et pose `noindex` pour la bêta. Installation, depuis le dossier du projet :

```bash
sudo cp deploy/nginx/MonArbre.conf /etc/nginx/snippets/MonArbre.conf
```

Puis ajouter `include /etc/nginx/snippets/MonArbre.conf;` dans le bloc `server { listen 443 … }` du domaine, tester et recharger : `sudo nginx -t && sudo systemctl reload nginx`. On copie le fichier (et non un lien symbolique) : nginx, qui tourne avec les droits root, ne doit pas relire un fichier modifiable par un autre compte.

## Utilisation

| Qui | Où | Quoi |
|---|---|---|
| Administrateur | Campagnes | Créer une campagne, ouvrir/fermer les inscriptions |
| Administrateur | Essences | Nom, texte « ce qu'il représente », caractéristiques, rôle, couleur du certificat, photo affichée sur la carte de l'essence dans le formulaire |
| Administrateur | Photos | Remplacer la photo d'accueil et celle de la page de confirmation du formulaire (recadrées automatiquement), ou rétablir la photo d'origine |
| Administrateur | Arbres | Saisir le stock d'arbres **à planter** (essence, lieu, GPS, année). Une recherche de lieu ou d'adresse à Corbas (Photon / OpenStreetMap) remplit le lieu, l'adresse et les coordonnées GPS ; un lien permet de vérifier l'emplacement sur la carte. Seuls les arbres libres sont proposés aux familles |
| Administrateur | Utilisateurs | Créer les comptes agents / administrateurs, réinitialiser un mot de passe |
| Administrateur | Notifications | Choisir les adresses (une ou plusieurs) prévenues par e-mail à chaque nouvelle demande, et envoyer un message de test |
| Agent | Demandes | Compteurs cliquables (à traiter, à imprimer, à remettre, copies de livret à supprimer), recherche (nom, e-mail, référence). Les demandes à traiter s'affichent **les plus anciennes en premier** : les arbres sont en nombre limité, on traite dans l'ordre d'arrivée |
| Agent | Fiche demande | Frise d'avancement, contrôles automatiques, arbre le plus adapté pré-sélectionné (une seule action pour valider ; confirmation si un contrôle est en alerte), certificat PDF, puis « Marquer comme remis » |
| Tous | Export Excel | Parrainages, arbres, essences, campagnes (4 feuilles) |
| Tous | Courriers | Historique des e-mails, avec la raison d'un échec d'envoi et un bouton « Renvoyer » |
| Tous | Clic sur son adresse (en haut à droite) | Changer son mot de passe |

Statuts : Reçue → Validée → Certificat imprimé → Remis. Branches : Complément demandé, Liste d'attente, Refusée, Annulée. Le serveur refuse toute transition non prévue.

**Places proposées aux familles.** Le formulaire propose les arbres libres de la campagne *moins* les demandes en cours de traitement (Reçue, Complément demandé) : une demande qui attend sa validation réserve une place. Quand il n'en reste plus, les nouvelles demandes passent automatiquement en liste d'attente. Un refus ou une annulation rend la place. Les essences désactivées ne comptent pas. Pour servir la liste d'attente, l'agent peut affecter un arbre libre d'une autre campagne.

**Copie du livret de famille** : obligatoire dans le formulaire (PDF, JPG ou PNG, 5 Mo max, type vérifié sur le contenu du fichier). Elle est stockée hors du site web dans `/data/livrets/` sous un nom aléatoire, consultable uniquement par un agent connecté. Après contrôle, l'agent clique sur « Contrôle fait : supprimer la copie » : la copie n'est plus accessible aux agents mais **reste récupérable par un administrateur pendant 6 mois** (bouton « Restaurer »), puis elle est effacée définitivement et automatiquement (purge au démarrage, puis toutes les heures). Le tableau des demandes signale les copies encore à supprimer. Un **refus** ou une **annulation** met aussi la copie en corbeille. La demande d'anonymisation RGPD (administrateur) efface la copie **immédiatement et sans récupération**, ainsi que les courriers de la famille. Sauvegardez `/data/livrets/` avec la base : les anciennes sauvegardes contiennent les copies jusqu'à leur propre expiration, donc limitez leur durée de conservation à 6 mois.

**Téléphone mobile** : obligatoire. Mobile français (06 ou 07, avec ou sans +33) ou numéro international commençant par +. Il est enregistré sous la forme « 06 12 34 56 78 ».

**Saisie assistée des adresses** : en tapant son adresse, la famille voit des suggestions de la Base Adresse Nationale (data.geopf.fr, service public gratuit, sans clé) ; choisir une suggestion remplit le code postal et la commune. Pour un enfant domicilié à Corbas, seules les adresses de Corbas sont proposées. Le navigateur n'appelle aucun service extérieur : les requêtes passent par le serveur de l'application, qui met les réponses en cache (1 h) et limite le débit (90 par minute et par adresse IP). Si le service ne répond pas, la saisie reste libre. Seules les premières lettres tapées sont transmises, sans autre donnée (c'est indiqué dans la mention RGPD). `AUTOCOMPLETION=0` désactive la fonction ; `ADRESSE_API` et `LIEU_API` permettent de pointer vers un autre service (par exemple une instance Photon hébergée par vos soins, si le service public venait à limiter l'usage). Le serveur doit pouvoir joindre ces services en HTTPS.

**Charte graphique et logo** : l'interface reprend celle de corbas.fr (Roboto, bleu `#005b94`, titres légers avec un mot en gras, boutons en pilule). Le logo de la ville est livré avec l'application (`assets/logo-ville.png`, PNG transparent de 170 × 47 px) : il figure sur le certificat, la page de connexion et le formulaire (hors iframe). Ce fichier est petit : l'impression du certificat sera plus nette avec une version d'au moins 600 px de large (ou vectorielle). Pour le remplacer, déposez la nouvelle version sous le nom `logo.png` ou `logo.jpg` dans le volume `/data` (ou indiquez son chemin dans `MAIRIE_LOGO`) : elle est prise en compte sans redémarrage. Le certificat est signé « Le Maire, Benoit Eraclas » (`MAIRIE_MAIRE`).

**Nom, logo et photos** : le dispositif s'appelle « Mon arbre à Corbas » (sous-titre « Un enfant, un arbre »). Le nom figure dans le logo livré avec l'application (`static/mon-arbre-a-corbas.svg`, lettres vectorisées : il ne dépend d'aucune police ; `static/marque.svg` et `static/marque-blanche.svg` pour l'arbre seul, `assets/mon-arbre-a-corbas.png` pour le certificat), dans le titre des pages, la signature des e-mails et le certificat ; le logo reprend la charte de la ville (bleu `#005b94`, marine, Roboto). Changer le nom suppose donc de redessiner le logo. Le formulaire est illustré par deux bandeaux (accueil, confirmation) et une photo par essence. Les photos livrées viennent de Wikimedia Commons (licences CC BY ou CC BY-SA, recadrées) : `static/photos/` et leurs mentions dans `static/photos/credits.json`, affichées automatiquement en bas des pages qui les montrent. **Pour les changer**, sans toucher aux fichiers : menu « Photos » (bandeaux) et menu « Essences » (photo d'une essence) ; les photos envoyées sont conservées dans `/data/photos/`, passent avant les photos livrées, et la mention de crédit de la photo remplacée disparaît. Une essence sans photo (nouvelle essence, par exemple) s'affiche sans image ; on peut aussi livrer une photo par essence sous `static/photos/essences/<nom-de-l-essence>.jpg` (minuscules, sans accent, tirets : `chene-vert.jpg`). Roboto (licence Apache 2.0) est embarquée au format WOFF (`static/fonts/`).

**Notification des agents** : à chaque demande reçue, un e-mail prévient les adresses configurées qu'il y a un traitement à faire (référence, essence souhaitée, nombre de demandes à traiter, lien vers la demande). Il ne contient aucune donnée personnelle. Les adresses se règlent, dans l'ordre de priorité : 1. page « Notifications » (administrateur, sans redémarrage) ; 2. variable `NOTIFICATION_EMAILS` (plusieurs adresses séparées par des virgules ou des espaces) ; 3. à défaut, tous les comptes du back-office. Le lien de la demande se construit à partir de l'adresse du site ; `APP_URL` permet de la forcer (par exemple `https://parrainage.corbas.fr`).

**Courriers** : enregistrés dans le back-office puis envoyés en arrière-plan si `SMTP_HOST` est renseigné (un serveur de messagerie lent ne fait pas attendre la famille).

**Protections** : 10 demandes enregistrées par heure et par adresse IP (`RATE_LIMIT`), connexion bloquée 15 minutes après 10 mots de passe faux, mot de passe de 10 caractères minimum, sessions de 8 heures, pages du back-office jamais mises en cache, export Excel sans formules (les textes saisis par les familles ne peuvent pas devenir des formules).

## Intégration dans WordPress

Dans une page, bloc « HTML personnalisé » :

```html
<iframe id="parrainage" src="https://parrainage.example.fr/" title="Formulaire de parrainage « Mon arbre à Corbas »"
        style="width:100%;border:0;min-height:700px" loading="lazy"></iframe>
<p><a href="https://parrainage.example.fr/" target="_blank" rel="noopener">Ouvrir le formulaire dans une nouvelle page</a></p>
<script>
window.addEventListener('message', function (e) {
  if (e.origin !== 'https://parrainage.example.fr') return;
  var f = document.getElementById('parrainage');
  if (e.data && e.data.type === 'parrainage-height') f.style.height = e.data.height + 'px';
  if (e.data && e.data.type === 'parrainage-scroll') f.scrollIntoView({behavior: 'smooth', block: 'start'});
});
</script>
```

La hauteur suit le contenu (elle diminue aussi quand l'étape est plus courte) et la page remonte au début du formulaire à chaque étape. Dans `.env`, `FRAME_ANCESTORS` doit lister le(s) domaine(s) du site WordPress (par exemple `self https://www.corbas.fr`), sinon le navigateur refuse l'iframe.

## Sauvegarde

Tout est dans le volume Docker `/data` (`parrainage.db`, `livrets/`, `secret.key`, cache des tuiles de carte). La base est en mode WAL : ne copiez pas le fichier `.db` seul pendant que l'application tourne, utilisez la sauvegarde SQLite ci-dessous. Exemple de sauvegarde nocturne :

```bash
docker compose exec -T app python -c "import sqlite3;s=sqlite3.connect('/data/parrainage.db');d=sqlite3.connect('/data/sauvegarde.db');s.backup(d)"
docker compose cp app:/data/sauvegarde.db ./sauvegardes/parrainage-$(date +%F).db
```

Les données doivent être conservées pendant la vie de l'arbre : conservez aussi un export Excel régulier.

## Tests

Une batterie de tests automatiques (formulaire, règles d'éligibilité, stock, traitement des demandes, livret, RGPD, certificat, export, comptes, courriers). Aucune dépendance à installer :

```bash
python -m unittest discover -s tests
```

## Ce que ce prototype ne fait pas encore

- Plusieurs enfants dans une même demande (jumeaux) : une demande par enfant, par décision.
- Rappel automatique des certificats non retirés.
- Pointage des arbres sur une carte : les coordonnées sont remplies par la recherche de lieu (ou saisies à la main) et doivent être à Corbas ; on les vérifie sur la carte OpenStreetMap par un lien.
- Photos des essences sur le certificat (elles figurent sur le formulaire).
- Journal détaillé des actions : seul l'agent qui a validé une demande est enregistré.
- Le certificat utilise Helvetica (le formulaire embarque Roboto, comme le site de la ville).
- Les polices du certificat ne couvrent que l'alphabet occidental : un prénom avec d'autres caractères (ex. polonais, turc) est translittéré (« Łukasz » devient « Lukasz »).
- L'anonymisation conserve le prénom de l'enfant et sa date de naissance sur la fiche de l'arbre (choix de conception : la fiche de l'arbre reste) ; à faire valider par le DPO.
- Les sites de plantation du jeu d'exemple sont indicatifs (coordonnées approximatives) : ils viennent d'une étude, pas d'un engagement.
