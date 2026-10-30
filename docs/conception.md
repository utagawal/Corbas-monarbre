# « Mon arbre à Corbas » (Un enfant, un arbre)
## Conception du formulaire et du processus

Version 1 – cadrage validé le 28/10/2026 (à confirmer en conseil municipal).

### Décisions de cadrage

| Sujet | Décision |
|---|---|
| Choix de l'arbre | La famille choisit **l'essence** (1er choix + 2e choix facultatif). **La ville attribue l'arbre précis** et son emplacement. |
| Validation | Chaque demande est contrôlée par un agent avant toute remise. |
| Pièces justificatives | **Aucun document n'est déposé dans le formulaire** (décision du 30/10/2026) : les services de l'état civil vérifient la naissance de l'enfant et le lien avec le déclarant avec leurs propres outils. Le formulaire est plus court et la mairie ne conserve plus de copie de livret de famille. |
| Remise du certificat | **Papier, uniquement en mairie.** Le PDF est généré pour impression par l'agent, pas envoyé par mail. |
| Technique | Application indépendante, intégrée dans WordPress par **iframe** (ou lien de redirection). Le site WordPress n'est pas modifié. |
| Paramétrage | Un administrateur gère campagnes, essences et arbres/emplacements, sans développeur. |
| Nom du dispositif | **« Mon arbre à Corbas »**, sous-titre « Un enfant, un arbre ». Choisi parce que les arbres proposés sont déjà de pleine tige : on évite « graine » ou « pousse ». « Mon arbre » est aussi la parole de l'enfant pendant toute la vie de l'arbre. |
| Identité visuelle | Logo « arbre au cœur blanc » (couronne bleue `#005b94`, tronc marine `#262532`), nom en Roboto avec « arbre » en gras, comme les titres du site de la ville. Photos d'arbres libres de droits (accueil, confirmation, une par essence), remplaçables par la mairie dans le back-office ; crédits affichés sous le formulaire. |

---

## 1. Les trois parcours

### Parcours parent (≈ 3 minutes, mobile en priorité)
1. Page WordPress « Mon arbre à Corbas » : explication courte + iframe du formulaire.
2. Étape 1 – L'enfant.
3. Étape 2 – Le parent.
4. Étape 3 – Le choix de l'essence.
5. Étape 4 – Récapitulatif, engagements, envoi.
6. Écran de confirmation + **e-mail personnalisé** (accusé de réception).
7. Plus tard : e-mail « Le certificat de {prénom} est prêt à la mairie » (après validation).
8. Passage à l'accueil : remise du certificat, signature du retrait.

### Parcours agent (back-office, 2 clics par demande)
1. Notification « nouvelle demande » (mail quotidien groupé ou immédiat, au choix).
2. Ouvre la fiche. L'outil affiche les contrôles automatiques (délai de 12 mois, doublon, commune, stock). La naissance et le lien avec le déclarant sont vérifiés par l'état civil, hors de l'application.
3. Choisit l'action : **Valider et affecter un arbre** (l'outil propose les arbres libres de l'essence choisie, avec carte), **Mettre en liste d'attente**, **Refuser** (motif obligatoire) ou **Demander un complément**.
4. Après affectation, le certificat PDF est généré. L'agent l'imprime et l'e-mail « prêt » part.
5. Au retrait, l'agent coche **Remis le jj/mm/aaaa**.

### Parcours administrateur (paramétrage)
- **Campagnes** : nom (« Automne 2026 »), dates d'ouverture et de fermeture des inscriptions, statut.
- **Essences** : nom courant, nom latin, photo, texte « ce qu'elle représente », texte « ses caractéristiques », feuillage, hauteur adulte, couleur du certificat. Actif/inactif par campagne.
- **Arbres/emplacements** par campagne : identifiant, essence, lieu (nom + adresse), coordonnées GPS (clic sur carte), statut (libre / réservé / parrainé / planté), date de plantation.
- Modèles de mails et texte du certificat modifiables.
- Export Excel/CSV du suivi.

---

## 2. Le formulaire (textes prêts à intégrer)

**Titre :** Parrainez un arbre pour votre enfant
**Chapeau :** À chaque naissance, la ville de Corbas vous propose de parrainer un arbre planté sur la commune. Il grandira en même temps que votre enfant. Comptez 3 minutes.

**Bandeau d'état de la campagne** (affiché au-dessus, géré par l'admin) :
- Ouverte : « Il reste {n} arbres disponibles pour la campagne {nom}. » (Si n > 10, afficher « Des arbres sont encore disponibles ».)
- Complète : « Toutes les places sont attribuées. Vous pouvez vous inscrire sur liste d'attente. »
- Fermée : « Les inscriptions rouvriront à l'automne. Laissez votre e-mail pour être prévenu(e). »

### Étape 1 sur 4 – Votre enfant
| Champ | Type | Règles et aide |
|---|---|---|
| Prénom de l'enfant * | texte | « Il figurera sur le certificat. » |
| Nom de l'enfant * | texte | Usage interne (suivi). Ne figure pas sur le certificat. |
| Date de naissance * | date | Ni future, ni de plus de 12 mois. Sinon message (voir §5). |
| Lien avec Corbas * | choix | « Domicilié(e) à Corbas » (1er choix) / « Né(e) à Corbas » |

### Étape 2 sur 4 – Vous
| Champ | Type | Règles et aide |
|---|---|---|
| Vous êtes * | choix | Mère / Père / Représentant légal |
| Prénom et nom * | texte | |
| Adresse e-mail * | e-mail | « Nous vous écrirons uniquement pour cette demande. » Saisie confirmée deux fois. |
| Téléphone mobile * | tel | Obligatoire : « Pour vous joindre rapidement si besoin. » Mobile français (06 ou 07, avec ou sans +33) ou numéro international commençant par +. Enregistré sous la forme « 06 12 34 56 78 ». |
| Adresse postale * | texte + code postal + ville | Sert à vérifier le lien avec Corbas. **Saisie assistée** : suggestions de la Base Adresse Nationale (service public) ; choisir une suggestion remplit aussi le code postal et la commune. Pour un enfant domicilié à Corbas, seules les adresses de Corbas sont proposées. Les suggestions passent par le serveur de l'application (le navigateur n'appelle aucun service extérieur) ; en cas de panne, la saisie à la main reste possible. |

### Étape 3 sur 4 – Choisissez l'essence
Cartes visuelles (photo, nom, 1 ligne de description, badge « Disponible » ou « Plus que 2 »). Pas de liste déroulante.

- **Essence souhaitée ***
- **Seconde essence (facultatif)** : « Si votre premier choix n'est plus disponible. »
- Texte d'information : « La ville choisit l'emplacement précis de l'arbre parmi les sites de plantation de la campagne. Vous le découvrirez sur votre certificat. »
- Les essences sans arbre libre sont grisées avec la mention « Complet ».

### Étape 4 sur 4 – Vérifiez et envoyez
Récapitulatif modifiable (lien « Modifier » par bloc), puis :

- [ ] * J'atteste être titulaire de l'autorité parentale sur cet enfant et que les informations sont exactes.
- [ ] * J'ai compris que l'arbre reste un bien communal : le parrainage ne donne aucun droit de propriété ni d'usage exclusif, et la commune peut intervenir sur l'arbre (taille, déplacement, abattage pour motif sanitaire ou de sécurité).
- [ ] * J'accepte que mes données soient traitées pour ce dispositif (voir mentions ci-dessous).
- [ ] Je souhaite être informé(e) des actions d'entretien bénévoles autour des arbres (arrosage, paillage…). *(Facultatif)*

Bouton : **Envoyer ma demande**

**Mention RGPD (sous le bouton) :** « La mairie de Corbas traite ces données pour gérer le dispositif “Mon arbre à Corbas” (mission d'intérêt public). Elles sont conservées pendant toute la durée de vie de l'arbre parrainé et ne sont transmises à personne. La naissance de l'enfant est vérifiée par les services de l'état civil de la mairie, avec leurs propres outils : aucun document n'est à joindre. Vous pouvez exercer vos droits d'accès, de rectification et de suppression à l'accueil de la mairie ou à {adresse DPO/mail}. »

### Principes d'interaction retenus

*Revue UX/UI (octobre 2026) :* encadré « Avant de commencer » (date de naissance, e-mail) affiché à la première étape seulement ; barre de progression étiquetée (Enfant, Vous, Essence, Envoi) ; contrôle des e-mails et du code postal dès la sortie du champ ; sélecteur de date qui grise les dates de plus de 12 mois ; pastille de sélection visible sur les cartes d'essence (pas seulement la couleur) ; page de confirmation en quatre étapes (« Et maintenant ? ») avec adresse et horaires de la mairie ; fond transparent dans l'iframe ; focus clavier bleu contrasté (6,4:1), textes secondaires à plus de 4,5:1 ; côté agents, compteurs cliquables, file d'attente triée du plus ancien au plus récent, arbre du premier choix pré-sélectionné, lien « Aller au contenu », courriers repliables.
- Un seul sujet par écran, barre de progression « Étape 2 sur 4 », bouton Retour qui conserve la saisie.
- Validation au fil de l'eau, messages en clair qui disent quoi faire, jamais « champ invalide ».
- **Aucune pièce à joindre** : le formulaire ne reçoit aucun fichier (la copie du livret de famille, prévue au départ, a été supprimée : l'état civil vérifie la naissance avec ses outils). Un justificatif de domicile est présenté au retrait du certificat.
- Pas de nom de famille sur le certificat, pas de photo de l'enfant.
- Anti-spam sans captcha pénible : champ piège invisible + limitation du nombre d'envois par adresse IP.
- Accessibilité (RGAA) : libellés explicites, contrastes, navigation clavier, alternatives textuelles des photos d'arbres, taille de police ≥ 16 px.
- Iframe : hauteur automatique, aucun défilement interne. Lien de secours « Ouvrir le formulaire dans une nouvelle page ».

---

## 3. Écrans et messages de retour

### Confirmation à l'écran
« Merci {prénom du parent} ! Votre demande pour {prénom de l'enfant} est bien enregistrée sous la référence **PAR-2026-0042**. Un e-mail de confirmation vient de vous être envoyé. Les services municipaux étudient votre demande. Vous serez prévenu(e) dès que le certificat sera prêt à la mairie. »

### E-mail 1 – Accusé de réception (immédiat, personnalisé)
**Objet :** Bienvenue à {prénom de l'enfant} : votre demande de parrainage est bien reçue

> Bonjour {prénom du parent},
>
> Toutes nos félicitations pour la naissance de {prénom de l'enfant} !
> Nous avons bien enregistré votre demande de parrainage d'un arbre (référence {PAR-xxxx}).
>
> **Votre choix :** {essence 1} (et {essence 2} en second choix)
>
> **Et maintenant ?**
> 1. Nos services vérifient votre demande et choisissent l'arbre qui accompagnera {prénom}.
> 2. Vous recevrez un nouvel e-mail dès que le certificat de parrainage sera prêt.
> 3. Vous viendrez le retirer à l'accueil de la mairie. Pensez à apporter un justificatif de domicile.
>
> Une question ? {mail/téléphone du service} – {horaires d'accueil}.
> Au plaisir de voir grandir {prénom} et son arbre,
> La Ville de Corbas

### E-mail 2 – Certificat prêt (envoyé quand l'agent valide)
**Objet :** Le certificat de parrainage de {prénom} est prêt

> L'arbre de {prénom} a été choisi : c'est un {essence} ! Son certificat vous attend à l'accueil de la mairie de Corbas, {adresse}, aux horaires suivants : {horaires}. Il est tenu à votre disposition pendant {x} mois. Apportez un justificatif de domicile.

### E-mail 3 – Liste d'attente
> Toutes les places de la campagne {nom} sont attribuées. Votre demande est placée en liste d'attente (rang {n}). Vous serez prévenu(e) dès que de nouveaux arbres seront plantés.

### E-mail 4 – Demande non retenue
> Nous ne pouvons pas donner suite à votre demande pour la raison suivante : {motif}. {Alternative proposée}. Pour toute question : {contact}.

### E-mail 5 – Complément nécessaire
> Pour finaliser votre demande, il nous manque : {précision}. Répondez simplement à ce message.

### E-mail interne à l'agent
> Objet : Nouvelle demande de parrainage {ref} à traiter (ou « (liste d'attente) » quand il n'y a plus d'arbre libre)
> Référence, date de réception, essence souhaitée, nombre de demandes à traiter en ce moment, [Ouvrir la demande].
>
> **Aucune donnée personnelle** dans ce message (ni nom, ni e-mail, ni adresse) : elles se consultent dans le back-office.

**Qui est prévenu ?** Une ou plusieurs adresses, au choix : le réglage « Notifications » de l'administrateur (modifiable sans redémarrage, avec un bouton « Envoyer un message de test »), sinon la variable `NOTIFICATION_EMAILS` du serveur (plusieurs adresses séparées par des virgules), sinon tous les comptes du back-office. Une boîte de service commune (par exemple accueil@…) convient très bien.

---

## 4. Le certificat (PDF A4 paysage, généré pour impression)

Contenu, de haut en bas :
1. **En-tête** : logo de la ville à gauche, logo « Mon arbre à Corbas » à droite, titre « Certificat de parrainage » au centre.
2. **Phrase centrale** : « La Ville de Corbas certifie que l'arbre n° **COR-2026-014** est parrainé par **{Prénom}**, né(e) le {date}. »
3. **Bloc arbre** : photo de l'essence, nom courant et latin, date de plantation.
4. **Texte de l'essence** (champ de la fiche essence) :
   - *Ce qu'il représente* (ex. « Le chêne symbolise la force et la longévité… »).
   - *Ses caractéristiques* (hauteur adulte, floraison, feuillage, intérêt pour la biodiversité).
   - *Son rôle à Corbas* (ombre, fraîcheur, abri pour les oiseaux).
5. **Où le trouver** : nom du lieu, adresse, et **carte de Corbas** avec le repère de l'arbre (numéroté), fond OpenStreetMap. Mention de l'identifiant et des coordonnées GPS. Un QR code mène à la page de l'arbre sur le site (facultatif).
6. **Rappel des conditions** (en petit) : l'arbre demeure un bien communal.
7. **Signature** : le maire (image de signature), cachet, date de remise, numéro de parrainage.

Charte : couleurs de la ville, une teinte d'accent par essence, polices lisibles, impression noir et blanc lisible.

---

## 5. Règles de gestion et cas limites

| Cas | Comportement |
|---|---|
| Naissance > 12 mois | **Bloquant** : le formulaire n'envoie pas la demande (contrôle à l'écran et côté serveur). Message : « Le parrainage doit être demandé avant les 12 mois de l'enfant. Contactez l'accueil si vous pensez être dans un cas particulier. » |
| Date de naissance dans le futur ou invalide | Bloquant. |
| Enfant « domicilié à Corbas » | Bloquant si l'adresse n'est pas à Corbas (69960). L'enfant né à Corbas peut habiter ailleurs. |
| Naissance avant le vote de la délibération | Acceptée si l'enfant a moins de 12 mois à la date de la demande. Aucune autre date butoir. |
| Doublon (même prénom, même nom, même date de naissance) | Bloquant, même avec une autre adresse e-mail. |
| Jumeaux / fratrie | Une demande par enfant (prénoms différents). Après l'envoi, le bouton « Faire une demande pour un autre enfant » reprend les coordonnées du parent. |
| Essence épuisée entre le choix et la validation | L'agent affecte le second choix, sinon contacte la famille. |
| Stock à 0 | Passage **automatique** en « liste d'attente ». Le stock restant = arbres libres de la campagne − demandes en cours de traitement (Reçue, Complément demandé) : une demande en attente de validation réserve une place, sinon le formulaire accepterait plus de familles que d'arbres. Un refus ou une annulation rend la place. |
| Liste d'attente servie plus tard | L'agent peut affecter n'importe quel arbre libre, y compris celui d'une campagne ultérieure. |
| Arbre mort ou abattu | Fiche arbre passée à « Remplacé » ; l'agent affecte un nouvel arbre ; un nouveau certificat est imprimé avec la mention « remplace le n° ». |
| Certificat non retiré | Rappel automatique à 30 jours, puis archivage à {x} mois. *(Non réalisé dans le prototype.)* |
| Demande de suppression RGPD | Fonction d'anonymisation réservée à l'administrateur : identité et courriers de la famille sont effacés ; la fiche arbre reste. |
| Refus ou annulation d'une demande | L'arbre est libéré. La famille peut redéposer une demande. |
| Courrier qui ne part pas (SMTP en panne) | L'envoi se fait en arrière-plan : la famille n'attend pas. Le courrier reste dans le back-office avec la raison de l'échec et un bouton « Renvoyer ». |
| Envois en rafale depuis une même adresse IP | 10 demandes enregistrées par heure au maximum (réglable). Les saisies refusées par le formulaire ne comptent pas. 10 mots de passe faux : connexion bloquée 15 minutes. |
| Heure du serveur | Toutes les dates sont calculées à l'heure de Paris (un serveur Docker est à l'heure UTC : une naissance du jour aurait été refusée entre minuit et 2 h). |

**Statuts d'une demande :** Reçue → Validée (arbre affecté) → Certificat imprimé → Remis. Branches : Complément demandé, Liste d'attente, Refusée, Annulée. Le serveur n'accepte que les transitions prévues (par exemple « Remis » seulement après « Certificat imprimé »), même si un formulaire est modifié à la main.

---

## 6. Suivi : base de données et export Excel

Stockage principal en base (SQLite ou MySQL), avec **export Excel (.xlsx) en un clic** et filtres par campagne.

**Table « Parrainages »**
| Colonne | Exemple |
|---|---|
| Référence | PAR-2026-0042 |
| Date de la demande | 12/11/2026 |
| Campagne | Automne 2026 |
| Statut | Remis |
| Prénom enfant / Nom enfant | Léa / Martin |
| Date de naissance | 03/09/2026 |
| Lien avec Corbas | Né(e) à Corbas |
| Parent (nom, prénom, qualité) | Martin Claire, mère |
| E-mail / Téléphone | |
| Adresse postale | |
| Essence souhaitée 1 / 2 | Chêne vert / Tilleul |
| Opt-in bénévolat entretien | Oui |
| Arbre affecté (ID) | COR-2026-014 |
| Agent validateur / date | |
| Date d'impression / de remise | |
| Notes internes | |

**Table « Arbres »**
| Colonne | Exemple |
|---|---|
| ID | COR-2026-014 |
| Campagne | Automne 2026 |
| Essence | Chêne vert (Quercus ilex) |
| Lieu / adresse | Parc de la Mairie |
| Latitude / Longitude | |
| Date de plantation | |
| Statut | Parrainé / Libre / Remplacé |
| Référence du parrainage | PAR-2026-0042 |
| Observations (santé, entretien) | |

**Table « Essences »** et **table « Campagnes »** : voir le paramétrage §1.

**Tableau de bord (accueil de l'agent) :** demandes à traiter, arbres libres par essence, certificats à imprimer, certificats non retirés.

---

## 7. Architecture proposée (application indépendante)

- Application web autonome hébergée à part, par exemple `parrainage.corbas.fr`.
- **Hébergement décidé :** un conteneur Docker (application + base SQLite) sur un serveur géré par vous, derrière Caddy pour le HTTPS. Un volume unique à sauvegarder chaque nuit, avec un export Excel automatique en seconde copie.
- **Stock :** l'application n'offre des parrainages que dans la limite des **arbres à planter** déclarés par l'administrateur pour la campagne. Le formulaire ne propose jamais plus d'arbres que le stock restant (arbres libres moins demandes en cours), et seules les essences ayant encore une place sont sélectionnables.
- **Sites de plantation :** les cinq sites proposés par le responsable des espaces verts sont une étude, pas un engagement. Ils ne figurent dans l'application que comme données d'exemple. Seul le stock saisi par l'administrateur fait foi. Le plan de plantation de l'automne 2026 transmis ensuite par le service des espaces verts (24 essences, 9 sites, 41 arbres, avec variété et taille) se charge avec `plantation.py` (`python plantation.py --help`).
- Le site WordPress contient une page avec `<iframe src="https://parrainage.corbas.fr/formulaire">` (ou un bouton de redirection).
- Back-office protégé par authentification (agents) avec deux rôles : **agent** (traite les demandes, imprime les certificats, consulte les courriers, exporte) et **administrateur** (en plus : campagnes, essences, arbres, comptes utilisateurs, anonymisation). Les comptes se créent dans l'application (menu Utilisateurs) ; chacun change son mot de passe (10 caractères minimum). Sessions limitées à 8 heures.
- Envoi des mails via le SMTP de la ville (SPF/DKIM configurés pour éviter les spams).
- Génération PDF côté serveur, carte statique avec fond OpenStreetMap (mention « © les contributeurs d'OpenStreetMap »).
- HTTPS, sauvegarde quotidienne. L'agent qui a validé une demande est enregistré sur la fiche (pas de journal détaillé de toutes les actions dans le prototype).
- Sécurité : liens de confirmation signés (la page « merci » d'une famille ne peut pas être devinée), jeton CSRF sur le back-office, en-tête CSP (`frame-ancestors`, `form-action`…), export Excel protégé contre l'injection de formules, limitation des envois et des tentatives de connexion, clé de session générée et conservée dans le volume.
- Points d'attention de l'iframe : cookies de session, redimensionnement automatique (postMessage), en-tête `frame-ancestors` limité au domaine de la mairie.

---

## 8. Points à trancher avant la mise en service

1. ~~Naissances antérieures au vote~~ : tranché. Seule la règle des 12 mois s'applique.
2. **Durée de conservation** : tranché, pour la durée de vie de l'arbre. Prévoir la mention RGPD correspondante, l'anonymisation quand l'arbre disparaît (ou à la demande de la famille) et le nom du DPO / contact à afficher.
3. **Domiciliation** : la délibération couvre « né sur le territoire de la commune **ou** y domicilié ». Né à Corbas mais domicilié ailleurs : accepté ? (C'est ce que prévoit le texte.) Les naissances ont lieu dans une maternité hors commune : prévoir une formulation claire.
4. ~~Hébergement~~ : tranché (Docker sur votre serveur). Reste à fixer le nom de domaine et la personne qui assure la maintenance.
5. **Liste des essences** et **sites de plantation** de la campagne 2026 (une vingtaine d'arbres), avec les photos et textes de présentation.
6. **Charte graphique** : l'interface reprend celle de corbas.fr (police Roboto, bleu #005b94, titres légers avec un mot en gras, boutons en pilule). Le Maire est Benoit Eraclas (signature du certificat). Le logo de la ville (PNG à fond transparent, 170 × 47 px, fourni par la mairie) est livré avec l'application (`assets/logo-ville.png`) : il figure sur le certificat, la page de connexion et le formulaire hors iframe. Une version plus grande (au moins 600 px de large, ou vectorielle) donnerait une impression plus nette : il suffit de la déposer sous le nom `logo.png` dans le volume de données, sans redémarrage.
7. **Retrait du certificat** : l'original du livret de famille n'est plus demandé (l'état civil vérifie la naissance) ; seul le justificatif de domicile figure dans les e-mails et la page de confirmation. À confirmer avec l'accueil. La mention RGPD du formulaire, qui indique la vérification par l'état civil, est à faire valider par le DPO.
8. **Corrections de la délibération** : « d'ores et déjà à disposition » (et non « d'ores et déjà »), et une virgule finale à remplacer par un point après « concernés ».

---

## 9. Suite possible

1. ~~Maquettes~~ et ~~prototype fonctionnel~~ : réalisés (dossier `parrainage/`, 63 tests automatiques, image Docker testée avec la vraie carte OpenStreetMap).
2. Intégration iframe : vérifiée avec une page d'hébergement simulée (hauteur automatique, remontée de page à chaque étape). Reste à essayer sur la vraie page WordPress.
3. Envoi réel des e-mails : à tester avec le SMTP de la ville.
4. Rappel des certificats non retirés, pointage des arbres sur une carte, photos des essences.
