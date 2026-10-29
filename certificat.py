"""Génération du certificat de parrainage (PDF A4 paysage) et de la carte."""
import io
import math
import os
import threading
import unicodedata

import requests
from PIL import Image, ImageDraw
from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ZOOM = 17
TILE = 256
UA = "ParrainageCorbas/1.0 (certificats de parrainage, mairie de Corbas)"
COULEUR_DEFAUT = "#2e7d32"
BLEU_VILLE = "#005b94"  # bleu du site de la ville : cadre, titre et intertitres du certificat
BAS_COLONNE = 128  # les textes de l'essence ne descendent pas sous cette ordonnée (pied de page au-dessous)

# Les polices PDF standard ne connaissent que l'alphabet occidental (cp1252) : on translittère le reste
# plutôt que d'imprimer des carrés noirs sur un certificat.
_SPECIAUX = str.maketrans({"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Ħ": "H", "ħ": "h", "ı": "i", "ĸ": "k"})


def texte_pdf(s):
    out = []
    for ch in unicodedata.normalize("NFC", (s or "").replace("\r\n", "\n").replace("\r", "\n")):
        try:
            ch.encode("cp1252")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        ch2 = ch.translate(_SPECIAUX)
        if ch2 != ch:
            out.append(ch2)
            continue
        out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode() or "?")
    return "".join(out)


def charger_logo(chemin, hauteur):
    """Logo (PNG ou JPG) réduit à une taille raisonnable pour le PDF : (image, largeur, hauteur) en points, ou None."""
    if not chemin or not os.path.exists(chemin):
        return None
    try:
        img = Image.open(chemin)
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        img.thumbnail((1200, 600))
        if img.width < 600:  # logo de petite taille : agrandi avec lissage (les contours restent nets à l'impression)
            facteur = 4
            img = img.resize((img.width * facteur, img.height * facteur), Image.LANCZOS)
        return ImageReader(img), hauteur * img.width / img.height, hauteur
    except Exception:  # fichier abîmé : le certificat reste imprimable, avec le nom de la ville en texte
        return None


def _tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _fetch_tile(x, y, cache_dir):
    path = os.path.join(cache_dir, f"{ZOOM}_{x}_{y}.png")
    if os.path.exists(path):
        try:
            return Image.open(path).convert("RGB")
        except Exception:  # tuile tronquée (arrêt en cours d'écriture) : on la retélécharge
            try:
                os.remove(path)
            except OSError:
                pass
    r = requests.get(f"https://tile.openstreetmap.org/{ZOOM}/{x}/{y}.png",
                     headers={"User-Agent": UA}, timeout=6)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")  # vérifie que la réponse est bien une image
    os.makedirs(cache_dir, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, path)
    return img


def carte(lat, lon, cache_dir, width=640, height=420, numero=""):
    """Carte centrée sur l'arbre (fond OpenStreetMap, repère rouge)."""
    fx, fy = _tile_xy(lat, lon, ZOOM)
    cx, cy = int(fx), int(fy)
    try:
        grid = Image.new("RGB", (TILE * 3, TILE * 3))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                grid.paste(_fetch_tile(cx + dx, cy + dy, cache_dir),
                           ((dx + 1) * TILE, (dy + 1) * TILE))
        px, py = int((fx - cx + 1) * TILE), int((fy - cy + 1) * TILE)
        ok = True
    except Exception:
        grid = Image.new("RGB", (TILE * 3, TILE * 3), "#eef2e8")
        d = ImageDraw.Draw(grid)
        for i in range(0, TILE * 3, 64):
            d.line([(i, 0), (i, TILE * 3)], fill="#d5dccb")
            d.line([(0, i), (TILE * 3, i)], fill="#d5dccb")
        d.text((12, 12), "Fond de carte indisponible (hors ligne)", fill="#555")
        px, py = TILE * 3 // 2, TILE * 3 // 2
        ok = False
    left, top = px - width // 2, py - height // 2
    img = grid.crop((left, top, left + width, top + height))
    d = ImageDraw.Draw(img)
    mx, my = width // 2, height // 2
    d.ellipse([mx - 22, my - 22, mx + 22, my + 22], outline="#c0392b", width=4)
    d.ellipse([mx - 7, my - 7, mx + 7, my + 7], fill="#c0392b", outline="white", width=2)
    if numero:
        numero = texte_pdf(numero)
        d.rectangle([mx + 26, my - 12, mx + 26 + 8 * len(numero) + 10, my + 12], fill="white", outline="#c0392b")
        d.text((mx + 31, my - 5), numero, fill="#c0392b")
    return img, ok


def _wrap(c, text, x, y, width, font="Helvetica", size=10, leading=13, ymin=None):
    """Écrit le texte à la ligne. Si ymin est donné, s'arrête avec « … » plutôt que de déborder."""
    lignes = simpleSplit(texte_pdf(text), font, size, width)
    for k, line in enumerate(lignes):
        if ymin is not None and y < ymin:
            return y
        if ymin is not None and y - leading < ymin and k < len(lignes) - 1:
            line = line.rstrip(" .,;") + " …"
            c.setFont(font, size)
            c.drawString(x, y, line)
            return y - leading
        c.setFont(font, size)
        c.drawString(x, y, line)
        y -= leading
    return y


def _taille_colonne(blocs, largeur, haut):
    """Plus grande taille de police (10 à 7 pt) pour que tous les textes tiennent dans la hauteur disponible."""
    taille = 10.0
    while taille > 7:
        h = sum(14 + len(simpleSplit(texte_pdf(t), "Helvetica", taille, largeur)) * (taille + 3) + 8 for _, t in blocs)
        if h <= haut:
            break
        taille -= 0.5
    return taille


def generer(p, cache_dir, mairie):
    """p : dict avec les champs du parrainage, de l'arbre et de l'essence."""
    buf = io.BytesIO()
    W, H = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(texte_pdf(f"Certificat de parrainage {p['ref']}"))
    try:
        accent = HexColor(p.get("couleur") or COULEUR_DEFAUT)
    except Exception:  # couleur saisie de travers dans l'administration
        accent = HexColor(COULEUR_DEFAUT)
    bleu = HexColor(BLEU_VILLE)
    c.setStrokeColor(bleu)
    c.setLineWidth(3)
    c.rect(18, 18, W - 36, H - 36)
    c.setLineWidth(0.8)
    c.rect(26, 26, W - 52, H - 52)

    logo = charger_logo(mairie.get("logo"), 50)
    c.setFillColor(bleu)
    if logo:  # le logo porte déjà le nom de la ville : pas de ligne de texte en plus
        c.drawImage(logo[0], 44, H - 44 - logo[2], logo[1], logo[2], mask="auto")
    else:
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(W / 2, H - 52, texte_pdf(mairie["nom"]).upper())
    dispositif = charger_logo(mairie.get("logo_dispositif"), 56)  # logo « Mon arbre à Corbas », en face de celui de la ville
    if dispositif:
        c.drawImage(dispositif[0], W - 44 - dispositif[1], H - 44 - dispositif[2], dispositif[1], dispositif[2], mask="auto")
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(W / 2, H - 86, "Certificat de parrainage")
    c.setFillColor(black)
    phrase = texte_pdf(f"L'arbre n° {p['arbre_code']} est parrainé par {p['prenom']}, né(e) le {p['naissance_fr']}.")
    taille = 12
    while taille > 8 and stringWidth(phrase, "Helvetica", taille) > W - 96:
        taille -= 0.5
    c.setFont("Helvetica", taille)
    c.drawCentredString(W / 2, H - 112, phrase)

    # colonne gauche : l'essence
    lx, ly, lw = 48, H - 150, 380
    c.setFillColor(accent)
    nom_essence, taille = texte_pdf(p["essence_nom"]), 16
    while taille > 10 and stringWidth(nom_essence, "Helvetica-Bold", taille) > lw:  # ne pas déborder sur la carte
        taille -= 1
    c.setFont("Helvetica-Bold", taille)
    c.drawString(lx, ly, nom_essence)
    c.setFillColor(black)
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(lx, ly - 15, texte_pdf(p.get("essence_latin")))
    y = ly - 40
    blocs = [(titre, p[cle]) for titre, cle in (("Ce qu'il représente", "symbole"), ("Ses caractéristiques", "caracteristiques"),
                                                 ("Son rôle à Corbas", "role")) if p.get(cle)]
    plante = (f"Planté le {p['plantation_fr']}." if p.get("plantation_fr")
              else f"Plantation prévue à l'automne {p['annee_plantation']}." if p.get("annee_plantation")
              else "")
    bas = BAS_COLONNE + (18 if plante else 0)  # la ligne de plantation garde toujours sa place
    taille = _taille_colonne(blocs, lw, y - bas - 16)
    for titre, texte in blocs:
        if y - 14 < bas:  # plus de place : pas de titre sans texte
            break
        c.setFillColor(bleu)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(lx, y, titre)
        c.setFillColor(black)
        y = _wrap(c, texte, lx, y - 14, lw, size=taille, leading=taille + 3, ymin=bas)
        y -= 8
    if plante:
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(lx, max(y, BAS_COLONNE + 2), texte_pdf(plante))

    # colonne droite : la carte
    img, _ = carte(p["lat"], p["lon"], cache_dir, numero=p["arbre_code"])
    mw, mh = 320, 210
    mx, my = W - 48 - mw, H - 150 - mh + 10
    c.drawImage(ImageReader(img), mx, my, mw, mh)
    c.setStrokeColor(bleu)
    c.rect(mx, my, mw, mh)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(HexColor("#555555"))
    c.drawRightString(mx + mw, my - 8, "© les contributeurs d'OpenStreetMap")
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(mx, my - 24, "Où le trouver")
    yy = _wrap(c, p["lieu"] + (f", {p['adresse']}" if p.get("adresse") else ""), mx, my - 38, mw, ymin=BAS_COLONNE + 14)
    c.setFont("Helvetica", 8.5)
    c.drawString(mx, yy - 2, texte_pdf(f"Identifiant : {p['arbre_code']}   -   GPS : {p['lat']:.5f}, {p['lon']:.5f}"))

    # pied
    c.setFont("Helvetica", 7.5)
    c.setFillColor(HexColor("#444444"))
    _wrap(c, "L'arbre demeure un bien communal : le parrainage n'emporte aucun droit de propriété ni d'usage "
             "exclusif. La commune assure son entretien et peut intervenir sur l'arbre (taille, déplacement, "
             "abattage pour motif sanitaire ou de sécurité).", 48, 112, W - 96, size=7.5, leading=10)
    c.setFillColor(black)
    c.setFont("Helvetica", 9)
    c.drawString(48, 66, texte_pdf(f"Parrainage n° {p['ref']}"))
    c.drawString(48, 52, f"Fait à Corbas, le {p['date_fr']}")
    c.setFont("Helvetica", 9)
    c.drawRightString(W - 48, 66, texte_pdf(f"Le Maire, {mairie['maire']}"))
    c.line(W - 48 - 160, 56, W - 48, 56)
    c.showPage()
    c.save()
    return buf.getvalue()
