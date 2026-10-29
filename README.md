# Mon arbre à Corbas – « Un enfant, un arbre »

Parrainage d'arbres par la ville de Corbas : formulaire public (intégrable dans WordPress), back-office pour les agents et l'administrateur, certificat PDF avec carte OpenStreetMap, courriers et export Excel. Application indépendante (Flask + SQLite + gunicorn) livrée en conteneur Docker.

- [docs/fonctionnement.md](docs/fonctionnement.md) : ce que font les agents et l'administrateur, données personnelles, e-mails, logo et photos.
- [docs/conception.md](docs/conception.md) : parcours, textes des écrans et des e-mails, règles de gestion.

L'application peut démarrer **préchargée avec des exemples** (`DEMO=1` : une campagne, 5 essences, 12 arbres), pratique pour la découvrir. En production, laissez `DEMO=0` et saisissez vos données dans l'administration (Campagnes, Essences, Arbres).

## Essayer sur son poste

```bash
cp .env.example .env     # puis, dans .env : HTTPS=0 et DEMO=1
docker compose run --rm -p 8000:8000 app
```

Formulaire sur http://localhost:8000/, administration sur http://localhost:8000/admin/ (compte `ADMIN_EMAIL` / `ADMIN_PASSWORD` du `.env`). Les données sont conservées dans un volume Docker entre deux essais.

## Mise en production avec Docker

Il faut un serveur Linux avec Docker (et son plugin Compose) et git.

### 1. Récupérer le code et configurer

```bash
git clone https://github.com/utagawal/Corbas-monarbre.git
cd Corbas-monarbre
cp .env.example .env
nano .env
```

Réglages principaux du fichier `.env` (tous commentés dans `.env.example`) :

| Variable | À renseigner |
|---|---|
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Compte administrateur, créé au **tout premier démarrage** seulement. Sans mot de passe, un mot de passe aléatoire est écrit dans `docker compose logs app`. |
| `HTTPS` | `1` : cookie de session sécurisé et en-tête HSTS. |
| `DEMO` | `0` en production. |
| `FRAME_ANCESTORS` | Domaine(s) du site WordPress autorisés à intégrer le formulaire, par exemple `self https://www.corbas.fr`. Sans cela, le navigateur refuse l'iframe. |
| `DOMAINE` | Nom DNS servi par Caddy (méthode A seulement). |
| `URL_PREFIX` | Sous-répertoire (`/monarbre`) si l'application n'a pas son propre nom DNS (cas 3). Vide sinon. |
| `APP_URL` | Adresse publique **sans** sous-répertoire (`https://www.corbas.fr`), pour les liens des e-mails aux agents. Facultatif. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Envoi des e-mails. Sans `SMTP_HOST`, ils sont seulement enregistrés dans le back-office (menu Courriers). |
| `MAIRIE_*`, `NOTIFICATION_EMAILS` | Coordonnées de la mairie (certificat, e-mails) et adresses prévenues à chaque nouvelle demande. |

### 2. Choisir où publier l'application

| Situation | Méthode | `URL_PREFIX` |
|---|---|---|
| 1. Nouveau nom DNS (`monarbre.ville-corbas.fr`), serveur dont les ports 80 et 443 sont libres | **A** : Caddy fourni | vide |
| 2. Nouveau nom DNS, mais un nginx tourne déjà sur le serveur | **B** : derrière nginx, bloc `server` dédié | vide |
| 3. Sous-répertoire d'un domaine existant (`https://www.corbas.fr/monarbre/`) | **B** : derrière nginx, bloc `location` | `/monarbre` |

#### Méthode A : Caddy fourni (HTTPS automatique)

1. Chez le gestionnaire du DNS, créez un enregistrement **A** (et **AAAA** si le serveur a une adresse IPv6) `monarbre.ville-corbas.fr` vers l'adresse du serveur, et attendez qu'il soit actif.
2. Ouvrez les ports **80 et 443** du serveur (le port 80 sert à l'obtention du certificat).
3. Dans `.env` : `DOMAINE=monarbre.ville-corbas.fr`, `HTTPS=1`, `DEMO=0`, `URL_PREFIX` vide.
4. Démarrez :

```bash
docker compose up -d --build
```

Caddy obtient et renouvelle seul le certificat Let's Encrypt. Le formulaire est sur `https://monarbre.ville-corbas.fr/`, l'administration sur `https://monarbre.ville-corbas.fr/admin/`.

#### Méthode B : derrière votre nginx

L'application écoute seulement en local (`127.0.0.1:8010`) et nginx lui transmet les requêtes. Le Caddy du projet n'est pas lancé.

1. Publiez le port de l'application en local seulement, dans un fichier propre au serveur (ignoré par git) :

```bash
cat > docker-compose.override.yml <<'EOF'
services:
  app:
    ports:
      - "127.0.0.1:8010:8000"
EOF
```

2. Dans `.env` : `HTTPS=1`, `DEMO=0`, et `URL_PREFIX` selon le cas (vide pour un nom DNS dédié, `/monarbre` pour un sous-répertoire).
3. Démarrez **uniquement l'application** (toujours avec `app` : sans cela, Compose lancerait aussi le Caddy du projet, qui entrerait en conflit avec nginx sur les ports 80 et 443) :

```bash
docker compose up -d --build app
```

4. Configurez nginx selon votre cas.

**Cas 2 : nouveau nom DNS.** Créez l'enregistrement DNS comme ci-dessus, puis ajoutez un site (par exemple `/etc/nginx/sites-available/monarbre.ville-corbas.fr`, à activer dans `sites-enabled`) :

```nginx
server {
    listen 80;
    server_name monarbre.ville-corbas.fr;
    client_max_body_size 6m;                         # copie du livret de famille : 5 Mo maximum

    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
        add_header X-Robots-Tag "noindex, nofollow" always;   # voir « Deux pièges avec nginx »
    }
}
```

Puis `sudo nginx -t && sudo systemctl reload nginx`, et le certificat HTTPS : `sudo certbot --nginx -d monarbre.ville-corbas.fr` (certbot ajoute le bloc 443 et la redirection).

**Cas 3 : sous-répertoire d'un domaine existant.** Dans le bloc `server { listen 443 … }` du domaine, `URL_PREFIX=/monarbre` dans `.env` :

```nginx
location = /monarbre { return 301 /monarbre/; }

location ^~ /monarbre/ {
    proxy_pass http://127.0.0.1:8010/;   # la barre finale retire /monarbre avant de transmettre
    client_max_body_size 6m;             # copie du livret de famille : 5 Mo maximum
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 60s;
    add_header X-Robots-Tag "noindex, nofollow" always;   # voir « Deux pièges avec nginx »
}
```

Le `^~` fait passer ce bloc avant les `location` à expression régulière du domaine (cache des images, par exemple). L'application remet le préfixe dans tous ses liens et redirections, et donne à son cookie de session le chemin `/monarbre` : il ne se mélange pas à ceux des autres applications du domaine.

**Deux pièges avec nginx.**
- Le formulaire doit pouvoir s'afficher en iframe sur le site de la ville : n'envoyez pas `X-Frame-Options` pour cette application. C'est elle qui décide (`FRAME_ANCESTORS`) et qui interdit l'iframe pour l'administration. Or si votre configuration nginx en déclare un pour tout le serveur (`sudo grep -rn X-Frame-Options /etc/nginx/`), le bloc le **hérite** tant qu'il ne déclare lui-même aucun `add_header`. C'est le rôle de la ligne `add_header X-Robots-Tag` ci-dessus : elle coupe l'héritage (et évite que l'adresse de l'application soit référencée). Si vous la retirez, gardez-en un autre. Détails dans les commentaires de [deploy/nginx/MonArbre.conf](deploy/nginx/MonArbre.conf).
- Ne mettez pas ces URL en cache (pages avec données personnelles).

Le fichier [deploy/nginx/MonArbre.conf](deploy/nginx/MonArbre.conf) est la version prête à inclure pour `maps.utagawavtt.com/monarbre` (derrière Cloudflare, avec le module headers-more), à copier dans `/etc/nginx/snippets/` puis à inclure dans le bloc `server` du domaine. On copie le fichier (et non un lien symbolique) : nginx, qui tourne avec les droits root, ne doit pas relire un fichier modifiable par un autre compte.

### 3. Vérifier

```bash
docker compose ps                  # l'application doit être « healthy »
docker compose logs -f app         # journaux (mot de passe généré, erreurs d'envoi d'e-mail…)
```

- `/sante` répond `ok` (par exemple `https://monarbre.ville-corbas.fr/sante`, ou `https://www.corbas.fr/monarbre/sante`).
- Connectez-vous à `/admin/`, **changez votre mot de passe** (clic sur votre adresse, en haut à droite), puis retirez `ADMIN_PASSWORD` du `.env`.
- Menu Notifications : « envoyer un message de test » vérifie le réglage SMTP.

### Mettre à jour

```bash
git pull
docker compose up -d --build        # méthode A
docker compose up -d --build app    # méthode B
```

Les données sont dans un volume Docker : elles sont conservées. Pour arrêter : `docker compose down` (sans `-v`, qui effacerait le volume).

### Sauvegarder

Tout est dans le volume Docker monté sur `/data` : base `parrainage.db`, copies des livrets de famille (`livrets/`), clé secrète (`secret.key`), photos envoyées. La base est en mode WAL : ne copiez pas le fichier `.db` seul pendant que l'application tourne, utilisez la sauvegarde SQLite ci-dessous.

```bash
mkdir -p sauvegardes
docker compose exec -T app python -c "import sqlite3;s=sqlite3.connect('/data/parrainage.db');d=sqlite3.connect('/data/sauvegarde.db');s.backup(d)"
docker compose cp app:/data/sauvegarde.db ./sauvegardes/parrainage-$(date +%F).db
docker compose exec -T app tar -C /data -czf - livrets > ./sauvegardes/livrets-$(date +%F).tar.gz
find ./sauvegardes -name 'livrets-*.tar.gz' -mtime +180 -delete     # copies de livrets : 6 mois de conservation au plus
```

À lancer chaque nuit (cron), avec un export Excel régulier : les données doivent être conservées pendant la vie de l'arbre. Seules les archives de livrets sont purgées au bout de 6 mois (voir [données personnelles](docs/fonctionnement.md#données-personnelles)).

## Intégration dans WordPress

Dans une page, bloc « HTML personnalisé » (remplacez l'adresse par celle de votre installation, avec le sous-répertoire dans le cas 3 ; la vérification `e.origin` ne porte que sur le nom de domaine) :

```html
<iframe id="parrainage" src="https://monarbre.ville-corbas.fr/" title="Formulaire de parrainage « Mon arbre à Corbas »"
        style="width:100%;border:0;min-height:700px" loading="lazy"></iframe>
<p><a href="https://monarbre.ville-corbas.fr/" target="_blank" rel="noopener">Ouvrir le formulaire dans une nouvelle page</a></p>
<script>
window.addEventListener('message', function (e) {
  if (e.origin !== 'https://monarbre.ville-corbas.fr') return;
  var f = document.getElementById('parrainage');
  if (e.data && e.data.type === 'parrainage-height') f.style.height = e.data.height + 'px';
  if (e.data && e.data.type === 'parrainage-scroll') f.scrollIntoView({behavior: 'smooth', block: 'start'});
});
</script>
```

La hauteur suit le contenu et la page remonte au début du formulaire à chaque étape. `FRAME_ANCESTORS` (dans `.env`) doit lister le domaine du site WordPress.

## Tests

Une batterie de tests automatiques, sans dépendance à installer :

```bash
python -m unittest discover -s tests
```
