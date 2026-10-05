"""Outils partagés par les scripts du site gorria.online (bibliothèque standard uniquement)."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
DATA = RACINE / "data"
SORTIE = RACINE / "_site"
PARIS = ZoneInfo("Europe/Paris")


def log(msg: str) -> None:
    print(msg, flush=True)


def lire_json(chemin: Path, defaut=None):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defaut
    except json.JSONDecodeError as e:
        log(f"⚠ {chemin.name} illisible ({e}) : valeur par défaut utilisée")
        return defaut


def ecrire_json(chemin: Path, donnees) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def config() -> dict:
    return lire_json(DATA / "config.json", {})


def maintenant() -> dt.datetime:
    return dt.datetime.now(PARIS)


def date_iso(s: str) -> dt.datetime:
    """Lit une date ISO HelloAsso (fractions de seconde à 7 chiffres tolérées)."""
    s = s.strip().replace("Z", "+00:00")
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=PARIS)
    return d.astimezone(PARIS)


# ---------------------------------------------------------------- registre

def avertir_registre(texte: str, ou: str, interdits: list[str]) -> None:
    """Signale dans le journal les mots hors registre (on ne réécrit pas les textes des collectifs)."""
    bas = sans_accents(texte.lower())
    for mot in interdits:
        if re.search(r"(?<![a-z])" + re.escape(sans_accents(mot.lower())) + r"(?![a-z])", bas):
            log(f"⚠ registre : « {mot} » trouvé dans {ou}")


def filtrer_mots(mots: list[str], interdits: list[str]) -> list[str]:
    inter = {sans_accents(m.lower()) for m in interdits}
    return [m for m in mots if sans_accents(m.lower()) not in inter]


def sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def ascii_gorria(s: str) -> str:
    return s.replace("Я", "R").replace("я", "r")


# ---------------------------------------------------------------- soirées

def texte_brut(desc: str) -> str:
    """Description HelloAsso (texte ou HTML) -> texte simple."""
    t = re.sub(r"<\s*br\s*/?>|</p>|</div>|</li>", "\n", desc or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\r", "")
    return "\n".join(l.strip() for l in t.split("\n")).strip()


def _champ(texte: str, motif: str) -> str:
    m = re.search(r"^[^\w\n]*(?:" + motif + r")\s*:\s*(.+)$", texte, flags=re.I | re.M)
    return m.group(1).strip() if m else ""


def analyser_description(desc: str) -> dict:
    t = texte_brut(desc)
    styles = [s.strip() for s in re.split(r"\s*/\s*|\s*•\s*|,", _champ(t, r"styles?")) if s.strip()]
    lineup = [s.strip() for s in re.split(r"\s*[•·]\s*|\s*,\s*",_champ(t, r"dj'?s?\s*(?:guests?|invit[ée]s?)|line[\s-]?up")) if s.strip()]
    # le reste (paragraphe libre éventuel) sert de description longue
    autres = [l for l in t.split("\n") if l and not re.match(r"^[^\w]*(styles?|dj'?s?|line|lieu|horaires?|pa?f|tickets?|adh[ée]sion)\b", l, re.I)]
    return {"styles": styles, "lineup": lineup, "texte": "\n".join(autres).strip(), "brut": t}


def analyser_titre(titre: str) -> tuple[str, str]:
    morceaux = [p.strip() for p in re.split(r"\s*/\s*", titre) if p.strip()]
    morceaux = [p for p in morceaux if ascii_gorria(p).upper() not in {"GORRIA", "BIARRITZ", "STUDIO GORRIA"}]
    return (" · ".join(morceaux) or titre.strip()), ""


def empreinte(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def soirees_depuis_cache(cache: dict, overrides: dict, cfg: dict) -> list[dict]:
    """Construit la liste normalisée des soirées (modèle events.json)."""
    interdits = cfg.get("MOTS_INTERDITS", [])
    adr = cfg["ADRESSE"]
    res = []
    for f in cache.get("formulaires", []):
        slug = f["formSlug"]
        ov = overrides.get(slug, {}) if isinstance(overrides.get(slug), dict) else {}
        if ov.get("masquer"):
            continue
        if f.get("state") not in (None, "Public"):
            continue
        titre, _ = analyser_titre(f.get("title", slug))
        titre = ov.get("titre") or titre
        info = analyser_description(f.get("description", ""))
        avertir_registre(f.get("title", "") + "\n" + info["brut"], f"la billetterie {slug}", interdits)
        statut = ov.get("status") or f.get("_statut_auto", "") or ""
        statut = {"": "scheduled", "full": "full", "cancelled": "cancelled", "postponed": "postponed"}.get(statut, "scheduled")
        debut, fin = date_iso(f["startDate"]), date_iso(f.get("endDate") or f["startDate"])
        if fin <= debut:
            fin = debut + dt.timedelta(hours=7)
        prix = sorted({round(t["price"] / 100) for t in f.get("tiers", []) if t.get("price")})
        lineup_txt = " • ".join(info["lineup"])
        court = f"Musiques électroniques au Studio GOЯRIA. "
        if lineup_txt:
            court += f"{lineup_txt}. "
        court += f"{debut.hour}h–{fin.hour}h. Adhésion requise. +18 ans."
        if len(court) > 200:
            court = court[:197].rsplit(" ", 1)[0] + "…"
        res.append({
            "id": f"helloasso:{slug}",
            "slug": slug,
            "title": titre,
            "title_ascii": ascii_gorria(titre),
            "collective": ov.get("collectif", ""),
            "lineup": info["lineup"],
            "styles": info["styles"],
            "start": debut.isoformat(),
            "end": fin.isoformat(),
            "status": statut,
            "description_short": court,
            "description_long": info["texte"],
            "image": f.get("banner") or "",
            "ticket_url": f.get("url") or cfg.get("BILLETTERIE_URL"),
            "prices": prix,
            "age_min": 18,
            "venue": adr,
            "updated_at": f.get("updatedAt") or "",
        })
    res.sort(key=lambda e: e["start"])
    return res


def phrase_conditions(cfg: dict) -> str:
    t = cfg["TARIFS"]
    a = cfg["ADHESIONS"]
    s = (f"Entrée {t[0]['montant']} € {t[0]['detail']} · {t[1]['montant']} € {t[1]['detail']} · "
         f"{t[2]['montant']} € {t[2]['detail']}, + adhésion obligatoire ({a[0]['nom']} {a[0]['montant']} €/{a[0]['duree']} "
         f"ou {a[1]['nom'].lower()} {a[1]['montant']} €). +18 ans, pièce d'identité. Sortie définitive.")
    return s[:255]


def fr_date_longue(d: dt.datetime) -> str:
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]
    return f"{jours[d.weekday()]} {d.day}{'er' if d.day == 1 else ''} {mois[d.month - 1]} {d.year}"


def sortir(code: int) -> None:
    sys.exit(code)
