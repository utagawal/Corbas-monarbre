# Fonctionnement et réglages en détail

Ce document complète le [README](../README.md) (installation et mise en production) et la [conception](conception.md) (parcours, textes, règles de gestion). Il décrit ce que font les agents et l'administrateur, et les réglages de l'application.

## Utilisation

| Qui | Où | Quoi |
|---|---|---|
| Administrateur | Campagnes | Créer une campagne, ouvrir/fermer les inscriptions |
| Administrateur | Essences | Nom, texte « ce qu'il représente », caractéristiques, rôle, couleur du certificat, photo affichée sur la carte de l'essence dans le formulaire |
| Administrateur | Photos | Remplacer la photo d'accueil et celle de la page de confirmation du formulaire (recadrées automatiquement), ou rétablir la photo d'origine |
| Administrateur | Arbres | Saisir le stock d'arbres **à planter** (essence, variété, taille, lieu, GPS, année). Une recherche de lieu ou d'adresse à Corbas (Photon / OpenStreetMap) remplit le lieu, l'adresse et les coordonnées GPS ; un lien permet de vérifier l'emplacement sur la carte. « Modifier » corrige le lieu, le GPS, la variété et la taille d'un arbre existant (même parrainé : le certificat suit). Seuls les arbres libres sont proposés aux familles |
| Administrateur | Utilisateurs | Créer les comptes agents / administrateurs, réinitialiser un mot de passe |
| Administrateur | Notifications | Choisir les adresses (une ou plusieurs) prévenues par e-mail à chaque nouvelle demande, et envoyer un message de test |
| Agent | Demandes | Compteurs cliquables (à traiter, à imprimer, à remettre), recherche (nom, e-mail, référence). Les demandes à traiter s'affichent **les plus anciennes en premier** : les arbres sont en nombre limité, on traite dans l'ordre d'arrivée |
| Agent | Fiche demande | Frise d'avancement, contrôles automatiques, arbre le plus adapté pré-sélectionné (une seule action pour valider ; confirmation si un contrôle est en alerte), certificat PDF, puis « Marquer comme remis » |
| Tous | Export Excel | Parrainages, arbres, essences, campagnes (4 feuilles) |
| Tous | Courriers | Historique des e-mails, avec la raison d'un échec d'envoi et un bouton « Renvoyer » |
| Tous | Clic sur son adresse (en haut à droite) | Changer son mot de passe |

Statuts : Reçue → Validée → Certificat imprimé → Remis. Branches : Complément demandé, Liste d'attente, Refusée, Annulée. Le serveur refuse toute transition non prévue.

**Places proposées aux familles.** Le formulaire propose les arbres libres de la campagne *moins* les demandes en cours de traitement (Reçue, Complément demandé) : une demande qui attend sa validation réserve une place. Quand il n'en reste plus, les nouvelles demandes passent automatiquement en liste d'attente. Un refus ou une annulation rend la place. Les essences désactivées ne comptent pas. Pour servir la liste d'attente, l'agent peut affecter un arbre libre d'une autre campagne.

## Données personnelles

**Vérification de la naissance** : le formulaire ne demande aucun document. Les services de l'état civil vérifient la naissance de l'enfant et le lien avec le déclarant avec leurs propres outils, hors de l'application ; la fiche de la demande le rappelle. Au retrait du certificat, seul un justificatif de domicile est demandé (e-mails et page de confirmation). La mention RGPD du formulaire indique cette vérification. La demande d'anonymisation RGPD (administrateur) efface l'identité, les coordonnées et les courriers de la famille ; la fiche de l'arbre reste.

**Téléphone mobile** : obligatoire. Mobile français (06 ou 07, avec ou sans +33) ou numéro international commençant par +. Il est enregistré sous la forme « 06 12 34 56 78 ».

**Protections** : 10 demandes enregistrées par heure et par adresse IP (`RATE_LIMIT`), connexion bloquée 15 minutes après 10 mots de passe faux, mot de passe de 10 caractères minimum, sessions de 8 heures, pages du back-office jamais mises en cache, export Excel sans formules (les textes saisis par les familles ne peuvent pas devenir des formules).

### Anciennes copies de livret de famille

Le formulaire a d'abord demandé une copie du livret de famille. L'application ne la lit, ne la conserve et ne la supprime plus. Si des copies ont été déposées pendant les essais, elles restent dans le dossier `livrets/` du volume de données, **sans plus aucun accès depuis l'application** : effacez-les une fois pour toutes après la mise à jour (et pensez aux anciennes sauvegardes, qui peuvent en contenir).

```bash
docker compose exec app rm -rf /data/livrets
```

## Saisie assistée des adresses

En tapant son adresse, la famille voit des suggestions de la Base Adresse Nationale (data.geopf.fr, service public gratuit, sans clé) ; choisir une suggestion remplit le code postal et la commune. Pour un enfant domicilié à Corbas, seules les adresses de Corbas sont proposées. Le navigateur n'appelle aucun service extérieur : les requêtes passent par le serveur de l'application, qui met les réponses en cache (1 h) et limite le débit (90 par minute et par adresse IP). Si le service ne répond pas, la saisie reste libre. Seules les premières lettres tapées sont transmises, sans autre donnée (c'est indiqué dans la mention RGPD). `AUTOCOMPLETION=0` désactive la fonction ; `ADRESSE_API` et `LIEU_API` permettent de pointer vers un autre service (par exemple une instance Photon hébergée par vos soins, si le service public venait à limiter l'usage). Le serveur doit pouvoir joindre ces services en HTTPS.

## E-mails

**Courriers** : enregistrés dans le back-office puis envoyés en arrière-plan si `SMTP_HOST` est renseigné (un serveur de messagerie lent ne fait pas attendre la famille).

**Notification des agents** : à chaque demande reçue, un e-mail prévient les adresses configurées qu'il y a un traitement à faire (référence, essence souhaitée, nombre de demandes à traiter, lien vers la demande). Il ne contient aucune donnée personnelle. Les adresses se règlent, dans l'ordre de priorité : 1. page « Notifications » (administrateur, sans redémarrage) ; 2. variable `NOTIFICATION_EMAILS` (plusieurs adresses séparées par des virgules ou des espaces) ; 3. à défaut, tous les comptes du back-office. Le lien de la demande se construit à partir de l'adresse du site ; `APP_URL` permet de la forcer (par exemple `https://monarbre.ville-corbas.fr`).

## Identité visuelle

**Charte graphique et logo** : l'interface reprend celle de corbas.fr (Roboto, bleu `#005b94`, titres légers avec un mot en gras, boutons en pilule). Le logo de la ville est livré avec l'application (`assets/logo-ville.png`, PNG transparent de 170 × 47 px) : il figure sur le certificat, la page de connexion et le formulaire (hors iframe). Ce fichier est petit : l'impression du certificat sera plus nette avec une version d'au moins 600 px de large (ou vectorielle). Pour le remplacer, déposez la nouvelle version sous le nom `logo.png` ou `logo.jpg` dans le volume `/data` (ou indiquez son chemin dans `MAIRIE_LOGO`) : elle est prise en compte sans redémarrage. Le certificat est signé « Le Maire, Benoit Eraclas » (`MAIRIE_MAIRE`).

**Nom, logo et photos** : le dispositif s'appelle « Mon arbre à Corbas » (sous-titre « Un enfant, un arbre »). Le nom figure dans le logo livré avec l'application (`static/mon-arbre-a-corbas.svg`, lettres vectorisées : il ne dépend d'aucune police ; `static/marque.svg` et `static/marque-blanche.svg` pour l'arbre seul, `assets/mon-arbre-a-corbas.png` pour le certificat), dans le titre des pages, la signature des e-mails et le certificat ; le logo reprend la charte de la ville (bleu `#005b94`, marine, Roboto). Changer le nom suppose donc de redessiner le logo. Le formulaire est illustré par deux bandeaux (accueil, confirmation) et une photo par essence. Les photos livrées viennent de Wikimedia Commons (licences CC BY ou CC BY-SA, recadrées) : `static/photos/` et leurs mentions dans `static/photos/credits.json`, affichées automatiquement en bas des pages qui les montrent. **Pour les changer**, sans toucher aux fichiers : menu « Photos » (bandeaux) et menu « Essences » (photo d'une essence) ; les photos envoyées sont conservées dans `/data/photos/`, passent avant les photos livrées, et la mention de crédit de la photo remplacée disparaît. Une essence sans photo (nouvelle essence, par exemple) s'affiche sans image ; on peut aussi livrer une photo par essence sous `static/photos/essences/<nom-de-l-essence>.jpg` (minuscules, sans accent, tirets : `chene-vert.jpg`). Roboto (licence Apache 2.0) est embarquée au format WOFF (`static/fonts/`).

## Ce que l'application ne fait pas encore

- Plusieurs enfants dans une même demande (jumeaux) : une demande par enfant, par décision.
- Rappel automatique des certificats non retirés.
- Pointage des arbres sur une carte : les coordonnées sont remplies par la recherche de lieu (ou saisies à la main) et doivent être à Corbas ; on les vérifie sur la carte OpenStreetMap par un lien.
- Photos des essences sur le certificat (elles figurent sur le formulaire).
- Journal détaillé des actions : seul l'agent qui a validé une demande est enregistré.
- Le certificat utilise Helvetica (le formulaire embarque Roboto, comme le site de la ville).
- Les polices du certificat ne couvrent que l'alphabet occidental : un prénom avec d'autres caractères (ex. polonais, turc) est translittéré (« Łukasz » devient « Lukasz »).
- L'anonymisation conserve le prénom de l'enfant et sa date de naissance sur la fiche de l'arbre (choix de conception : la fiche de l'arbre reste) ; à faire valider par le DPO.
- Les sites du jeu d'exemple (`DEMO=1`) sont indicatifs : ils viennent d'une étude, pas d'un engagement.
