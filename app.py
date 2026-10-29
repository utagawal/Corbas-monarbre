"""« Mon arbre à Corbas » (Un enfant, un arbre) : formulaire de parrainage, back-office, certificat PDF, export Excel."""
import io
import json
import math
import mimetypes
import os
import re
import secrets
import smtplib
import sqlite3
import sys
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, session, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from PIL import Image, ImageOps
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import certificat

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
DB_PATH = os.path.join(DATA, "parrainage.db")
os.makedirs(DATA, exist_ok=True)


def cle_secrete():
    """SECRET_KEY de l'environnement, sinon une clé aléatoire conservée dans le volume de données."""
    k = os.environ.get("SECRET_KEY")
    if k:
        return k
    chemin = os.path.join(DATA, "secret.key")
    try:
        with open(chemin) as f:
            k = f.read().strip()
    except FileNotFoundError:
        k = ""
    if not k:
        k = secrets.token_hex(32)
        with open(chemin, "w") as f:
            f.write(k)
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
    return k


app = Flask(__name__)
app.secret_key = cle_secrete()
if os.environ.get("TRUST_PROXY", "0") == "1":  # derrière Caddy : vraie adresse IP du visiteur, schéma https
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def normaliser_prefixe(valeur):
    """« monarbre », « /monarbre » ou « /monarbre/ » deviennent « /monarbre » ; vide : pas de préfixe."""
    morceau = (valeur or "").strip().strip("/")
    return "/" + morceau if morceau else ""


class Prefixe:
    """Application servie sous un sous-chemin d'un domaine partagé (par exemple maps.utagawavtt.com/monarbre).
    Le serveur web retire le préfixe avant de transmettre la requête ; l'application le remet dans toutes les adresses
    qu'elle fabrique (liens, formulaires, redirections)."""

    def __init__(self, wsgi, prefixe):
        self.wsgi, self.prefixe = wsgi, prefixe

    def __call__(self, environ, start_response):
        environ["SCRIPT_NAME"] = self.prefixe + environ.get("SCRIPT_NAME", "")
        return self.wsgi(environ, start_response)


URL_PREFIX = normaliser_prefixe(os.environ.get("URL_PREFIX"))
if URL_PREFIX:
    app.wsgi_app = Prefixe(app.wsgi_app, URL_PREFIX)
LIVRETS = os.path.join(DATA, "livrets")
os.makedirs(LIVRETS, exist_ok=True)
TAILLE_MAX = 5 * 1024 * 1024
app.config.update(MAX_CONTENT_LENGTH=TAILLE_MAX + 512 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("HTTPS", "0") == "1",
                  # nom et chemin propres : sur un domaine partagé avec d'autres applications, le cookie ne se mélange pas aux leurs
                  SESSION_COOKIE_NAME="monarbre_session", SESSION_COOKIE_PATH=URL_PREFIX or "/")

MAIRIE = {
    "nom": os.environ.get("MAIRIE_NOM", "Ville de Corbas"),
    "adresse": os.environ.get("MAIRIE_ADRESSE", "Mairie de Corbas (adresse à compléter)"),
    "horaires": os.environ.get("MAIRIE_HORAIRES", "horaires d'accueil à compléter"),
    "contact": os.environ.get("MAIRIE_CONTACT", "contact@exemple.fr"),
    "maire": os.environ.get("MAIRIE_MAIRE", "Benoit Eraclas"),
    "site": os.environ.get("MAIRIE_SITE", "https://corbas.fr"),
    "dpo": os.environ.get("MAIRIE_DPO", "contact@exemple.fr"),
}
# Nom du dispositif : il est inscrit dans le logo livré avec l'application (static/mon-arbre-a-corbas.svg), il ne se règle donc pas par une variable.
DISPOSITIF = {"nom": "Mon arbre à Corbas", "devise": "Un enfant, un arbre"}


def ancetres(valeur):
    """Liste des sites autorisés à intégrer le formulaire. Tolère 'self' écrit sans apostrophes (fichier .env)."""
    out = []
    for t in valeur.replace(",", " ").split():
        t = t.strip("'\"")
        out.append(f"'{t}'" if t in ("self", "none") else t)
    return " ".join(out) or "'self'"


FRAME_ANCESTORS = ancetres(os.environ.get("FRAME_ANCESTORS", "'self' https://corbas.fr https://www.corbas.fr https://ville-corbas.fr https://www.ville-corbas.fr"))
LIMITE_ENVOIS = int(os.environ.get("RATE_LIMIT", 10))  # demandes enregistrées par heure et par adresse IP

STATUTS = ["Reçue", "Complément demandé", "Liste d'attente", "Validée", "Certificat imprimé", "Remis",
           "Refusée", "Annulée"]
ACTIFS = ("Reçue", "Complément demandé", "Liste d'attente", "Validée", "Certificat imprimé", "Remis")
EN_COURS = ("Reçue", "Complément demandé")  # demandes qui attendent un arbre : elles « réservent » une place
AVEC_ARBRE = ("Validée", "Certificat imprimé")
# Statuts dans lesquels chaque action est permise (le serveur refuse le reste, même si le formulaire a été modifié).
AUTORISE = {
    "valider": ("Reçue", "Complément demandé", "Liste d'attente", "Validée", "Certificat imprimé"),
    "attente": ("Reçue", "Complément demandé", "Validée", "Certificat imprimé"),
    "refuser": ("Reçue", "Complément demandé", "Liste d'attente", "Validée", "Certificat imprimé"),
    "complement": ("Reçue", "Complément demandé", "Liste d'attente"),
    "remis": ("Certificat imprimé",),
    "annuler": ACTIFS,
    "notes": tuple(STATUTS), "supprimer_livret": tuple(STATUTS), "restaurer_livret": tuple(STATUTS),
    "anonymiser": tuple(STATUTS),
}
STATUTS_ARBRE = ("libre", "parraine", "remplace")

SCHEMA = """
CREATE TABLE IF NOT EXISTS campagnes(id INTEGER PRIMARY KEY, nom TEXT NOT NULL, annee INTEGER NOT NULL,
  ouverture TEXT, fermeture TEXT, ouverte INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS essences(id INTEGER PRIMARY KEY, nom TEXT NOT NULL, latin TEXT, resume TEXT,
  symbole TEXT, caracteristiques TEXT, role TEXT, couleur TEXT DEFAULT '#2e7d32', photo_url TEXT, actif INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS arbres(id INTEGER PRIMARY KEY, code TEXT UNIQUE, campagne_id INTEGER REFERENCES campagnes(id),
  essence_id INTEGER REFERENCES essences(id), lieu TEXT, adresse TEXT, lat REAL, lon REAL, annee_plantation INTEGER,
  date_plantation TEXT, statut TEXT DEFAULT 'libre', observations TEXT, variete TEXT, taille TEXT);
CREATE TABLE IF NOT EXISTS parrainages(id INTEGER PRIMARY KEY, ref TEXT UNIQUE, created_at TEXT, campagne_id INTEGER,
  statut TEXT, enfant_prenom TEXT, enfant_nom TEXT, naissance TEXT, lien TEXT, parent_qualite TEXT, parent_nom TEXT,
  email TEXT, tel TEXT, adresse TEXT, cp TEXT, ville TEXT, essence1_id INTEGER, essence2_id INTEGER, benevolat INTEGER,
  hors_delai INTEGER DEFAULT 0, arbre_id INTEGER, agent TEXT, valide_at TEXT, imprime_at TEXT, remis_at TEXT,
  motif TEXT, notes TEXT, anonymise INTEGER DEFAULT 0, livret TEXT, livret_supprime_at TEXT);
CREATE TABLE IF NOT EXISTS mails(id INTEGER PRIMARY KEY, created_at TEXT, destinataire TEXT, sujet TEXT, corps TEXT, envoye INTEGER, erreur TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, hash TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS parametres(cle TEXT PRIMARY KEY, valeur TEXT);
CREATE INDEX IF NOT EXISTS idx_parr_naissance ON parrainages(naissance);
CREATE INDEX IF NOT EXISTS idx_parr_arbre ON parrainages(arbre_id);
CREATE INDEX IF NOT EXISTS idx_arbres_camp ON arbres(campagne_id, statut);
"""
# colonnes ajoutées après la première version : migration des bases existantes
MIGRATIONS = (("parrainages", "livret"), ("parrainages", "livret_supprime_at"), ("mails", "erreur"), ("arbres", "variete"), ("arbres", "taille"))


# ---------------------------------------------------------------- temps (heure de Paris, pas celle du serveur)
try:
    TZ = ZoneInfo(os.environ.get("APP_TZ", "Europe/Paris"))
except ZoneInfoNotFoundError:
    TZ = None


def maintenant():
    return datetime.now(TZ).replace(tzinfo=None) if TZ else datetime.now()


def aujourdhui():
    return maintenant().date()


def now():
    return maintenant().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- base de données
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def q(sql, *a):
    return db().execute(sql, a).fetchall()


def q1(sql, *a):
    return db().execute(sql, a).fetchone()


def ex(sql, *a):
    cur = db().execute(sql, a)
    db().commit()
    return cur.lastrowid


def init_db(demo=False):
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")  # lectures et écritures simultanées sans blocage
    con.executescript(SCHEMA)
    for table, col in MIGRATIONS:
        if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
    if not con.execute("SELECT 1 FROM users").fetchone():
        mail = os.environ.get("ADMIN_EMAIL", "admin@corbas.local")
        pw = os.environ.get("ADMIN_PASSWORD")
        if not pw:
            pw = secrets.token_urlsafe(12)
            print(f"ATTENTION : ADMIN_PASSWORD n'est pas défini. Mot de passe généré pour {mail} : {pw}\n"
                  "Connectez-vous et changez-le (menu « Mon mot de passe »).", flush=True)
        con.execute("INSERT INTO users(email,hash,role) VALUES(?,?,?)", (mail.lower(), generate_password_hash(pw), "admin"))
    con.commit()
    if demo and not con.execute("SELECT 1 FROM campagnes").fetchone():
        seed_demo(con)
    con.close()


def seed_demo(con):
    """Données d'EXEMPLE : sites issus de l'étude du service espaces verts, non engageants."""
    con.execute("INSERT INTO campagnes(nom,annee,ouverture,fermeture,ouverte) VALUES('Automne 2026 (exemple)',2026,'2026-10-01','2027-06-30',1)")
    ess = [
        ("Chêne vert", "Quercus ilex", "Robuste, toujours vert", "Le chêne vert symbolise la force, la constance et la longévité : il peut vivre plusieurs siècles.",
         "Arbre de 10 à 20 m à feuillage persistant, très résistant à la sécheresse et à la chaleur.", "Il offre de l'ombre et un abri toute l'année aux oiseaux et aux insectes.", "#2e6b34"),
        ("Tilleul à petites feuilles", "Tilia cordata", "Parfumé, mellifère", "Le tilleul est l'arbre de la paix, de la douceur et du lien entre les générations.",
         "Arbre de 20 à 25 m. Ses fleurs, en juin, parfument l'air et nourrissent les abeilles.", "Il apporte une belle ombre fraîche en été et ses fleurs servent aux tisanes.", "#7a9a2e"),
        ("Cerisier à fleurs", "Prunus serrulata", "Floraison de printemps", "Son éclat éphémère rappelle la beauté de chaque instant et le renouveau du printemps.",
         "Arbre de 6 à 10 m, couvert de fleurs roses ou blanches au printemps.", "Il embellit les squares et attire les pollinisateurs dès les premiers beaux jours.", "#c2557a"),
        ("Érable champêtre", "Acer campestre", "Local et résistant", "L'érable champêtre représente l'adaptation et la générosité : il grandit presque partout.",
         "Arbre de 10 à 15 m, feuillage qui vire à l'or en automne, bien adapté au climat local.", "Il crée de l'ombre légère et nourrit la faune locale.", "#b8791f"),
        ("Charme commun", "Carpinus betulus", "Robuste et élégant", "Le charme évoque l'harmonie et l'attachement : son nom lui vient de la grâce de son port.",
         "Arbre de 15 à 20 m au feuillage dense, qui reste sur les branches une bonne partie de l'hiver.", "Il structure les parcs et offre refuge aux oiseaux.", "#3d6f6f"),
    ]
    for e in ess:
        con.execute("INSERT INTO essences(nom,latin,resume,symbole,caracteristiques,role,couleur) VALUES(?,?,?,?,?,?,?)", e)
    # coordonnées issues d'OpenStreetMap (école et avenue réelles) mais emplacement exact des arbres fictif
    sites = [("Abords du gymnase et de l'école Jean Jaurès", "Chemin de Grange Blanche, Corbas (exemple)", 45.66599, 4.90278, 2026, [1, 2, 4, 5], 8),
             ("Square de la crèche IAE", "Avenue de Corbetta, Corbas (exemple)", 45.66810, 4.89584, 2026, [3], 4)]
    n = 0
    for lieu, adr, lat, lon, an, ess_ids, nb in sites:
        for i in range(nb):
            n += 1
            e = ess_ids[i % len(ess_ids)]
            con.execute("INSERT INTO arbres(code,campagne_id,essence_id,lieu,adresse,lat,lon,annee_plantation) VALUES(?,?,?,?,?,?,?,?)",
                        (f"COR-2026-{n:03d}", 1, e, lieu, adr, lat + (i % 4) * 0.00012, lon + (i // 4) * 0.00015, an))
    con.commit()


# ---------------------------------------------------------------- utilitaires
def fr(d):
    if not d:
        return ""
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(d)


def frdt(d):
    """« 2026-10-29 00:08:54 » devient « 29/10/2026 à 00h08 » ; vide : un tiret."""
    if not d:
        return "–"
    try:
        return datetime.strptime(str(d)[:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y à %Hh%M")
    except ValueError:
        return str(d)


def latin_complet(latin, variete):
    """« Prunus serrulata » et « Kanzan » donnent « Prunus serrulata 'Kanzan' » (le nom de la variété cultivée s'écrit entre apostrophes)."""
    return " ".join(x for x in (latin, f"'{variete}'" if variete else "") if x)


app.jinja_env.filters["fr"] = fr
app.jinja_env.filters["frdt"] = frdt
app.jinja_env.filters["variete"] = lambda nom: f"'{nom}'" if nom else ""
app.jinja_env.globals["annee_defaut"] = lambda: aujourdhui().year


LIENS = ("Domicilié(e) à Corbas", "Né(e) à Corbas")
QUALITES = ("Mère", "Père", "Représentant légal")
EMAIL_RE = re.compile(r"^[^@\s<>\",;:]+@[^@\s<>\",;:]+\.[^@\s<>\",;:]{2,}$")
MSG_MOBILE = ("Indiquez votre numéro de mobile (06 ou 07…). Un numéro étranger commence par + suivi de l'indicatif du pays.")


def normaliser_mobile(saisie):
    """Numéro de mobile français (06 ou 07, avec ou sans +33) ou international (+ et 8 à 15 chiffres), mis en forme ; None si invalide."""
    brut = re.sub(r"[\s.()\-]", "", saisie or "")
    if not re.fullmatch(r"\+?\d+", brut):
        return None
    if brut.startswith("0033"):
        brut = "+33" + brut[4:]
    if brut.startswith("+33"):  # +33 6 12 34 56 78, ou +33 (0)6 12 34 56 78
        reste = brut[3:]
        brut = "0" + (reste[1:] if reste.startswith("0") else reste)
    elif brut.startswith("+"):  # autre pays : impossible de vérifier que c'est un mobile
        return brut if 8 <= len(brut) - 1 <= 15 else None
    if re.fullmatch(r"0[67]\d{8}", brut):
        return " ".join(brut[i:i + 2] for i in range(0, 10, 2))
    return None


COULEUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Longueurs maximales des champs du formulaire public (le HTML porte les mêmes valeurs dans maxlength)
LONGUEURS = {"enfant_prenom": 60, "enfant_nom": 80, "parent_nom": 100, "email": 120, "email2": 120, "tel": 25,
             "adresse": 150, "cp": 10, "ville": 60}
# Les arbres sont à Corbas : une latitude/longitude hors de ce cadre est presque sûrement une faute de frappe
CADRE_CORBAS = (45.53, 45.81, 4.70, 5.10)


def norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


def ligne(s):
    """Texte sur une seule ligne : retours à la ligne, tabulations et espaces multiples ramenés à un espace."""
    return " ".join((s or "").split())


def soigner_prenom(s):
    """« léa » ou « LÉA » deviennent « Léa » ; une saisie déjà soignée n'est pas touchée."""
    return s.title() if s and (s == s.lower() or s == s.upper()) else s


def mois_avant(d, n):
    m = d.year * 12 + d.month - 1 - n
    y, mo = divmod(m, 12)
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo])
    return date(y, mo + 1, day)


def date_ou_none(s):
    try:
        return date.fromisoformat(s).isoformat() if s else None
    except ValueError:
        raise ValueError(s)


def campagne_ouverte():
    t = aujourdhui().isoformat()
    return q1("SELECT * FROM campagnes WHERE ouverte=1 AND (ouverture IS NULL OR ouverture='' OR ouverture<=?) "
              "AND (fermeture IS NULL OR fermeture='' OR fermeture>=?) ORDER BY id DESC", t, t)


def stock_net(campagne_id):
    """(places restantes, {essence: arbres encore proposables}).

    Un arbre libre n'est plus proposé dès qu'une demande en cours (Reçue / Complément demandé) l'attend :
    sinon le formulaire accepterait plus de familles qu'il n'y a d'arbres. Les essences désactivées sont ignorées."""
    libres = {r["essence_id"]: r["n"] for r in q(
        "SELECT a.essence_id, COUNT(*) n FROM arbres a JOIN essences e ON e.id=a.essence_id "
        "WHERE a.campagne_id=? AND a.statut='libre' AND e.actif=1 GROUP BY a.essence_id", campagne_id)}
    attendent = {r["essence1_id"]: r["n"] for r in q(
        "SELECT essence1_id, COUNT(*) n FROM parrainages WHERE campagne_id=? AND arbre_id IS NULL "
        "AND statut IN ('Reçue','Complément demandé') GROUP BY essence1_id", campagne_id)}
    total = max(0, sum(libres.values()) - sum(attendent.values()))
    if not total:
        return 0, {}
    net = {e: n - attendent.get(e, 0) for e, n in libres.items()}
    return total, {e: n for e, n in net.items() if n > 0}


def prochain_numero(table, prefixe):
    """Plus grand numéro déjà utilisé + 1 (compter les lignes donnerait un doublon après une suppression)."""
    col = "ref" if table == "parrainages" else "code"
    n = 0
    for r in q(f"SELECT {col} c FROM {table} WHERE {col} LIKE ?", f"{prefixe}-%"):
        suite = r["c"].rsplit("-", 1)[-1]
        if suite.isdigit():
            n = max(n, int(suite))
    return n + 1


def ref_suivante():
    y = aujourdhui().year
    return f"PAR-{y}-{prochain_numero('parrainages', f'PAR-{y}'):04d}"


# ---------------------------------------------------------------- courriers
def smtp_actif():
    return bool(os.environ.get("SMTP_HOST"))


def _smtp(to, sujet, corps):
    m = EmailMessage()
    m["From"] = os.environ.get("SMTP_FROM", MAIRIE["contact"])
    m["To"], m["Subject"] = to, sujet
    m.set_content(corps)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587)), timeout=15) as s:
        if os.environ.get("SMTP_TLS", "1") == "1":
            s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(m)


def _envoyer(mid):
    """Envoi d'un courrier enregistré (dans un fil à part, avec sa propre connexion à la base)."""
    con = sqlite3.connect(DB_PATH, timeout=10)
    try:
        m = con.execute("SELECT destinataire, sujet, corps FROM mails WHERE id=?", (mid,)).fetchone()
        if not m:
            return
        try:
            _smtp(*m)
            con.execute("UPDATE mails SET envoye=1, erreur=NULL WHERE id=?", (mid,))
        except Exception as e:  # le courrier reste visible dans le back-office, avec la raison, et peut être renvoyé
            print("Échec SMTP :", e, file=sys.stderr, flush=True)
            con.execute("UPDATE mails SET envoye=0, erreur=? WHERE id=?", (str(e)[:300], mid))
        con.commit()
    finally:
        con.close()


def lancer_envoi(mid):
    threading.Thread(target=_envoyer, args=(mid,), daemon=True).start()


def send_mail(to, sujet, corps):
    """Enregistre le courrier puis l'envoie en arrière-plan : un serveur SMTP lent ne bloque ni la famille ni l'agent."""
    mid = ex("INSERT INTO mails(created_at,destinataire,sujet,corps,envoye) VALUES(?,?,?,?,0)", now(), to, sujet, corps)
    if smtp_actif():
        lancer_envoi(mid)


SIGN = f"\n\n{DISPOSITIF['nom']} – {MAIRIE['nom']}\n{MAIRIE['contact']}"
ATTENTE = ("Toutes les places de la campagne sont attribuées ou en cours d'attribution. Votre demande est placée en "
           "liste d'attente. Vous serez prévenu(e) dès que de nouveaux arbres seront plantés.")


LOGO_FOURNI = os.path.join(BASE, "assets", "logo-ville.png")  # logo de la ville livré avec l'application
LOGO_DISPOSITIF = os.path.join(BASE, "assets", "mon-arbre-a-corbas.png")  # logo « Mon arbre à Corbas » (version imprimée sur le certificat)


def chemin_logo():
    """Logo de la ville : MAIRIE_LOGO, sinon logo.png / logo.jpg déposé dans le dossier de données (pris en compte sans redémarrage),
    sinon le logo livré avec l'application. Déposer un fichier dans /data suffit donc à le remplacer."""
    voulu = os.environ.get("MAIRIE_LOGO")
    for c in ([voulu] if voulu else []) + [os.path.join(DATA, "logo" + e) for e in (".png", ".jpg", ".jpeg")] + [LOGO_FOURNI]:
        if c and os.path.isfile(c):
            return c
    return None


@app.context_processor
def logo_dans_les_pages():
    return {"logo_present": chemin_logo() is not None, "DISPOSITIF": DISPOSITIF}


@app.get("/logo")
def logo():
    chemin = chemin_logo()
    if not chemin:
        abort(404)
    with open(chemin, "rb") as fh:
        resp = Response(fh.read(), mimetype=mimetypes.guess_type(chemin)[0] or "image/png")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ---------------------------------------------------------------- photos
PHOTOS = os.path.join(BASE, "static", "photos")  # photos livrées avec l'application ; leurs mentions sont dans credits.json
PHOTOS_ENVOYEES = os.path.join(DATA, "photos")  # photos envoyées dans l'administration (volume de données) : elles passent avant les photos livrées
PHOTOS_AMBIANCE = {"hero-accueil": "Accueil du formulaire", "hero-merci": "Page de confirmation"}  # bandeaux que l'administrateur peut remplacer
BANDEAU = (1200, 400)
MAX_PIXELS = 50_000_000
os.makedirs(PHOTOS_ENVOYEES, exist_ok=True)


def slug(texte):
    s = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def noter_credit(nom):
    """Retient la mention d'une photo livrée qui s'affiche sur la page (elle figure en bas de page). Une photo remplacée par la mairie n'en a plus."""
    if "credits_livres" not in g:
        try:
            with open(os.path.join(PHOTOS, "credits.json"), encoding="utf-8") as fh:
                g.credits_livres = json.load(fh)
        except (OSError, ValueError):
            g.credits_livres = {}
    if nom in g.credits_livres:
        g.setdefault("credits", {})[nom] = g.credits_livres[nom]


def photo_envoyee_url(nom):
    fichier = os.path.join(PHOTOS_ENVOYEES, nom + ".jpg")
    return url_for("photo_envoyee", nom=nom, v=int(os.path.getmtime(fichier))) if os.path.isfile(fichier) else None


def photo(nom):
    """Adresse d'une photo : celle envoyée dans l'administration (bandeaux), sinon celle livrée avec l'application
    (static/photos/<nom>.jpg), sinon None : les pages restent belles sans photo."""
    if nom in PHOTOS_AMBIANCE and photo_envoyee_url(nom):
        return photo_envoyee_url(nom)
    if os.path.isfile(os.path.join(PHOTOS, nom + ".jpg")):
        noter_credit(nom)
        return url_for("static", filename=f"photos/{nom}.jpg")
    return None


def photo_essence(e):
    """Photo envoyée par l'administrateur, sinon celle livrée avec l'application sous le nom de l'essence (static/photos/essences/), sinon rien."""
    return photo_envoyee_url(f"essence-{e['id']}") or photo("essences/" + slug(e["nom"]))


app.jinja_env.globals["photo"] = photo
app.jinja_env.globals["credits_photos"] = lambda: list(g.get("credits", {}).values())


@app.get("/photos/<nom>.jpg")
def photo_envoyee(nom):
    if nom not in PHOTOS_AMBIANCE and not re.fullmatch(r"essence-\d+", nom):
        abort(404)
    try:
        with open(os.path.join(PHOTOS_ENVOYEES, nom + ".jpg"), "rb") as fh:
            resp = Response(fh.read(), mimetype="image/jpeg")
    except FileNotFoundError:
        abort(404)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def lire_photo(fichier):
    """Image envoyée, décodée par Pillow (le contenu fait foi, pas l'extension) et redressée ; None si elle est illisible ou démesurée."""
    try:
        img = Image.open(fichier.stream)
        if img.width * img.height > MAX_PIXELS:
            return None
        img.load()
        return ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None


def ecrire_photo(nom, img):
    """JPEG sans métadonnées, écrit de façon atomique."""
    chemin = os.path.join(PHOTOS_ENVOYEES, nom + ".jpg")
    img.save(chemin + ".tmp", "JPEG", quality=82, optimize=True)
    os.replace(chemin + ".tmp", chemin)


def retirer_photo(nom):
    try:
        os.remove(os.path.join(PHOTOS_ENVOYEES, nom + ".jpg"))
    except FileNotFoundError:
        pass


def mail_accuse(p, e1, e2, attente=False):
    pre = e1["nom"] + (f" (et {e2['nom']} en second choix)" if e2 else "")
    if attente:
        etape = ATTENTE
    else:
        etape = ("Nos services vérifient votre demande et choisissent l'arbre qui accompagnera "
                 f"{p['enfant_prenom']}.\nVous recevrez un nouvel e-mail dès que le certificat de parrainage sera prêt.")
    send_mail(p["email"], f"Bienvenue à {p['enfant_prenom']} : votre demande de parrainage est bien reçue",
              f"Bonjour {p['parent_nom']},\n\nToutes nos félicitations pour la naissance de {p['enfant_prenom']} !\n"
              f"Nous avons bien enregistré votre demande « {DISPOSITIF['nom']} » : le parrainage d'un arbre de la commune "
              f"(référence {p['ref']}).\n\n"
              f"Votre choix : {pre}\n\nEt maintenant ?\n{etape}\n"
              f"Le certificat sera à retirer à l'accueil de la mairie ({MAIRIE['adresse']}). Pensez à apporter "
              f"l'original du livret de famille et un justificatif de domicile.\n\nUne question ? {MAIRIE['contact']}"
              f"\n\nAu plaisir de voir grandir {p['enfant_prenom']} et son arbre," + SIGN)


# ---------------------------------------------------------------- notification des agents
MAX_DESTINATAIRES = 20


def lire_param(cle, defaut=""):
    r = q1("SELECT valeur FROM parametres WHERE cle=?", cle)
    return r["valeur"] if r and r["valeur"] is not None else defaut


def ecrire_param(cle, valeur):
    ex("INSERT INTO parametres(cle, valeur) VALUES(?, ?) ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur", cle, valeur)


def decouper_adresses(texte):
    """Adresses séparées par des retours à la ligne, des virgules, des points-virgules ou des espaces : minuscules, sans doublon."""
    vues, sortie = set(), []
    for a in re.split(r"[\s,;]+", texte or ""):
        a = a.strip().lower()
        if a and a not in vues:
            vues.add(a)
            sortie.append(a)
    return sortie


def destinataires_notification():
    """(adresses à prévenir, origine) : réglage de l'administrateur, sinon NOTIFICATION_EMAILS du serveur, sinon tous les comptes."""
    for origine, texte in (("reglage", lire_param("notification_emails")), ("serveur", os.environ.get("NOTIFICATION_EMAILS", ""))):
        adresses = [a for a in decouper_adresses(texte) if EMAIL_RE.match(a)]
        if adresses:
            return adresses, origine
    return [u["email"] for u in q("SELECT email FROM users ORDER BY id")], "comptes"


def lien_fiche(pid):
    base = os.environ.get("APP_URL", "").rstrip("/")
    if not base:
        return url_for("fiche", pid=pid, _external=True)
    if request.script_root and base.endswith(request.script_root):  # APP_URL écrite avec le sous-chemin : on ne le double pas
        base = base[:-len(request.script_root)]
    return base + url_for("fiche", pid=pid)


def notifier_agents(p, e1, attente):
    """Prévient les agents qu'une demande vient d'arriver. Aucune donnée personnelle dans le message : référence, essence, lien."""
    adresses, _ = destinataires_notification()
    if not adresses:
        return
    a_traiter = q1("SELECT COUNT(*) n FROM parrainages WHERE statut IN ('Reçue','Complément demandé')")["n"]
    if attente:
        sujet = f"Nouvelle demande de parrainage {p['ref']} (liste d'attente)"
        statut = "Liste d'attente : aucun arbre libre pour l'instant, rien à traiter tout de suite."
    else:
        sujet = f"Nouvelle demande de parrainage {p['ref']} à traiter"
        statut = "Reçue : à contrôler et à valider."
    corps = (f"Une nouvelle demande de parrainage vient d'être enregistrée.\n\nRéférence : {p['ref']}\n"
             f"Reçue le : {frdt(p['created_at'])}\nEssence souhaitée : {e1['nom']}\nStatut : {statut}\n\n"
             f"Demandes à traiter en ce moment : {a_traiter}\nOuvrir la demande : {lien_fiche(p['id'])}\n\n"
             "Ce message ne contient volontairement aucune donnée personnelle : elles se consultent dans le back-office.")
    for a in adresses:
        send_mail(a, sujet, corps)


# ---------------------------------------------------------------- en-têtes et limitation des envois
CSP_PAGE = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors ")


@app.after_request
def entetes(resp):
    admin = request.path.startswith("/admin")
    parents = "'none'" if admin else FRAME_ANCESTORS
    resp.headers["Content-Security-Policy"] = (CSP_PAGE if resp.mimetype == "text/html" else "frame-ancestors ") + parents
    if admin:
        resp.headers["X-Frame-Options"] = "DENY"
    if admin or request.path.startswith("/merci"):
        resp.headers["Cache-Control"] = "no-store"  # pages avec données personnelles : jamais en cache
    if os.environ.get("HTTPS", "0") == "1":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


_essais = {}
_verrou = threading.Lock()


def limite_atteinte(cle, maxi, fenetre):
    t = time.time()
    with _verrou:
        if len(_essais) > 5000:  # ménage : on oublie les adresses sans activité récente
            for k in [k for k, v in _essais.items() if not v or t - v[-1] > 3600]:
                del _essais[k]
        l = _essais[cle] = [x for x in _essais.get(cle, []) if t - x < fenetre]
        return len(l) >= maxi


def noter(cle):
    with _verrou:
        _essais.setdefault(cle, []).append(time.time())


# ---------------------------------------------------------------- saisie assistée des adresses
# Le navigateur n'appelle jamais un service extérieur : il interroge notre serveur, qui relaie la requête. Les familles ne sont pas
# pistées par un tiers, la politique de sécurité du site reste fermée, et les réponses sont mises en cache et limitées.
UA_API = "ParrainageCorbas/1.0 (formulaire de parrainage, mairie de Corbas)"
AUTOCOMPLETION = os.environ.get("AUTOCOMPLETION", "1") == "1"
ADRESSE_API = os.environ.get("ADRESSE_API", "https://data.geopf.fr/geocodage/search/")  # Base Adresse Nationale (service public)
LIEU_API = os.environ.get("LIEU_API", "https://photon.komoot.io/api/")  # Photon : données OpenStreetMap, lieux et équipements compris
INSEE_CORBAS = "69273"
BBOX_CORBAS = "4.86,45.64,4.935,45.69"  # lon min, lat min, lon max, lat max : la commune et ses abords immédiats (exclut Saint-Priest, Mions…)
LIMITE_API = 90  # suggestions par minute et par adresse IP
_cache_api = {}


def appel_json(url, params):
    r = requests.get(url, params=params, headers={"User-Agent": UA_API}, timeout=4)
    r.raise_for_status()
    return r.json()


def avec_cache(cle, fabrique, duree=3600):
    t = time.time()
    with _verrou:
        v = _cache_api.get(cle)
    if v and v[0] > t:
        return v[1]
    val = fabrique()  # une panne n'est jamais mise en cache
    with _verrou:
        if len(_cache_api) > 500:
            _cache_api.clear()
        _cache_api[cle] = (t + duree, val)
    return val


def chercher_adresses(texte, corbas):
    """Adresses postales (Base Adresse Nationale). corbas=True : seulement celles de Corbas (enfant domicilié à Corbas)."""
    params = {"q": texte, "limit": 6, "autocomplete": 1}
    if corbas:
        params["citycode"] = INSEE_CORBAS
    sortie = []
    for f in appel_json(ADRESSE_API, params).get("features", []):
        p, genre = f.get("properties", {}), f.get("properties", {}).get("type")
        if genre in ("housenumber", "street", "locality") and p.get("name"):
            sortie.append(dict(label=p.get("label") or p["name"], adresse=p["name"], cp=p.get("postcode") or "",
                               ville=p.get("city") or "", numero=genre == "housenumber"))
    return sortie


def chercher_lieux(texte, _corbas=False):
    """Lieux et adresses de Corbas avec leurs coordonnées GPS (Photon / OpenStreetMap), pour le stock d'arbres."""
    params = {"q": texte, "limit": 6, "lang": "fr", "lat": 45.667, "lon": 4.90, "bbox": BBOX_CORBAS}
    sortie, vus = [], set()
    for f in appel_json(LIEU_API, params).get("features", []):
        p, (lon, lat) = f.get("properties", {}), f["geometry"]["coordinates"][:2]
        rue = " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
        commune = " ".join(x for x in (p.get("postcode"), p.get("city")) if x)
        adresse = ", ".join(x for x in (rue, commune) if x)
        lieu = p.get("name") or rue
        label = lieu + (" – " + adresse if adresse else "")
        if lieu and label not in vus:
            vus.add(label)
            sortie.append(dict(label=label, lieu=lieu, adresse=adresse, lat=round(lat, 6), lon=round(lon, 6)))
    return sortie


def reponse_suggestions(nom, fabrique):
    if not AUTOCOMPLETION:
        return jsonify(resultats=[], indisponible=True)
    cle_ip = (nom, request.remote_addr or "?")
    if limite_atteinte(cle_ip, LIMITE_API, 60):
        return jsonify(resultats=[], indisponible=True), 429
    noter(cle_ip)
    texte, corbas = ligne(request.args.get("q"))[:100], request.args.get("corbas") == "1"
    if len(texte) < 3:
        return jsonify(resultats=[])
    try:
        return jsonify(resultats=avec_cache((nom, texte.lower(), corbas), lambda: fabrique(texte, corbas)))
    except Exception as e:  # service extérieur en panne ou lent : la saisie à la main reste possible
        print("Suggestions indisponibles :", e, file=sys.stderr, flush=True)
        return jsonify(resultats=[], indisponible=True)


@app.get("/api/adresse")
def api_adresse():
    return reponse_suggestions("adresse", chercher_adresses)


# ---------------------------------------------------------------- partie publique
def contexte_formulaire():
    camp = campagne_ouverte()
    if not camp:
        return dict(camp=None, MAIRIE=MAIRIE)
    total, net = stock_net(camp["id"])
    essences = [dict(e, dispo=net.get(e["id"], 0), photo=photo_essence(e)) for e in q("SELECT * FROM essences WHERE actif=1 ORDER BY nom")
                if total == 0 or net.get(e["id"])]
    return dict(camp=camp, essences=essences, total=total, attente=(total == 0), MAIRIE=MAIRIE, LONGUEURS=LONGUEURS,
                today=aujourdhui().isoformat(), min_naissance=mois_avant(aujourdhui(), 12).isoformat())


@app.get("/")
def formulaire():
    return render_template("form.html", v={}, errors={}, **contexte_formulaire())


def type_de_fichier(fichier):
    """Extension déduite du contenu réel du fichier (et non de son nom), ou None."""
    tete = fichier.stream.read(8)
    fichier.stream.seek(0, 2)
    taille = fichier.stream.tell()
    fichier.stream.seek(0)
    ext = (".pdf" if tete.startswith(b"%PDF") else ".jpg" if tete[:3] == bytes([0xFF, 0xD8, 0xFF])
           else ".png" if tete[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else None)
    return ext, taille


def doublon_existant(prenom, nom, naissance):
    """Même enfant déjà demandé (accents, majuscules et tirets ignorés), hors demandes refusées ou annulées."""
    for r in q("SELECT enfant_prenom, enfant_nom FROM parrainages WHERE naissance=? AND anonymise=0 "
               "AND statut NOT IN ('Refusée','Annulée')", naissance):
        if norm(r["enfant_prenom"]) == norm(prenom) and norm(r["enfant_nom"]) == norm(nom):
            return True
    return False


def controler_demande(f, fichier, ctx):
    """Contrôle côté serveur (le JavaScript du formulaire n'est qu'une aide) : retourne (valeurs, erreurs, extension)."""
    v = {k: ligne(f.get(k)) for k in (
        "enfant_prenom", "enfant_nom", "naissance", "lien", "parent_qualite", "parent_nom", "email", "email2",
        "tel", "adresse", "cp", "ville", "essence1", "essence2")}
    v["enfant_prenom"] = soigner_prenom(v["enfant_prenom"])
    v["attest"], v["engage"], v["rgpd"], v["benevolat"] = (f.get("attest"), f.get("engage"), f.get("rgpd"), f.get("benevolat"))
    err = {}
    for k, msg in (("enfant_prenom", "Indiquez le prénom de l'enfant."), ("enfant_nom", "Indiquez le nom de l'enfant."),
                   ("lien", "Précisez le lien de l'enfant avec Corbas."), ("parent_qualite", "Précisez votre qualité."),
                   ("parent_nom", "Indiquez vos prénom et nom."), ("adresse", "Indiquez votre adresse."),
                   ("cp", "Indiquez le code postal."), ("ville", "Indiquez la commune.")):
        if not v[k]:
            err[k] = msg
    for k, maxi in LONGUEURS.items():
        if len(v[k]) > maxi and k not in err:
            err[k] = f"Ce champ est trop long ({maxi} caractères au maximum)."
    try:
        nais = date.fromisoformat(v["naissance"])
        if nais > aujourdhui():
            err["naissance"] = "La date de naissance ne peut pas être dans le futur."
        elif nais < mois_avant(aujourdhui(), 12):
            err["naissance"] = ("Le parrainage doit être demandé avant les 12 mois de l'enfant. Si vous pensez être dans un "
                                f"cas particulier, contactez l'accueil : {MAIRIE['contact']}.")
    except ValueError:
        err["naissance"] = "Indiquez la date de naissance (jj/mm/aaaa)."
    if v["lien"] not in LIENS:
        err["lien"] = "Précisez le lien de l'enfant avec Corbas."
    elif "domicili" in v["lien"].lower() and not (norm(v["ville"]) == "corbas" and v["cp"] == "69960"):
        err["ville"] = ("Pour un enfant domicilié à Corbas, l'adresse doit être à Corbas (code postal 69960). "
                        "Si l'enfant est né à Corbas, choisissez « Né(e) à Corbas ».")
    if v["cp"] and not (v["cp"].isdigit() and len(v["cp"]) == 5):
        err["cp"] = "Le code postal comporte 5 chiffres."
    if v["parent_qualite"] not in QUALITES:
        err["parent_qualite"] = "Précisez votre qualité."
    if not EMAIL_RE.match(v["email"]):
        err["email"] = "Cette adresse e-mail semble incomplète, par exemple prenom.nom@exemple.fr."
    elif v["email"].lower() != v["email2"].lower():
        err["email2"] = "Les deux adresses e-mail ne sont pas identiques."
    if not v["tel"]:
        err["tel"] = "Indiquez votre numéro de mobile."
    elif len(v["tel"]) > LONGUEURS["tel"]:
        pass  # message de longueur déjà posé plus haut
    elif normaliser_mobile(v["tel"]) is None:
        err["tel"] = MSG_MOBILE
    else:
        v["tel"] = normaliser_mobile(v["tel"])
    ids = {str(e["id"]) for e in ctx["essences"]}
    if v["essence1"] not in ids:
        err["essence1"] = "Choisissez l'essence de l'arbre. Si elle n'apparaît plus, c'est qu'elle vient d'être attribuée."
    if v["essence2"] and (v["essence2"] not in ids or v["essence2"] == v["essence1"]):
        v["essence2"] = ""
    for k, msg in (("attest", "Merci de confirmer que vous détenez l'autorité parentale."),
                   ("engage", "Merci de confirmer que vous avez compris le statut de l'arbre."),
                   ("rgpd", "Merci d'accepter le traitement de vos données pour envoyer la demande.")):
        if not v[k]:
            err[k] = msg
    ext = None
    if not fichier or not fichier.filename:
        err["livret"] = "Joignez une copie du livret de famille (PDF, JPG ou PNG)."
    else:
        ext, taille = type_de_fichier(fichier)
        if not ext:
            err["livret"] = "Ce fichier n'est pas reconnu. Joignez un PDF, une photo JPG ou une image PNG."
        elif taille == 0 or taille > TAILLE_MAX:
            err["livret"] = "Le fichier est vide ou dépasse 5 Mo. Réduisez-le ou photographiez-le à nouveau."
    if err.get("livret") is None and err:
        err["livret_a_rejoindre"] = "Par sécurité, joignez de nouveau la copie du livret de famille."
    if not err and doublon_existant(v["enfant_prenom"], v["enfant_nom"], v["naissance"]):
        err["doublon"] = (f"Une demande existe déjà pour {v['enfant_prenom']} né(e) le {fr(v['naissance'])}. "
                          f"Si vous souhaitez la modifier, contactez l'accueil : {MAIRIE['contact']}.")
    return v, err, ext


def inserer_parrainage(v, ctx, statut, nom_fichier):
    """Insère la demande ; en cas de collision de référence (deux envois simultanés), recommence avec la suivante."""
    for _ in range(6):
        ref = ref_suivante()
        try:
            ex("INSERT INTO parrainages(ref,created_at,campagne_id,statut,enfant_prenom,enfant_nom,naissance,lien,parent_qualite,"
               "parent_nom,email,tel,adresse,cp,ville,essence1_id,essence2_id,benevolat,livret) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ref, now(), ctx["camp"]["id"], statut, v["enfant_prenom"], v["enfant_nom"], v["naissance"], v["lien"],
               v["parent_qualite"], v["parent_nom"], v["email"], v["tel"], v["adresse"], v["cp"], v["ville"],
               int(v["essence1"]), int(v["essence2"]) if v["essence2"] else None, 1 if v["benevolat"] else 0, nom_fichier)
            return ref
        except sqlite3.IntegrityError:
            db().rollback()
    raise RuntimeError("Impossible d'attribuer une référence")


_jeton = URLSafeTimedSerializer(app.secret_key, salt="merci")


@app.post("/demande")
def demande():
    ctx = contexte_formulaire()
    if not ctx["camp"]:
        return render_template("form.html", v={}, errors={}, **ctx)
    f = request.form
    if f.get("site_web"):  # champ piège (honeypot)
        return redirect(url_for("formulaire"))
    ip = request.remote_addr or "?"
    if limite_atteinte(("demande", ip), LIMITE_ENVOIS, 3600) or limite_atteinte(("erreurs", ip), 60, 3600):
        abort(429)
    v, err, ext = controler_demande(f, request.files.get("livret"), ctx)
    if err:
        noter(("erreurs", ip))
        return render_template("form.html", v=v, errors=err, **ctx), 400
    statut = "Liste d'attente" if ctx["attente"] else "Reçue"
    nom_fichier = f"{secrets.token_hex(16)}{ext}"
    request.files["livret"].save(os.path.join(LIVRETS, nom_fichier))
    request.files["livret"].close()
    try:
        ref = inserer_parrainage(v, ctx, statut, nom_fichier)
    except Exception:
        retirer_fichier(nom_fichier)  # pas de copie de livret orpheline si l'enregistrement échoue
        raise
    noter(("demande", ip))
    p = q1("SELECT * FROM parrainages WHERE ref=?", ref)
    e1 = q1("SELECT * FROM essences WHERE id=?", p["essence1_id"])
    e2 = q1("SELECT * FROM essences WHERE id=?", p["essence2_id"]) if p["essence2_id"] else None
    mail_accuse(p, e1, e2, ctx["attente"])
    notifier_agents(p, e1, ctx["attente"])
    return redirect(url_for("merci", token=_jeton.dumps(ref)))


MESSAGES = {
    400: ("Demande non valide", "Votre session a peut-être expiré. Rechargez la page puis recommencez."),
    403: ("Accès refusé", "Cette page est réservée aux administrateurs."),
    404: ("Page introuvable", "Cette page n'existe pas ou le lien a expiré."),
    429: ("Trop de demandes", "Un trop grand nombre de demandes ont été envoyées depuis votre connexion. Réessayez dans une heure "
                              "ou contactez l'accueil de la mairie."),
    500: ("Une erreur est survenue", "Le problème a été enregistré. Réessayez dans quelques instants."),
}


def page_erreur(e):
    code = getattr(e, "code", 500) or 500
    titre, texte = MESSAGES.get(code, MESSAGES[500])
    return render_template("erreur.html", code=code, titre=titre, texte=texte), code


for _code in MESSAGES:
    app.register_error_handler(_code, page_erreur)


@app.errorhandler(413)
def trop_gros(_):
    return render_template("form.html", v={}, errors={"livret": "Le fichier dépasse 5 Mo. Réduisez-le ou photographiez-le à nouveau."},
                           **contexte_formulaire()), 413


@app.get("/merci/<token>")
def merci(token):
    try:
        ref = _jeton.loads(token, max_age=7 * 86400)  # lien signé : impossible de deviner la page d'une autre famille
    except BadSignature:
        abort(404)
    p = q1("SELECT ref, parent_nom, enfant_prenom, statut FROM parrainages WHERE ref=?", ref)
    if not p:
        abort(404)
    return render_template("merci.html", p=p, MAIRIE=MAIRIE)


@app.get("/sante")
def sante():
    q1("SELECT 1")
    return "ok"


# ---------------------------------------------------------------- authentification
def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf"] = csrf
app.jinja_env.globals["MAIRIE"] = MAIRIE
app.jinja_env.globals["STATUTS"] = STATUTS
app.jinja_env.globals["LIENS"] = LIENS
app.jinja_env.globals["QUALITES"] = QUALITES
FAUX_HASH = generate_password_hash("mot-de-passe-inexistant")  # même durée de calcul que pour un vrai compte


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            u = q1("SELECT id, email, role FROM users WHERE id=?", session.get("uid")) if "uid" in session else None
            if not u:  # session expirée, ou compte supprimé depuis la connexion
                session.clear()
                return redirect(url_for("login", next=request.path))
            session["email"], session["role"] = u["email"], u["role"]
            if role == "admin" and u["role"] != "admin":
                abort(403)
            return fn(*a, **k)
        return wrapper
    return deco


@app.before_request
def verif_csrf():
    if request.method == "POST" and request.path.startswith("/admin") and request.path != "/admin/login":
        if "uid" not in session:  # session expirée : retour à la connexion plutôt qu'une page d'erreur
            return redirect(url_for("login"))
        if not secrets.compare_digest(request.form.get("csrf", "").encode(), session.get("csrf", "x").encode()):
            abort(400)


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        cle = ("login", request.remote_addr or "?")
        if limite_atteinte(cle, 10, 900):
            flash("Trop de tentatives. Réessayez dans 15 minutes.", "err")
            return render_template("admin/login.html"), 429
        u = q1("SELECT * FROM users WHERE lower(email)=lower(?)", request.form.get("email", "").strip())
        if check_password_hash(u["hash"] if u else FAUX_HASH, request.form.get("password", "")) and u:
            session.clear()
            session.permanent = True
            session.update(uid=u["id"], email=u["email"], role=u["role"])
            nxt = request.args.get("next", "")
            return redirect(request.script_root + nxt if nxt.startswith("/admin") and not nxt.startswith("//") else url_for("tableau"))
        noter(cle)
        flash("Identifiant ou mot de passe incorrect.", "err")
    return render_template("admin/login.html")


@app.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


MDP_MIN = 10


def controle_mdp(mdp):
    return None if len(mdp) >= MDP_MIN else f"Le mot de passe doit comporter au moins {MDP_MIN} caractères."


@app.route("/admin/mot-de-passe", methods=["GET", "POST"])
@login_required()
def mot_de_passe():
    if request.method == "POST":
        f = request.form
        u = q1("SELECT * FROM users WHERE id=?", session["uid"])
        if not check_password_hash(u["hash"], f.get("ancien", "")):
            flash("Le mot de passe actuel est incorrect.", "err")
        elif controle_mdp(f.get("nouveau", "")):
            flash(controle_mdp(f.get("nouveau", "")), "err")
        elif f.get("nouveau") != f.get("confirmation"):
            flash("Les deux nouveaux mots de passe ne sont pas identiques.", "err")
        else:
            ex("UPDATE users SET hash=? WHERE id=?", generate_password_hash(f["nouveau"]), u["id"])
            flash("Mot de passe modifié.", "ok")
            return redirect(url_for("tableau"))
    return render_template("admin/mot_de_passe.html")


@app.route("/admin/utilisateurs", methods=["GET", "POST"])
@login_required("admin")
def utilisateurs():
    if request.method == "POST":
        f = request.form
        a = f.get("action")
        if a == "creer":
            mail, mdp, role = f.get("email", "").strip().lower(), f.get("mdp", ""), f.get("role")
            if not EMAIL_RE.match(mail):
                flash("Adresse e-mail incorrecte.", "err")
            elif role not in ("agent", "admin"):
                flash("Choisissez un rôle.", "err")
            elif controle_mdp(mdp):
                flash(controle_mdp(mdp), "err")
            elif q1("SELECT 1 FROM users WHERE lower(email)=?", mail):
                flash("Un compte existe déjà avec cette adresse.", "err")
            else:
                ex("INSERT INTO users(email,hash,role) VALUES(?,?,?)", mail, generate_password_hash(mdp), role)
                flash(f"Compte créé pour {mail}. Transmettez-lui son mot de passe par un autre canal que l'e-mail.", "ok")
        else:
            u = q1("SELECT * FROM users WHERE id=?", f.get("id", type=int))
            if not u:
                flash("Compte introuvable.", "err")
            elif a == "mdp":
                if controle_mdp(f.get("mdp", "")):
                    flash(controle_mdp(f.get("mdp", "")), "err")
                else:
                    ex("UPDATE users SET hash=? WHERE id=?", generate_password_hash(f["mdp"]), u["id"])
                    flash(f"Mot de passe de {u['email']} modifié.", "ok")
            elif a == "supprimer":
                if u["id"] == session["uid"]:
                    flash("Vous ne pouvez pas supprimer votre propre compte.", "err")
                elif u["role"] == "admin" and q1("SELECT COUNT(*) n FROM users WHERE role='admin'")["n"] <= 1:
                    flash("Il doit rester au moins un administrateur.", "err")
                else:
                    ex("DELETE FROM users WHERE id=?", u["id"])
                    flash(f"Compte {u['email']} supprimé.", "ok")
            else:
                abort(400)
        return redirect(url_for("utilisateurs"))
    return render_template("admin/utilisateurs.html", rows=q("SELECT * FROM users ORDER BY role, email"))


@app.route("/admin/parametres", methods=["GET", "POST"])
@login_required("admin")
def parametres():
    if request.method == "POST":
        if request.form.get("action") == "test":
            adresses, origine = destinataires_notification()
            for a in adresses:
                send_mail(a, f"Test : notifications « {DISPOSITIF['nom']} »",
                          "Ce message de test confirme que cette adresse reçoit les notifications de nouvelles demandes de parrainage."
                          + SIGN)
            flash(f"Message de test envoyé à {len(adresses)} adresse(s)."
                  + ("" if smtp_actif() else " Aucun serveur d'envoi (SMTP) n'est configuré : il est seulement enregistré dans « Courriers »."), "ok")
        else:
            adresses = decouper_adresses(request.form.get("notifications", ""))
            invalides = [a for a in adresses if not EMAIL_RE.match(a)]
            if invalides:
                flash("Adresse(s) incorrecte(s) : " + ", ".join(invalides[:5]), "err")
            elif len(adresses) > MAX_DESTINATAIRES:
                flash(f"{MAX_DESTINATAIRES} adresses au maximum.", "err")
            else:
                ecrire_param("notification_emails", "\n".join(adresses))
                flash("Réglage enregistré." if adresses else "Réglage supprimé : retour à la configuration du serveur.", "ok")
        return redirect(url_for("parametres"))
    adresses, origine = destinataires_notification()
    return render_template("admin/parametres.html", saisie=lire_param("notification_emails"), adresses=adresses, origine=origine, smtp=smtp_actif())


# ---------------------------------------------------------------- back-office : demandes
@app.get("/admin/")
@login_required()
def tableau():
    camp = request.args.get("campagne", type=int)
    statut = request.args.get("statut", "")
    recherche = norm(request.args.get("q", ""))
    livret_a_supprimer = request.args.get("livret") == "1"
    sql, a = "SELECT p.*, e.nom essence FROM parrainages p LEFT JOIN essences e ON e.id=p.essence1_id WHERE 1=1", []
    if camp:
        sql += " AND campagne_id=?"; a.append(camp)
    if statut == "a_traiter":  # demandes qui attendent une décision de l'agent
        sql += " AND statut IN ('Reçue','Complément demandé')"
    elif statut:
        sql += " AND statut=?"; a.append(statut)
    if livret_a_supprimer:  # contrôle fait, copie du livret encore présente
        sql += " AND livret IS NOT NULL AND livret_supprime_at IS NULL AND statut IN ('Validée','Certificat imprimé','Remis')"
    # file d'attente : les arbres sont en nombre limité, on traite dans l'ordre d'arrivée (les plus anciennes en premier)
    file_attente = statut in ("a_traiter", "Reçue", "Complément demandé", "Liste d'attente")
    rows = q(sql + (" ORDER BY p.id ASC" if file_attente else " ORDER BY p.id DESC"), *a)
    if recherche:  # recherche sans tenir compte des accents ni des majuscules
        rows = [r for r in rows if recherche in norm(" ".join(
            str(r[k] or "") for k in ("ref", "enfant_prenom", "enfant_nom", "parent_nom", "email")))]
    stats = {r["statut"]: r["n"] for r in q("SELECT statut, COUNT(*) n FROM parrainages GROUP BY statut")}
    stock = q("SELECT e.nom, COUNT(a.id) n FROM essences e LEFT JOIN arbres a ON a.essence_id=e.id AND a.statut='libre' "
              "AND a.campagne_id IN (SELECT id FROM campagnes WHERE ouverte=1) WHERE e.actif=1 GROUP BY e.id ORDER BY e.nom")
    livrets = q1("SELECT COUNT(*) n FROM parrainages WHERE livret IS NOT NULL AND livret_supprime_at IS NULL "
                 "AND statut IN ('Validée','Certificat imprimé','Remis')")["n"]
    return render_template("admin/tableau.html", rows=rows, stats=stats, stock=stock, statut=statut, camp=camp,
                           recherche=request.args.get("q", ""), livrets=livrets, livret_filtre=livret_a_supprimer, file_attente=file_attente,
                           libres=sum(s["n"] for s in stock), en_cours=sum(stats.get(s, 0) for s in EN_COURS),
                           campagnes=q("SELECT * FROM campagnes ORDER BY id DESC"))


def detail(pid):
    p = q1("SELECT * FROM parrainages WHERE id=?", pid)
    if not p:
        abort(404)
    return p


@app.get("/admin/demande/<int:pid>")
@login_required()
def fiche(pid):
    p = detail(pid)
    e1 = q1("SELECT * FROM essences WHERE id=?", p["essence1_id"])
    e2 = q1("SELECT * FROM essences WHERE id=?", p["essence2_id"]) if p["essence2_id"] else None
    # tout arbre libre peut être affecté, y compris d'une autre campagne (liste d'attente servie par une campagne ultérieure)
    dispo = q("SELECT a.*, e.nom essence, c.nom campagne FROM arbres a JOIN essences e ON e.id=a.essence_id "
              "JOIN campagnes c ON c.id=a.campagne_id WHERE a.statut='libre' OR a.id=? "
              "ORDER BY (a.campagne_id=?) DESC, (a.essence_id=?) DESC, (a.essence_id=?) DESC, e.nom, a.code",
              p["arbre_id"] or 0, p["campagne_id"], p["essence1_id"], p["essence2_id"] or 0)
    arbre = q1("SELECT a.*, e.nom essence FROM arbres a JOIN essences e ON e.id=a.essence_id WHERE a.id=?", p["arbre_id"]) if p["arbre_id"] else None
    doublons = [r["ref"] for r in q("SELECT ref, enfant_prenom FROM parrainages WHERE id<>? AND anonymise=0 AND lower(email)=lower(?)",
                                    pid, p["email"] or "") if norm(r["enfant_prenom"]) == norm(p["enfant_prenom"])]
    stock1 = q1("SELECT COUNT(*) n FROM arbres WHERE campagne_id=? AND essence_id=? AND statut='libre'", p["campagne_id"], p["essence1_id"])["n"]
    try:  # l'âge se juge à la date de la demande, pas à celle du contrôle
        delai_ok = date.fromisoformat(p["naissance"]) >= mois_avant(date.fromisoformat(p["created_at"][:10]), 12)
    except (TypeError, ValueError):
        delai_ok = True
    actions = {a for a, statuts in AUTORISE.items() if p["statut"] in statuts} if not p["anonymise"] else set()
    return render_template("admin/fiche.html", p=p, echeance=echeance(p), e1=e1, e2=e2, dispo=dispo, arbre=arbre,
                           doublons=doublons, stock1=stock1, delai_ok=delai_ok, actions=actions)


def liberer(p):
    if p["arbre_id"]:
        db().execute("UPDATE arbres SET statut='libre' WHERE id=? AND statut='parraine'", (p["arbre_id"],))


CONSERVATION_JOURS = 183  # ~6 mois : durée pendant laquelle une copie « supprimée » reste récupérable


def retirer_fichier(nom):
    """Efface le fichier ; retourne False s'il n'a pas pu l'être (verrouillé, droits) pour réessayer plus tard."""
    try:
        os.remove(os.path.join(LIVRETS, os.path.basename(nom)))
    except FileNotFoundError:
        pass
    except OSError as e:
        print("Suppression impossible :", e, file=sys.stderr, flush=True)
        return False
    return True


def supprimer_livret(p, definitif=False):
    """Suppression par l'agent : la copie passe en corbeille (récupérable 6 mois). definitif=True : effacement immédiat."""
    if not p["livret"]:
        return
    if definitif and retirer_fichier(p["livret"]):
        db().execute("UPDATE parrainages SET livret=NULL, livret_supprime_at=COALESCE(livret_supprime_at, ?) WHERE id=?", (now(), p["id"]))
    elif definitif:
        raise RuntimeError("La copie du livret n'a pas pu être effacée")
    elif not p["livret_supprime_at"]:
        db().execute("UPDATE parrainages SET livret_supprime_at=? WHERE id=?", (now(), p["id"]))
    db().commit()


def echeance(p):
    if not p["livret_supprime_at"]:
        return None
    return (datetime.strptime(p["livret_supprime_at"], "%Y-%m-%d %H:%M:%S") + timedelta(days=CONSERVATION_JOURS)).strftime("%Y-%m-%d")


def purger_livrets():
    """Efface définitivement les copies supprimées depuis plus de 6 mois."""
    limite = (maintenant() - timedelta(days=CONSERVATION_JOURS)).strftime("%Y-%m-%d %H:%M:%S")
    for r in q("SELECT id, livret FROM parrainages WHERE livret IS NOT NULL AND livret_supprime_at IS NOT NULL AND livret_supprime_at<?", limite):
        if retirer_fichier(r["livret"]):  # sinon on garde la référence et on réessaie à la prochaine purge
            db().execute("UPDATE parrainages SET livret=NULL WHERE id=?", (r["id"],))
    db().commit()


_derniere_purge = [0.0]


@app.before_request
def purge_periodique():
    if request.path.startswith("/admin") and time.time() - _derniere_purge[0] > 3600:
        _derniere_purge[0] = time.time()
        purger_livrets()


@app.get("/admin/demande/<int:pid>/livret")
@login_required()
def livret(pid):
    p = detail(pid)
    if not p["livret"]:
        abort(404)
    if p["livret_supprime_at"] and session.get("role") != "admin":
        abort(403)
    chemin = os.path.join(LIVRETS, os.path.basename(p["livret"]))
    if not os.path.exists(chemin):
        abort(404)
    with open(chemin, "rb") as fh:  # lecture complète (5 Mo max) : pas de descripteur laissé ouvert
        resp = Response(fh.read(), mimetype=mimetypes.guess_type(chemin)[0] or "application/octet-stream")
    resp.headers["Content-Disposition"] = f"inline; filename=livret-{p['ref']}{os.path.splitext(chemin)[1]}"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def valider_demande(p, agent):
    arbre_id = request.form.get("arbre_id", type=int)
    arbre = q1("SELECT * FROM arbres WHERE id=?", arbre_id) if arbre_id else None
    if not arbre:
        flash("Choisissez un arbre dans la liste.", "err")
        return
    changement = p["arbre_id"] != arbre["id"]
    if not changement and p["statut"] in AVEC_ARBRE:
        flash("Cet arbre est déjà affecté à cette demande.", "err")
        return
    # réservation atomique : si un autre agent vient de prendre cet arbre, rien n'est modifié
    pris = db().execute("UPDATE arbres SET statut='parraine' WHERE id=? AND (statut='libre' OR id=?)",
                        (arbre["id"], p["arbre_id"] or 0)).rowcount
    if not pris:
        db().rollback()
        flash("Cet arbre n'est plus disponible.", "err")
        return
    if p["arbre_id"] and changement:
        liberer(p)
    db().execute("UPDATE parrainages SET statut='Validée', arbre_id=?, agent=?, valide_at=?, imprime_at=NULL, motif=NULL WHERE id=?",
                 (arbre["id"], agent, now(), p["id"]))
    db().commit()
    ess = q1("SELECT nom FROM essences WHERE id=?", arbre["essence_id"])["nom"]
    quand = ""
    if not arbre["date_plantation"] and arbre["annee_plantation"]:
        quand = (f" Il sera planté à l'automne {arbre['annee_plantation']} : "
                 "le certificat porte la mention « plantation prévue ».")
    send_mail(p["email"], f"Le certificat de parrainage de {p['enfant_prenom']} est prêt",
              f"Bonjour {p['parent_nom']},\n\nL'arbre de {p['enfant_prenom']} a été choisi : c'est un {ess} !\n"
              f"Son certificat vous attend à l'accueil de la mairie de Corbas, {MAIRIE['adresse']} "
              f"({MAIRIE['horaires']}). Apportez l'original du livret de famille et un justificatif de domicile.{quand}"
              f"\n\nRéférence : {p['ref']}" + SIGN)
    flash("Demande validée, arbre affecté, e-mail envoyé à la famille.", "ok")


def clore_demande(p, statut, motif=None, agent=None):
    """Refus ou annulation : l'arbre est libéré et la copie du livret passe en corbeille (plus aucun contrôle à faire)."""
    liberer(p)
    db().execute("UPDATE parrainages SET statut=?, arbre_id=NULL, motif=COALESCE(?, motif), agent=COALESCE(?, agent) WHERE id=?",
                 (statut, motif, agent, p["id"]))
    db().commit()
    supprimer_livret(p)


@app.post("/admin/demande/<int:pid>/action")
@login_required()
def action(pid):
    p = detail(pid)
    a = request.form.get("action")
    agent = session["email"]
    if p["anonymise"] or a not in AUTORISE:
        abort(400)
    if p["statut"] not in AUTORISE[a]:
        flash(f"Cette action n'est pas possible pour une demande « {p['statut']} ».", "err")
        return redirect(url_for("fiche", pid=pid))
    if a == "valider":
        valider_demande(p, agent)
    elif a == "attente":
        liberer(p)
        db().execute("UPDATE parrainages SET statut=\"Liste d'attente\", arbre_id=NULL, valide_at=NULL, imprime_at=NULL WHERE id=?", (pid,))
        db().commit()
        send_mail(p["email"], f"Votre demande de parrainage ({p['ref']}) est sur liste d'attente", ATTENTE + SIGN)
        flash("Demande mise en liste d'attente.", "ok")
    elif a == "refuser":
        motif = request.form.get("motif", "").strip()
        if not motif:
            flash("Le motif du refus est obligatoire.", "err")
            return redirect(url_for("fiche", pid=pid))
        clore_demande(p, "Refusée", motif, agent)
        send_mail(p["email"], f"Votre demande de parrainage ({p['ref']})",
                  f"Bonjour {p['parent_nom']},\n\nNous ne pouvons pas donner suite à votre demande pour la raison suivante : "
                  f"{motif}\n\nPour toute question : {MAIRIE['contact']}" + SIGN)
        flash("Demande refusée, e-mail envoyé. La copie du livret a été supprimée (récupérable 6 mois).", "ok")
    elif a == "complement":
        msg = request.form.get("motif", "").strip()
        if not msg:
            flash("Précisez ce qu'il manque.", "err")
            return redirect(url_for("fiche", pid=pid))
        db().execute("UPDATE parrainages SET statut='Complément demandé', motif=? WHERE id=?", (msg, pid))
        db().commit()
        send_mail(p["email"], f"Votre demande de parrainage ({p['ref']}) : il nous manque une information",
                  f"Bonjour {p['parent_nom']},\n\nPour finaliser votre demande, il nous manque : {msg}\n"
                  f"Répondez simplement à ce message." + SIGN)
        flash("Demande de complément envoyée.", "ok")
    elif a == "remis":
        db().execute("UPDATE parrainages SET statut='Remis', remis_at=? WHERE id=?", (now(), pid))
        db().commit()
        flash("Certificat marqué comme remis.", "ok")
    elif a == "annuler":
        clore_demande(p, "Annulée")
        flash("Demande annulée, l'arbre est de nouveau disponible. La copie du livret a été supprimée (récupérable 6 mois).", "ok")
    elif a == "notes":
        db().execute("UPDATE parrainages SET notes=? WHERE id=?", (request.form.get("notes", "")[:4000], pid))
        db().commit()
        flash("Notes enregistrées.", "ok")
    elif a == "supprimer_livret":
        supprimer_livret(p)
        flash("Copie du livret supprimée. Elle reste récupérable par un administrateur pendant 6 mois, puis sera effacée.", "ok")
    elif a == "restaurer_livret":
        if session.get("role") != "admin":
            abort(403)
        if p["livret"] and p["livret_supprime_at"]:
            db().execute("UPDATE parrainages SET livret_supprime_at=NULL WHERE id=?", (pid,))
            db().commit()
            flash("Copie du livret restaurée.", "ok")
        else:
            flash("Il n'y a plus de copie à restaurer (délai de 6 mois dépassé).", "err")
    elif a == "anonymiser":
        if session.get("role") != "admin":
            abort(403)
        ref, adresse_mail = p["ref"], p["email"] or ""
        supprimer_livret(p, definitif=True)
        db().execute("UPDATE parrainages SET enfant_nom='', parent_nom='(anonymisé)', email='', tel='', adresse='', cp='', "
                     "ville='', notes='', motif=NULL, anonymise=1 WHERE id=?", (pid,))
        # les courriers conservés dans le back-office contiennent les mêmes données : ils sont effacés aussi
        if adresse_mail:
            db().execute("UPDATE mails SET destinataire='(anonymisé)', sujet='(anonymisé)', corps='(effacé : demande RGPD)' "
                         "WHERE lower(destinataire)=lower(?)", (adresse_mail,))
        db().execute("UPDATE mails SET sujet='(anonymisé) ' || ?, corps='(effacé : demande RGPD)' WHERE sujet LIKE ? OR corps LIKE ?",
                     (ref, f"%{ref}%", f"%{ref}%"))
        db().commit()
        flash("Données personnelles effacées (fiche, copie du livret et courriers). La fiche de l'arbre est conservée.", "ok")
    return redirect(url_for("fiche", pid=pid))


@app.get("/admin/demande/<int:pid>/certificat.pdf")
@login_required()
def certificat_pdf(pid):
    p = detail(pid)
    if not p["arbre_id"]:
        abort(409)
    a = q1("SELECT a.code, a.lieu, a.adresse, a.lat, a.lon, a.date_plantation, a.annee_plantation, a.variete, e.nom, e.latin, e.symbole, "
           "e.caracteristiques, e.role, e.couleur FROM arbres a JOIN essences e ON e.id=a.essence_id WHERE a.id=?", p["arbre_id"])
    # le certificat porte la date de sa première impression, même s'il est réimprimé plus tard
    emis = p["imprime_at"] or now()
    pdf = certificat.generer(dict(
        ref=p["ref"], prenom=p["enfant_prenom"], naissance_fr=fr(p["naissance"]), date_fr=fr(emis),
        arbre_code=a["code"], essence_nom=a["nom"], essence_latin=latin_complet(a["latin"], a["variete"]), symbole=a["symbole"],
        caracteristiques=a["caracteristiques"], role=a["role"], couleur=a["couleur"], lieu=a["lieu"], adresse=a["adresse"],
        lat=a["lat"], lon=a["lon"], plantation_fr=fr(a["date_plantation"]), annee_plantation=a["annee_plantation"]),
        os.path.join(DATA, "tuiles"), dict(MAIRIE, logo=chemin_logo(), logo_dispositif=LOGO_DISPOSITIF))
    if p["statut"] == "Validée":
        ex("UPDATE parrainages SET statut='Certificat imprimé', imprime_at=? WHERE id=?", now(), pid)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=certificat-{p['ref']}.pdf"})


# ---------------------------------------------------------------- back-office : paramétrage
@app.route("/admin/campagnes", methods=["GET", "POST"])
@login_required("admin")
def campagnes():
    if request.method == "POST":
        f = request.form
        try:
            ouverture, fermeture = date_ou_none(f.get("ouverture")), date_ou_none(f.get("fermeture"))
        except ValueError:
            flash("Une des dates est incorrecte.", "err")
            return redirect(url_for("campagnes"))
        nom, annee = ligne(f.get("nom"))[:100], f.get("annee", type=int) or aujourdhui().year
        if not nom:
            flash("Donnez un nom à la campagne.", "err")
        elif not 2000 <= annee <= 2100:
            flash("L'année de plantation est incorrecte.", "err")
        elif ouverture and fermeture and fermeture < ouverture:
            flash("La fermeture des inscriptions ne peut pas précéder leur ouverture.", "err")
        else:
            vals = (nom, annee, ouverture, fermeture, 1 if f.get("ouverte") else 0)
            if f.get("id"):
                ex("UPDATE campagnes SET nom=?,annee=?,ouverture=?,fermeture=?,ouverte=? WHERE id=?", *vals, int(f["id"]))
            else:
                ex("INSERT INTO campagnes(nom,annee,ouverture,fermeture,ouverte) VALUES(?,?,?,?,?)", *vals)
            flash("Campagne enregistrée.", "ok")
        return redirect(url_for("campagnes"))
    rows = q("SELECT c.*, (SELECT COUNT(*) FROM arbres WHERE campagne_id=c.id) total, "
             "(SELECT COUNT(*) FROM arbres WHERE campagne_id=c.id AND statut='libre') libres FROM campagnes c ORDER BY id DESC")
    return render_template("admin/campagnes.html", rows=rows, edit=q1("SELECT * FROM campagnes WHERE id=?", request.args.get("edit", type=int)))


@app.route("/admin/essences", methods=["GET", "POST"])
@login_required("admin")
def essences():
    if request.method == "POST":
        f = request.form
        vals = [f.get(k, "").strip() for k in ("nom", "latin", "resume", "symbole", "caracteristiques", "role")]
        couleur = f.get("couleur", "").strip() or "#2e7d32"
        fichier = request.files.get("photo")
        img = lire_photo(fichier) if fichier and fichier.filename else None
        if not vals[0]:
            flash("Donnez un nom à l'essence.", "err")
        elif not COULEUR_RE.match(couleur):
            flash("La couleur doit s'écrire comme #2e7d32 (dièse suivi de 6 caractères 0-9 ou a-f).", "err")
        elif fichier and fichier.filename and img is None:
            flash("Cette photo n'est pas reconnue. Joignez une image JPG, PNG ou WebP.", "err")
        else:
            vals += [couleur, 1 if f.get("actif") else 0]
            if f.get("id"):
                eid = int(f["id"])
                ex("UPDATE essences SET nom=?,latin=?,resume=?,symbole=?,caracteristiques=?,role=?,couleur=?,actif=? WHERE id=?", *vals, eid)
            else:
                eid = ex("INSERT INTO essences(nom,latin,resume,symbole,caracteristiques,role,couleur,actif) VALUES(?,?,?,?,?,?,?,?)", *vals)
            if img is not None:
                img.thumbnail((1000, 1000))
                ecrire_photo(f"essence-{eid}", img)
            elif f.get("photo_retirer"):
                retirer_photo(f"essence-{eid}")
            flash("Essence enregistrée.", "ok")
        return redirect(url_for("essences"))
    edit = q1("SELECT * FROM essences WHERE id=?", request.args.get("edit", type=int))
    return render_template("admin/essences.html", rows=q("SELECT * FROM essences ORDER BY nom"), edit=edit,
                           photo_actuelle=photo_essence(edit) if edit else None,
                           photo_envoyee=bool(edit) and bool(photo_envoyee_url(f"essence-{edit['id']}")))


@app.route("/admin/photos", methods=["GET", "POST"])
@login_required("admin")
def photos_admin():
    if request.method == "POST":
        nom = request.form.get("nom")
        if nom not in PHOTOS_AMBIANCE:
            abort(400)
        fichier = request.files.get("photo")
        if request.form.get("action") == "origine":
            retirer_photo(nom)
            flash("Photo d'origine rétablie.", "ok")
        elif not fichier or not fichier.filename:
            flash("Choisissez la photo à envoyer.", "err")
        else:
            img = lire_photo(fichier)
            if img is None:
                flash("Cette photo n'est pas reconnue. Joignez une image JPG, PNG ou WebP.", "err")
            else:
                ecrire_photo(nom, ImageOps.fit(img, BANDEAU, Image.LANCZOS))  # recadrée au format du bandeau
                flash("Photo remplacée.", "ok")
        return redirect(url_for("photos_admin"))
    lignes = [dict(nom=n, titre=t, url=photo(n), envoyee=bool(photo_envoyee_url(n))) for n, t in PHOTOS_AMBIANCE.items()]
    return render_template("admin/photos.html", lignes=lignes)


def lire_coordonnees(f):
    lat, lon = float(f["lat"].replace(",", ".")), float(f["lon"].replace(",", "."))
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError
    la0, la1, lo0, lo1 = CADRE_CORBAS
    if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
        raise OverflowError
    return lat, lon


@app.get("/admin/api/lieu")
@login_required("admin")
def api_lieu():
    return reponse_suggestions("lieu", chercher_lieux)


@app.route("/admin/arbres", methods=["GET", "POST"])
@login_required("admin")
def arbres():
    if request.method == "POST":
        f = request.form
        retour = url_for("arbres", campagne=f.get("campagne_id", type=int))
        if f.get("action") == "supprimer":
            a = q1("SELECT * FROM arbres WHERE id=?", f.get("id", type=int))
            if a and a["statut"] == "libre":
                ex("DELETE FROM arbres WHERE id=?", a["id"])
                flash("Arbre supprimé du stock.", "ok")
            else:
                flash("Seul un arbre libre peut être supprimé. Pour un arbre parrainé, annulez d'abord le parrainage.", "err")
            return redirect(retour)
        if f.get("action") == "statut":
            a = q1("SELECT a.*, (SELECT COUNT(*) FROM parrainages p WHERE p.arbre_id=a.id) lies FROM arbres a WHERE a.id=?", f.get("id", type=int))
            statut = f.get("statut")
            try:
                plante = date_ou_none(f.get("date_plantation"))
            except ValueError:
                flash("La date de plantation est incorrecte.", "err")
                return redirect(retour)
            if not a or statut not in STATUTS_ARBRE:
                flash("Arbre ou statut inconnu.", "err")
            elif a["lies"] and statut == "libre":
                flash("Cet arbre est affecté à un parrainage : annulez d'abord le parrainage pour le remettre en stock.", "err")
            elif not a["lies"] and statut == "parraine":
                flash("Un arbre n'est « parrainé » que par la validation d'une demande.", "err")
            else:
                ex("UPDATE arbres SET statut=?, date_plantation=?, observations=? WHERE id=?",
                   statut, plante, f.get("observations", "")[:1000], a["id"])
                flash("Arbre mis à jour.", "ok")
            return redirect(retour)
        if f.get("action") == "modifier":
            a = q1("SELECT * FROM arbres WHERE id=?", f.get("id", type=int))
            try:
                lieu = ligne(f.get("lieu"))[:120]
                if not a or not lieu:
                    raise ValueError
                lat, lon = lire_coordonnees(f)
            except (KeyError, ValueError, TypeError):
                flash("Vérifiez les champs : lieu et coordonnées GPS (ex. 45.6706 et 4.8960).", "err")
            except OverflowError:
                flash("Ces coordonnées ne sont pas à Corbas. Vérifiez la latitude (environ 45.67) et la longitude (environ 4.90).", "err")
            else:
                ex("UPDATE arbres SET lieu=?, adresse=?, lat=?, lon=?, variete=?, taille=? WHERE id=?",
                   lieu, ligne(f.get("adresse"))[:200], lat, lon, ligne(f.get("variete"))[:60], ligne(f.get("taille"))[:40], a["id"])
                flash("Arbre modifié.", "ok")
            return redirect(retour)
        try:
            camp = int(f["campagne_id"]); ess = int(f["essence_id"])
            nb = int(f.get("nombre") or 1)
            lieu = ligne(f.get("lieu"))[:120]
            if not 1 <= nb <= 200 or not lieu:
                raise ValueError
            lat, lon = lire_coordonnees(f)
            annee_c = q1("SELECT annee FROM campagnes WHERE id=?", camp)["annee"]
            if not q1("SELECT 1 FROM essences WHERE id=?", ess):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            flash("Vérifiez les champs : campagne, essence, lieu, nombre (1 à 200) et coordonnées GPS (ex. 45.6706 et 4.8960).", "err")
            return redirect(url_for("arbres"))
        except OverflowError:
            flash("Ces coordonnées ne sont pas à Corbas. Vérifiez la latitude (environ 45.67) et la longitude (environ 4.90).", "err")
            return redirect(url_for("arbres"))
        n = prochain_numero("arbres", f"COR-{annee_c}")
        for i in range(nb):
            db().execute("INSERT INTO arbres(code,campagne_id,essence_id,lieu,adresse,lat,lon,annee_plantation,variete,taille) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (f"COR-{annee_c}-{n + i:03d}", camp, ess, lieu, ligne(f.get("adresse"))[:200],
                          lat + (i % 5) * 0.00008, lon + (i // 5) * 0.0001, f.get("annee_plantation", type=int) or annee_c,
                          ligne(f.get("variete"))[:60], ligne(f.get("taille"))[:40]))
        db().commit()  # tout ou rien
        flash(f"{nb} arbre(s) ajouté(s) au stock. Ajustez les coordonnées au besoin.", "ok")
        return redirect(url_for("arbres", campagne=camp))
    camp = request.args.get("campagne", type=int)
    sql = ("SELECT a.*, e.nom essence, c.nom campagne, p.ref pref, p.enfant_prenom FROM arbres a JOIN essences e ON e.id=a.essence_id "
           "JOIN campagnes c ON c.id=a.campagne_id LEFT JOIN parrainages p ON p.arbre_id=a.id")
    rows = q(sql + (" WHERE a.campagne_id=?" if camp else "") + " ORDER BY a.code", *([camp] if camp else []))
    return render_template("admin/arbres.html", rows=rows, camp=camp, campagnes=q("SELECT * FROM campagnes ORDER BY id DESC"),
                           essences=q("SELECT * FROM essences WHERE actif=1 ORDER BY nom"))


@app.get("/admin/mails")
@login_required()
def mails():
    return render_template("admin/mails.html", rows=q("SELECT * FROM mails ORDER BY id DESC LIMIT 100"), smtp=smtp_actif())


@app.post("/admin/mails/<int:mid>/renvoyer")
@login_required()
def renvoyer_mail(mid):
    if not q1("SELECT 1 FROM mails WHERE id=? AND envoye=0", mid):
        flash("Ce courrier est déjà parti ou n'existe plus.", "err")
    elif not smtp_actif():
        flash("Aucun serveur d'envoi (SMTP) n'est configuré.", "err")
    else:
        lancer_envoi(mid)
        flash("Nouvel envoi en cours. Actualisez la page dans quelques secondes.", "ok")
    return redirect(url_for("mails"))


def livret_export(r):
    if r["livret"] and not r["livret_supprime_at"]:
        return "Reçue, à contrôler"
    if r["livret"]:
        return f"Supprimée le {fr(r['livret_supprime_at'])}, récupérable jusqu'au {fr(echeance(r))}"
    if r["livret_supprime_at"]:
        return f"Supprimée le {fr(r['livret_supprime_at'])}, effacée définitivement"
    return ""


@app.get("/admin/export.xlsx")
@login_required()
def export_xlsx():
    wb = Workbook()

    def feuille(ws, titre, entetes, lignes):
        ws.title = titre
        ws.append(entetes)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="2E6B34")
        for l in lignes:
            ws.append(list(l))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, str):
                    c.data_type = "s"  # un texte saisi par une famille (« =... ») ne doit jamais devenir une formule Excel
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(40, max(10, max(len(str(c.value or "")) for c in col) + 2))

    feuille(wb.active, "Parrainages",
            ["Référence", "Date de la demande", "Campagne", "Statut", "Prénom enfant", "Nom enfant", "Naissance", "Lien avec Corbas",
             "Copie du livret", "Parent", "Qualité", "E-mail", "Téléphone", "Adresse", "CP", "Ville", "Essence 1", "Essence 2",
             "Bénévolat entretien", "Arbre affecté", "Agent", "Validé le", "Imprimé le", "Remis le", "Motif", "Notes"],
            [(r["ref"], r["created_at"], r["camp"], r["statut"], r["enfant_prenom"], r["enfant_nom"], r["naissance"], r["lien"],
              livret_export(r), r["parent_nom"], r["parent_qualite"], r["email"], r["tel"], r["adresse"], r["cp"],
              r["ville"], r["e1"], r["e2"], "Oui" if r["benevolat"] else "Non", r["code"], r["agent"], r["valide_at"],
              r["imprime_at"], r["remis_at"], r["motif"], r["notes"]) for r in q(
                "SELECT p.*, c.nom camp, e1.nom e1, e2.nom e2, a.code FROM parrainages p LEFT JOIN campagnes c ON c.id=p.campagne_id "
                "LEFT JOIN essences e1 ON e1.id=p.essence1_id LEFT JOIN essences e2 ON e2.id=p.essence2_id "
                "LEFT JOIN arbres a ON a.id=p.arbre_id ORDER BY p.id")])
    feuille(wb.create_sheet(), "Arbres",
            ["Identifiant", "Campagne", "Essence", "Nom latin", "Variété", "Taille", "Lieu", "Adresse", "Latitude", "Longitude",
             "Année plantation", "Date plantation", "Statut", "Parrainage", "Prénom de l'enfant", "Observations"],
            [(r["code"], r["camp"], r["essence"], r["latin"], r["variete"], r["taille"], r["lieu"], r["adresse"], r["lat"], r["lon"], r["annee_plantation"],
              r["date_plantation"], r["statut"], r["pref"], r["enfant_prenom"], r["observations"]) for r in q(
                "SELECT a.*, c.nom camp, e.nom essence, e.latin, p.ref pref, p.enfant_prenom FROM arbres a "
                "JOIN campagnes c ON c.id=a.campagne_id JOIN essences e ON e.id=a.essence_id "
                "LEFT JOIN parrainages p ON p.arbre_id=a.id ORDER BY a.code")])
    feuille(wb.create_sheet(), "Essences", ["Nom", "Nom latin", "Description", "Ce qu'il représente", "Caractéristiques", "Rôle", "Actif"],
            [(r["nom"], r["latin"], r["resume"], r["symbole"], r["caracteristiques"], r["role"], "Oui" if r["actif"] else "Non")
             for r in q("SELECT * FROM essences ORDER BY nom")])
    feuille(wb.create_sheet(), "Campagnes", ["Nom", "Année", "Ouverture", "Fermeture", "Ouverte"],
            [(r["nom"], r["annee"], r["ouverture"], r["fermeture"], "Oui" if r["ouverte"] else "Non") for r in q("SELECT * FROM campagnes")])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=parrainages-{aujourdhui().isoformat()}.xlsx"})


# ---------------------------------------------------------------- démarrage
init_db(demo=os.environ.get("DEMO", "0") == "1")
with app.app_context():
    purger_livrets()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("DEBUG", "0") == "1")
