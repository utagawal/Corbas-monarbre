#!/usr/bin/env bash
# Mise à jour de « Mon arbre à Corbas » depuis le serveur.
#
#   ./deploy/mettre-a-jour.sh              met à jour : sauvegarde de la base, récupération du code, reconstruction de l'image,
#                                          redémarrage, contrôle, retour à la version précédente si le contrôle échoue
#   ./deploy/mettre-a-jour.sh --verifier   ne change rien : indique ce qui est disponible
#   ./deploy/mettre-a-jour.sh --forcer     reconstruit même sans nouveau code (correctifs de l'image Python de base)
#
# Ce qui est mis à jour : le code (git pull), l'image Python de base avec ses correctifs système (docker build --pull) et les
# paquets Python aux versions fixées dans requirements.txt. Une nouvelle version d'un paquet s'adopte en modifiant
# requirements.txt dans le dépôt, après essai : --verifier liste ce qui existe.
#
# Réglages (variables d'environnement, facultatives) :
#   MONARBRE_SERVICES   services Compose à relancer. Par défaut : « app » si docker-compose.override.yml existe (derrière votre
#                       nginx), sinon tous les services (avec le Caddy du projet).
#   MONARBRE_PULL=0     ne pas chercher une image de base plus récente.
#
# Automatique (cron, par exemple chaque lundi à 4 h 30) : voir le README. Code de sortie 0 si tout va bien, 1 en cas d'échec.
set -euo pipefail

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
echec() { log "ERREUR : $*" >&2; exit 1; }

aide() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

MODE=maj
FORCER=0
for arg in "$@"; do
  case "$arg" in
    --verifier) MODE=verifier ;;
    --forcer) FORCER=1 ;;
    -h|--aide|--help) aide; exit 0 ;;
    *) echec "option inconnue : $arg (voir --aide)" ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."
RACINE=$(pwd)

command -v git >/dev/null 2>&1 || echec "git est introuvable"
command -v docker >/dev/null 2>&1 || echec "docker est introuvable"
docker compose version >/dev/null 2>&1 || echec "le plugin « docker compose » est introuvable"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || echec "$RACINE n'est pas un dépôt git (le projet doit être installé avec git clone)"
[ -f .env ] || echec "fichier .env introuvable dans $RACINE : copier .env.example en .env et le compléter"

if [ -n "${MONARBRE_SERVICES+x}" ]; then
  SERVICES="$MONARBRE_SERVICES"
elif [ -f docker-compose.override.yml ]; then
  SERVICES="app"   # derrière nginx : le Caddy du projet ne doit pas être lancé
else
  SERVICES=""      # tous les services (avec Caddy)
fi
PULL="--pull"
[ "${MONARBRE_PULL:-1}" = "0" ] && PULL=""

app_en_marche() { [ -n "$(docker compose ps -q app 2>/dev/null)" ]; }

# Même contrôle que le HEALTHCHECK du Dockerfile : la page /sante répond. Jusqu'à 90 secondes.
attendre_application() {
  local i
  for i in $(seq 1 30); do
    if docker compose exec -T app python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/sante',timeout=3)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

git fetch --quiet origin || echec "git fetch a échoué (réseau ? accès au dépôt ?)"
AMONT=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) \
  || echec "la branche courante ne suit aucune branche distante (git checkout main ?)"
AVANT=$(git rev-parse HEAD)
NOUVEAUX=$(git rev-list --count "HEAD..$AMONT")
MODIFIES=$(git status --porcelain --untracked-files=no)

# ---------------------------------------------------------------- vérification seule
if [ "$MODE" = "verifier" ]; then
  log "Version installée : $(git log -1 --format='%h %s')"
  if [ "$NOUVEAUX" -gt 0 ]; then
    log "$NOUVEAUX nouveauté(s) disponible(s) :"
    git log --format='  %h %s' "HEAD..$AMONT"
  else
    log "Code à jour."
  fi
  [ -z "$MODIFIES" ] || log "ATTENTION : des fichiers suivis par git ont été modifiés à la main (la mise à jour s'arrêtera) :
$MODIFIES"
  if app_en_marche; then
    PAQUETS=$(docker compose exec -T app pip list --outdated --disable-pip-version-check --no-cache-dir 2>/dev/null || true)
    if [ -n "$PAQUETS" ]; then
      log "Paquets Python plus récents que ceux installés (ceux de requirements.txt sont fixés : à adopter après essai ; les autres suivent la dernière version à chaque reconstruction) :"
      printf '%s\n' "$PAQUETS" | sed 's/^/  /'
    else
      log "Paquets Python : rien de plus récent (ou liste indisponible)."
    fi
  else
    log "L'application ne tourne pas : paquets non vérifiés."
  fi
  exit 0
fi

# ---------------------------------------------------------------- mise à jour
[ -z "$MODIFIES" ] || echec "des fichiers suivis par git ont été modifiés à la main : la mise à jour ne les écrase pas. Voir : git status
$MODIFIES"

# un seul passage à la fois (cron, lancement manuel) : verrou par dossier, nettoyé à la sortie
VERROU="${TMPDIR:-/tmp}/monarbre-maj.lock"
if ! mkdir "$VERROU" 2>/dev/null; then
  if kill -0 "$(cat "$VERROU/pid" 2>/dev/null)" 2>/dev/null; then
    log "Une mise à jour est déjà en cours : rien à faire."
    exit 0
  fi
  rm -rf "$VERROU"
  mkdir "$VERROU"
fi
echo $$ > "$VERROU/pid"
trap 'rm -rf "$VERROU"' EXIT

if [ "$NOUVEAUX" -eq 0 ] && [ "$FORCER" -eq 0 ]; then
  log "Déjà à jour ($(git log -1 --format='%h %s')). --forcer reconstruit tout de même l'image (correctifs de l'image de base)."
  exit 0
fi

# fait avant toute modification : de quoi revenir en arrière
IMAGE_APP=$(docker compose config --images app 2>/dev/null | head -n 1 || true)
CONTENEUR=$(docker compose ps -q app 2>/dev/null || true)
IMAGE_AVANT=""
[ -z "$CONTENEUR" ] || IMAGE_AVANT=$(docker inspect --format '{{.Image}}' "$CONTENEUR" 2>/dev/null || true)
# l'image en service reçoit un nom à elle (« avant-maj ») : la reconstruction ne peut pas la faire disparaître
DEPOT="${IMAGE_APP%%:*}"
IMAGE_SAUVEE=""
if [ -n "$IMAGE_AVANT" ] && [ -n "$DEPOT" ] && docker tag "$IMAGE_AVANT" "$DEPOT:avant-maj" 2>/dev/null; then
  IMAGE_SAUVEE="$DEPOT:avant-maj"
fi
RECREE=0

if app_en_marche; then
  log "Sauvegarde de la base avant mise à jour…"
  mkdir -p sauvegardes
  chmod 700 sauvegardes
  FICHIER="sauvegardes/avant-maj-$(date +%F-%H%M).db"
  docker compose exec -T app python -c "import sqlite3;s=sqlite3.connect('/data/parrainage.db');d=sqlite3.connect('/data/sauvegarde.db');s.backup(d)" \
    || echec "la sauvegarde de la base a échoué : rien n'a été modifié"
  docker compose cp app:/data/sauvegarde.db "$FICHIER" || echec "la copie de la sauvegarde a échoué : rien n'a été modifié"
  docker compose exec -T app rm -f /data/sauvegarde.db
  chmod 600 "$FICHIER"
  # on garde les 5 dernières sauvegardes d'avant mise à jour (elles contiennent des données personnelles)
  { ls -1t sauvegardes/avant-maj-*.db 2>/dev/null | tail -n +6 | while read -r ancienne; do rm -f "$ancienne"; done; } || true
  log "Sauvegarde : $FICHIER"
else
  log "L'application ne tourne pas : pas de sauvegarde (première installation ?)."
fi

revenir_en_arriere() {
  log "Retour à la version précédente ($(git rev-parse --short "$AVANT"))…"
  git reset --hard --quiet "$AVANT"
  if [ "$RECREE" -eq 1 ]; then
    # l'ancienne image est remise en service ; à défaut, on reconstruit depuis l'ancien code (déjà rétabli ci-dessus)
    if [ -n "$IMAGE_SAUVEE" ] && docker tag "$IMAGE_SAUVEE" "$DEPOT:latest" && docker compose up -d --no-build $SERVICES; then
      :
    else
      log "L'ancienne image n'est pas disponible : reconstruction depuis l'ancien code…"
      docker compose up -d --build $SERVICES || true
    fi
    if attendre_application; then
      [ -z "$IMAGE_SAUVEE" ] || docker rmi "$IMAGE_SAUVEE" >/dev/null 2>&1 || true
      log "Version précédente rétablie et en marche."
    else
      log "ATTENTION : la version précédente ne répond pas non plus. Voir : docker compose logs app"
    fi
  fi
}

if [ "$NOUVEAUX" -gt 0 ]; then
  log "Récupération du code ($NOUVEAUX nouveauté(s))…"
  git merge --ff-only --quiet "$AMONT" || echec "le code local et le dépôt ont divergé : rien n'a été modifié. Voir : git status"
  git log --format='  %h %s' "$AVANT..HEAD"
fi

log "Reconstruction de l'image${PULL:+ (avec la dernière image Python de base)}…"
# shellcheck disable=SC2086
if ! docker compose build $PULL $SERVICES; then
  revenir_en_arriere
  echec "la reconstruction a échoué : l'application n'a pas été touchée"
fi

log "Redémarrage…"
RECREE=1
# shellcheck disable=SC2086
if ! docker compose up -d $SERVICES; then
  revenir_en_arriere
  echec "le redémarrage a échoué"
fi

log "Contrôle de l'application…"
if ! attendre_application; then
  docker compose logs --tail 20 app 2>&1 | sed 's/^/  | /' || true
  revenir_en_arriere
  echec "la nouvelle version ne répond pas sur /sante : retour à la version précédente"
fi

# l'ancienne image n'est plus utile : on retire son nom de secours (et l'image avec, si plus rien ne l'utilise)
if [ -n "$IMAGE_SAUVEE" ]; then docker rmi "$IMAGE_SAUVEE" >/dev/null 2>&1 || true; fi
log "Mise à jour terminée : $(git log -1 --format='%h %s')"
