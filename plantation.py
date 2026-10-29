"""Charge un plan de plantation (campagne, essences, sites et arbres) dans la base de l'application.

    python plantation.py donnees/plantation-automne-2026.json [--campagne "Automne 2026"] [--remplacer]

Le fichier est un JSON (voir donnees/plantation-automne-2026.json). Le chargement est « tout ou rien » : au moindre défaut
du fichier, rien n'est écrit. Les essences sont reconnues par leur nom latin : une essence déjà connue est conservée avec ses
textes et sa photo (seuls ses champs vides sont complétés) ; les autres sont créées.

Une campagne qui n'existe pas encore est créée **fermée** : l'administrateur l'ouvre quand les inscriptions peuvent commencer.
Une campagne qui contient déjà des arbres n'est touchée qu'avec --remplacer, qui retire ses arbres libres (jamais un arbre
parrainé) avant de charger ceux du fichier, et désactive les essences qui n'ont plus aucun arbre."""
import argparse
import json
import math
import sqlite3
import sys

import app


class ErreurPlan(Exception):
    """Le plan est incohérent ou ne peut pas être chargé : le message dit pourquoi."""


def position_correcte(lat, lon):
    la0, la1, lo0, lo1 = app.CADRE_CORBAS
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)) \
        and la0 <= lat <= la1 and lo0 <= lon <= lo1


def entier(v, mini, maxi):
    return isinstance(v, int) and not isinstance(v, bool) and mini <= v <= maxi


def controler(plan):
    """Défauts du plan, un message par défaut (liste vide si le plan est correct)."""
    defauts = []
    camp = plan.get("campagne") or {}
    if not app.ligne(camp.get("nom")):
        defauts.append("campagne : le nom est obligatoire")
    if not entier(camp.get("annee"), 2000, 2100):
        defauts.append("campagne : l'année doit être comprise entre 2000 et 2100")
    essences = {}
    for i, e in enumerate(plan.get("essences") or [], 1):
        nom, latin = app.ligne(e.get("nom")), app.ligne(e.get("latin"))
        if not nom or not latin:
            defauts.append(f"essence n° {i} : le nom et le nom latin sont obligatoires")
            continue
        if app.norm(latin) in essences:
            defauts.append(f"essence « {latin} » : présente deux fois")
        essences[app.norm(latin)] = e
        if e.get("couleur") and not app.COULEUR_RE.match(e["couleur"]):
            defauts.append(f"essence « {latin} » : la couleur doit s'écrire comme #2e7d32")
    if not essences:
        defauts.append("aucune essence dans le fichier")
    sites = plan.get("sites") or []
    if not sites:
        defauts.append("aucun site dans le fichier")
    for s in sites:
        lieu = app.ligne(s.get("lieu"))
        if not lieu:
            defauts.append("un site n'a pas de nom (lieu)")
        if not position_correcte(s.get("lat"), s.get("lon")):
            defauts.append(f"site « {lieu} » : coordonnées GPS absentes ou hors de Corbas")
        if not s.get("arbres"):
            defauts.append(f"site « {lieu} » : aucun arbre")
        for ligne_arbre in s.get("arbres") or []:
            if app.norm(ligne_arbre.get("essence")) not in essences:
                defauts.append(f"site « {lieu} » : l'essence « {ligne_arbre.get('essence')} » n'est pas dans la liste des essences")
            if not entier(ligne_arbre.get("quantite", 1), 1, 200):
                defauts.append(f"site « {lieu} » : la quantité de « {ligne_arbre.get('essence')} » doit être un nombre de 1 à 200")
            if ("lat" in ligne_arbre or "lon" in ligne_arbre) and not position_correcte(ligne_arbre.get("lat"), ligne_arbre.get("lon")):
                defauts.append(f"site « {lieu} » : coordonnées GPS de « {ligne_arbre.get('essence')} » incorrectes ou hors de Corbas")
    return defauts


def charger(con, plan, campagne=None, remplacer=False):
    """Charge le plan dans la base (connexion sqlite3) et retourne le bilan. Lève ErreurPlan, sans rien écrire, si le plan est
    incorrect ou si la campagne contient déjà des arbres et que remplacer est faux."""
    defauts = controler(plan)
    if defauts:
        raise ErreurPlan("Le fichier contient des erreurs, rien n'a été écrit :\n - " + "\n - ".join(defauts))
    nom_camp = app.ligne(campagne) or app.ligne(plan["campagne"]["nom"])
    bilan = dict(campagne=nom_camp, creee=False, essences_creees=0, essences_reprises=0, arbres=0, retires=0, gardes=0, desactivees=0)
    try:
        camp = con.execute("SELECT id, annee FROM campagnes WHERE nom=?", (nom_camp,)).fetchone()
        if camp is None:
            annee = plan["campagne"]["annee"]
            cid = con.execute("INSERT INTO campagnes(nom,annee,ouverte) VALUES(?,?,0)", (nom_camp, annee)).lastrowid
            bilan["creee"] = True
        else:
            cid, annee = camp
            deja = con.execute("SELECT COUNT(*) FROM arbres WHERE campagne_id=?", (cid,)).fetchone()[0]
            if deja and not remplacer:
                raise ErreurPlan(f"La campagne « {nom_camp} » contient déjà {deja} arbre(s). Ajoutez --remplacer pour remplacer ses arbres "
                                 "libres par ceux du fichier (les arbres déjà parrainés sont conservés).")
        if remplacer:
            bilan["retires"] = con.execute(
                "DELETE FROM arbres WHERE campagne_id=? AND statut='libre' AND NOT EXISTS (SELECT 1 FROM parrainages p WHERE p.arbre_id=arbres.id)",
                (cid,)).rowcount
            bilan["gardes"] = con.execute("SELECT COUNT(*) FROM arbres WHERE campagne_id=?", (cid,)).fetchone()[0]

        connues = {app.norm(latin): ident for ident, latin in con.execute("SELECT id, latin FROM essences")}
        ids = {}
        for e in plan["essences"]:
            cle = app.norm(e["latin"])
            textes = [(e.get(k) or "").strip() for k in ("resume", "symbole", "caracteristiques", "role")]
            if cle in connues:  # essence déjà connue : réactivée, ses textes sont gardés (seuls les champs vides sont complétés)
                ids[cle] = connues[cle]
                con.execute("UPDATE essences SET actif=1, resume=COALESCE(NULLIF(resume,''),?), symbole=COALESCE(NULLIF(symbole,''),?), "
                            "caracteristiques=COALESCE(NULLIF(caracteristiques,''),?), role=COALESCE(NULLIF(role,''),?) WHERE id=?",
                            (*textes, ids[cle]))
                bilan["essences_reprises"] += 1
            else:
                ids[cle] = con.execute(
                    "INSERT INTO essences(nom,latin,resume,symbole,caracteristiques,role,couleur,actif) VALUES(?,?,?,?,?,?,?,1)",
                    (app.ligne(e["nom"]), app.ligne(e["latin"]), *textes, e.get("couleur") or "#2e7d32")).lastrowid
                bilan["essences_creees"] += 1
        if remplacer:
            bilan["desactivees"] = con.execute(
                f"UPDATE essences SET actif=0 WHERE actif=1 AND id NOT IN ({','.join('?' * len(ids))}) "
                "AND NOT EXISTS (SELECT 1 FROM arbres a WHERE a.essence_id=essences.id)", list(ids.values())).rowcount

        numero = 0  # les identifiants continuent la série de l'année (COR-2026-001, 002…), campagnes confondues
        for (code,) in con.execute("SELECT code FROM arbres WHERE code LIKE ?", (f"COR-{annee}-%",)):
            suite = code.rsplit("-", 1)[-1]
            if suite.isdigit():
                numero = max(numero, int(suite))
        for site in plan["sites"]:
            posees = {}  # arbres déjà posés à chaque position : les suivants sont décalés de quelques mètres
            for l in site["arbres"]:
                lat, lon = l.get("lat", site["lat"]), l.get("lon", site["lon"])
                for _ in range(l.get("quantite", 1)):
                    rang = posees[(lat, lon)] = posees.get((lat, lon), -1) + 1
                    numero += 1
                    con.execute(
                        "INSERT INTO arbres(code,campagne_id,essence_id,lieu,adresse,lat,lon,annee_plantation,variete,taille,observations) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (f"COR-{annee}-{numero:03d}", cid, ids[app.norm(l["essence"])], app.ligne(site["lieu"])[:120],
                         app.ligne(site.get("adresse"))[:200], round(lat + (rang % 5) * 0.00008, 6), round(lon + (rang // 5) * 0.0001, 6),
                         annee, app.ligne(l.get("variete"))[:60], app.ligne(l.get("taille"))[:40], app.ligne(l.get("note"))[:1000] or None))
                    bilan["arbres"] += 1
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return bilan


def main(argv=None):
    p = argparse.ArgumentParser(description="Charge un plan de plantation (essences, sites, arbres) dans la base de l'application.")
    p.add_argument("fichier", help="plan de plantation au format JSON")
    p.add_argument("--campagne", help="nom de la campagne à remplir (par défaut, celle du fichier ; créée fermée si elle n'existe pas)")
    p.add_argument("--remplacer", action="store_true",
                   help="remplacer les arbres libres de la campagne (les arbres parrainés sont conservés)")
    a = p.parse_args(argv)
    try:
        with open(a.fichier, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"Fichier illisible : {e}", file=sys.stderr)
        return 1
    con = sqlite3.connect(app.DB_PATH, timeout=10)
    con.execute("PRAGMA foreign_keys=ON")
    try:
        bilan = charger(con, plan, a.campagne, a.remplacer)
    except ErreurPlan as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        con.close()
    if bilan["creee"]:
        print(f"Campagne « {bilan['campagne']} » créée, FERMÉE : ouvrez-la dans Administration > Campagnes quand les inscriptions peuvent commencer.")
    else:
        print(f"Campagne « {bilan['campagne']} » : arbres libres retirés : {bilan['retires']} ; arbres parrainés conservés : {bilan['gardes']}.")
    print(f"Essences : {bilan['essences_creees']} créées, {bilan['essences_reprises']} déjà connues (textes et photos conservés)"
          + (f", {bilan['desactivees']} désactivées (plus aucun arbre)." if a.remplacer else "."))
    print(f"{bilan['arbres']} arbres ajoutés au stock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
