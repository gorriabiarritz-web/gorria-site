#!/usr/bin/env python3
"""
GORRIA — fabrique le site gorria.online (dossier _site/).

1. Lit les billetteries publiques sur l'API HelloAsso (si HELLOASSO_CLIENT_ID et
   HELLOASSO_CLIENT_SECRET sont fournis) et met à jour data/helloasso_cache.json.
   Sans identifiants, ou si HelloAsso ne répond pas : le cache est utilisé.
2. Applique data/overrides.json (complet, annulée, reportée, titre, masquer).
3. Écrit dans _site/ : index.html, events.json, agenda.ics, sitemap.xml,
   robots.txt, CNAME, whatsapp/index.html, 404.html.

Options :
  --hors-ligne   n'interroge pas HelloAsso (cache seulement)
  --date AAAA-MM-JJ   fait comme si on était ce jour-là (tests)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import shutil
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from commun import (DATA, PARIS, RACINE, SORTIE, config, date_iso, ecrire_json, empreinte,
                    fr_date_longue, lire_json, log, maintenant, phrase_conditions,
                    soirees_depuis_cache)

API = "https://api.helloasso.com"
GARDER_PASSEES_JOURS = 30


# ------------------------------------------------------------------ HelloAsso

def _requete(url: str, data: bytes | None = None, jeton: str | None = None, essais: int = 3) -> dict:
    import time
    entetes = {"Accept": "application/json", "User-Agent": "gorria-site/1.0"}
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    if data is not None:
        entetes["Content-Type"] = "application/x-www-form-urlencoded"
    derniere = None
    for i in range(essais):
        try:
            req = urllib.request.Request(url, data=data, headers=entetes)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # réseau, 5xx, JSON
            derniere = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"HelloAsso injoignable ({url.split('?')[0]}) : {derniere}")


def lire_helloasso(cfg: dict, cache: dict) -> dict:
    cid, csec = os.environ.get("HELLOASSO_CLIENT_ID"), os.environ.get("HELLOASSO_CLIENT_SECRET")
    if not (cid and csec):
        log("HelloAsso : identifiants absents → données du cache (" + cache.get("lu_le", "?") + ")")
        return cache
    org = cfg.get("HELLOASSO_ORGANISATION", "sound-makers")
    try:
        tok = _requete(f"{API}/oauth2/token", urllib.parse.urlencode(
            {"grant_type": "client_credentials", "client_id": cid, "client_secret": csec}).encode())["access_token"]
        limite = (maintenant() - dt.timedelta(days=GARDER_PASSEES_JOURS)).isoformat()
        formulaires, page = [], 1
        while page <= 10:
            q = urllib.parse.urlencode({"formTypes": "Event", "states": "Public", "pageSize": 50, "pageIndex": page})
            j = _requete(f"{API}/v5/organizations/{org}/forms?{q}", jeton=tok)
            data = j.get("data") or []
            formulaires += data
            if len(data) < 50:
                break
            page += 1
        retenus = []
        for f in formulaires:
            if not f.get("startDate") or date_iso(f["startDate"]).isoformat() < limite:
                continue
            titre = (f.get("title") or "").upper().replace("Я", "R")
            if "GORRIA" not in titre:
                continue  # autres billetteries de l'association
            d = _requete(f"{API}/v5/organizations/{org}/forms/Event/{f['formSlug']}/public", jeton=tok)
            retenus.append({
                "formSlug": f["formSlug"],
                "title": d.get("title") or f.get("title"),
                "startDate": d.get("startDate") or f["startDate"],
                "endDate": d.get("endDate") or f.get("endDate"),
                "state": d.get("state") or f.get("state"),
                "url": d.get("url") or f.get("url"),
                "banner": (d.get("banner") or {}).get("publicUrl") or (f.get("banner") or {}).get("publicUrl", ""),
                "description": d.get("description") or f.get("description") or "",
                "tiers": [{"label": t.get("label"), "price": t.get("price")} for t in d.get("tiers") or []],
                "updatedAt": (d.get("meta") or {}).get("updatedAt", ""),
            })
        nouveau = {"_doc": cache.get("_doc", ""), "lu_le": maintenant().isoformat(timespec="seconds"),
                   "source": "API HelloAsso v5", "formulaires": retenus}
        ecrire_json(DATA / "helloasso_cache.json", nouveau)
        log(f"HelloAsso : {len(retenus)} billetterie(s) GOЯRIA lue(s)")
        return nouveau
    except Exception as e:
        log(f"⚠ {e} → données du cache conservées")
        return cache


# ------------------------------------------------------------------ ICS

def _ics_txt(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _plier(ligne: str) -> list[str]:
    """Pliage RFC 5545 : 75 octets max, sans couper un caractère UTF-8."""
    sortie, courant, taille = [], "", 0
    for c in ligne:
        n = len(c.encode("utf-8"))
        limite = 75 if not sortie else 74
        if taille + n > limite:
            sortie.append(courant)
            courant, taille = c, n
        else:
            courant += c
            taille += n
    sortie.append(courant)
    return [sortie[0]] + [" " + s for s in sortie[1:]]


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Paris
X-LIC-LOCATION:Europe/Paris
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def faire_ics(soirees: list[dict], cfg: dict, etat: dict, maint: dt.datetime) -> str:
    adr = cfg["ADRESSE"]
    lieu = f"{adr['nom']}, {adr['rue']}, {adr['code_postal']} {adr['ville']}"
    utc = dt.timezone.utc
    stamp = maint.astimezone(utc).strftime("%Y%m%dT%H%M%SZ")
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Sound Makers//Studio GORRIA//FR",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Soirées Studio GOЯRIA",
              "X-WR-TIMEZONE:Europe/Paris",
              "X-WR-CALDESC:Les soirées du Studio GOЯRIA\\, tiers-lieu culturel des musiques électroniques à Biarritz",
              "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"] + VTIMEZONE
    for e in soirees:
        # SEQUENCE : +1 à chaque changement de contenu
        contenu = {k: e[k] for k in ("title", "start", "end", "status", "lineup", "styles", "ticket_url", "image")}
        h = empreinte(contenu)
        st = etat.get(e["slug"])
        if not st:
            st = {"empreinte": h, "sequence": 0, "modifie": stamp}
        elif st.get("empreinte") != h:
            st = {"empreinte": h, "sequence": st.get("sequence", 0) + 1, "modifie": stamp}
        etat[e["slug"]] = st
        debut, fin = date_iso(e["start"]), date_iso(e["end"])
        titre = f"GOЯRIA · {e['title']}"
        if e.get("collective"):
            titre += f" ({e['collective']})"
        if e["status"] == "full":
            titre += " — COMPLET"
        elif e["status"] == "postponed":
            titre += " — REPORTÉE"
        desc = []
        if e["lineup"]:
            desc.append("DJ : " + " • ".join(e["lineup"]))
        if e["styles"]:
            desc.append("Styles : " + " / ".join(e["styles"]))
        desc.append(phrase_conditions(cfg))
        desc.append("Réservation : " + e["ticket_url"])
        desc.append("Adhésion : " + cfg["ADHESION_URL"])
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{e['slug']}@gorria.online",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{st['modifie']}",
            f"SEQUENCE:{st['sequence']}",
            f"DTSTART;TZID=Europe/Paris:{debut:%Y%m%dT%H%M%S}",
            f"DTEND;TZID=Europe/Paris:{fin:%Y%m%dT%H%M%S}",
            "SUMMARY:" + _ics_txt(titre),
            "DESCRIPTION:" + _ics_txt("\n".join(desc)),
            "LOCATION:" + _ics_txt(lieu),
            f"GEO:{adr['lat']};{adr['lng']}",
            "URL:" + e["ticket_url"],
            "CATEGORIES:Musique électronique,DJ set,Techno",
            "STATUS:" + ("CANCELLED" if e["status"] == "cancelled" else "CONFIRMED"),
            "TRANSP:OPAQUE",
        ]
        if e.get("image"):
            lignes += [f"IMAGE;VALUE=URI;DISPLAY=BADGE:{e['image']}", f"ATTACH:{e['image']}"]
        lignes.append("END:VEVENT")
    lignes.append("END:VCALENDAR")
    pliees = []
    for l in lignes:
        pliees += _plier(l)
    return "\r\n".join(pliees) + "\r\n"


# ------------------------------------------------------------------ HTML

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def carte_soiree(e: dict, cfg: dict) -> str:
    d = date_iso(e["start"])
    fin = date_iso(e["end"])
    jours = ["LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM"]
    mois = ["JANV", "FÉVR", "MARS", "AVR", "MAI", "JUIN", "JUIL", "AOÛT", "SEPT", "OCT", "NOV", "DÉC"]
    badge = {"full": '<span class="badge">Complet</span>', "cancelled": '<span class="badge">Annulée</span>',
             "postponed": '<span class="badge">Reportée</span>'}.get(e["status"], "")
    img = (f'<img src="{esc(e["image"])}" alt="Visuel de la soirée {esc(e["title"])}" loading="lazy" '
           f'width="1200" height="630">') if e.get("image") else '<div class="img-vide" aria-hidden="true">GOЯRIA</div>'
    lineup = " • ".join(esc(x) for x in e["lineup"]) or "Line-up à venir"
    styles = " / ".join(esc(x) for x in e["styles"])
    bouton = ('<a class="btn" href="{u}" rel="noopener">Réserver</a>'.format(u=esc(e["ticket_url"]))
              if e["status"] not in ("cancelled", "full") else "")
    return f"""
      <article class="soiree{' soiree--off' if e['status'] in ('cancelled',) else ''}">
        <div class="soiree__img">{img}</div>
        <div class="soiree__corps">
          <p class="soiree__date"><time datetime="{esc(e['start'])}"><b>{jours[d.weekday()]} {d.day} {mois[d.month-1]}</b> · {d.hour}h › {fin.hour}h</time> {badge}</p>
          <h3>{esc(e['title'])}</h3>
          <p class="soiree__lineup">{lineup}</p>
          {f'<p class="soiree__styles">{styles}</p>' if styles else ''}
          <div class="soiree__actions">{bouton}<a class="lien" href="{esc(e['ticket_url'])}" rel="noopener">Infos</a></div>
        </div>
      </article>"""


# ------------------------------------------------------------------ YouTube (flux RSS)

YT_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
NB_VIDEOS = 6


def url_flux_youtube(cfg: dict) -> str:
    """Flux Atom public des vidéos longues de la chaîne (playlist UULF = sans les Shorts)."""
    return "https://www.youtube.com/feeds/videos.xml?playlist_id=" + cfg.get("YOUTUBE_FLUX_PLAYLIST", "UULFxc4rj6lfImrX5L4ztpcJSw")


def lire_youtube(cfg: dict, hors_ligne: bool = False) -> list[dict]:
    """Lit les dernières vidéos de la chaîne. En cas d'échec : data/youtube_cache.json."""
    cache = lire_json(DATA / "youtube_cache.json", {}) or {}
    if hors_ligne:
        return cache.get("videos", [])
    url = url_flux_youtube(cfg)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gorria-site/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            racine = ET.fromstring(r.read())
        videos = []
        for e in racine.findall("a:entry", YT_NS):
            vid = e.findtext("yt:videoId", "", YT_NS).strip()
            if vid:
                videos.append({"id": vid, "titre": e.findtext("a:title", "", YT_NS).strip(),
                               "publie": e.findtext("a:published", "", YT_NS).strip()})
        if not videos:
            raise RuntimeError("flux vide")
        if videos != cache.get("videos"):
            ecrire_json(DATA / "youtube_cache.json", {
                "_doc": "Dernières vidéos longues de la chaîne YouTube (écrit par scripts/build.py).",
                "lu_le": maintenant().isoformat(timespec="seconds"), "source": url, "videos": videos})
        log(f"YouTube : {len(videos)} vidéo(s) dans le flux")
        return videos
    except Exception as ex:
        log(f"⚠ YouTube : flux illisible ({ex}) → cache conservé")
        return cache.get("videos", [])


def carte_video(v: dict) -> str:
    """Titre type « Style | DJ 🇫🇷 | Studio GoЯRia Biarritz | Mois Année »."""
    morceaux = [m.strip() for m in v["titre"].split("|") if m.strip()]
    style = morceaux[0] if len(morceaux) > 1 else ""
    dj = morceaux[1] if len(morceaux) > 1 else v["titre"]
    quand = morceaux[-1] if len(morceaux) > 2 else ""
    lien = "https://www.youtube.com/watch?v=" + v["id"]
    vignette = f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"
    return f"""
      <a class="video" href="{esc(lien)}" rel="noopener">
        <div class="video__img"><img src="{esc(vignette)}" alt="Set {esc(dj)} au Studio GOЯRIA" loading="lazy" width="480" height="360"><span class="video__play" aria-hidden="true">▶</span></div>
        <div class="video__corps">
          {f'<p class="video__style">{esc(style)}</p>' if style else ''}
          <h3>{esc(dj)}</h3>
          {f'<p class="video__date">{esc(quand)}</p>' if quand else ''}
        </div>
      </a>"""


def cartes_videos(videos: list[dict]) -> str:
    if not videos:
        return '<p class="vide">Les sets sont sur notre chaîne YouTube.</p>'
    return "\n".join(carte_video(v) for v in videos[:NB_VIDEOS])


def jsonld(soirees: list[dict], cfg: dict) -> str:
    adr = cfg["ADRESSE"]
    lieu = {"@type": "MusicVenue", "name": adr["nom"], "url": cfg["SITE_URL"],
            "address": {"@type": "PostalAddress", "streetAddress": adr["rue"], "postalCode": adr["code_postal"],
                        "addressLocality": adr["ville"], "addressCountry": adr["pays"]},
            "geo": {"@type": "GeoCoordinates", "latitude": adr["lat"], "longitude": adr["lng"]}}
    org = {"@type": "Organization", "name": f"{cfg['ASSOCIATION']['nom']} — {cfg['NOM']}", "url": cfg["SITE_URL"],
           "sameAs": [cfg["INSTAGRAM_URL"], cfg["FACEBOOK_URL"], cfg["YOUTUBE_URL"], cfg["TIKTOK_URL"]]}
    statut = {"scheduled": "EventScheduled", "full": "EventScheduled", "cancelled": "EventCancelled",
              "postponed": "EventPostponed"}
    graphe = [dict(lieu, **{"@id": cfg["SITE_URL"] + "/#lieu"}), dict(org, **{"@id": cfg["SITE_URL"] + "/#organisation"})]
    for e in soirees:
        graphe.append({
            "@type": "MusicEvent", "name": e["title"],
            "startDate": e["start"], "endDate": e["end"],
            "eventStatus": "https://schema.org/" + statut.get(e["status"], "EventScheduled"),
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@id": cfg["SITE_URL"] + "/#lieu"},
            "organizer": {"@id": cfg["SITE_URL"] + "/#organisation"},
            "image": [e["image"]] if e.get("image") else [],
            "description": e["description_short"],
            "performer": [{"@type": "Person", "name": n} for n in e["lineup"]],
            "typicalAgeRange": "18-",
            "url": e["ticket_url"],
            "offers": [{"@type": "Offer", "name": t["nom"], "price": t["montant"], "priceCurrency": "EUR",
                        "url": e["ticket_url"],
                        "availability": "https://schema.org/" + ("SoldOut" if e["status"] == "full" else "InStock")}
                       for t in cfg["TARIFS"]],
        })
    return json.dumps({"@context": "https://schema.org", "@graph": graphe}, ensure_ascii=False, indent=1).replace("</", "<\\/")


def faire_index(soirees_a_venir: list[dict], cfg: dict, maint: dt.datetime, videos: list[dict] | None = None) -> str:
    gabarit = (RACINE / "templates" / "index.html").read_text(encoding="utf-8")
    if soirees_a_venir:
        cartes = "\n".join(carte_soiree(e, cfg) for e in soirees_a_venir)
    else:
        cartes = ('<p class="vide">Les prochaines dates arrivent bientôt. Abonne-toi à l\'agenda ou rejoins la '
                  'communauté WhatsApp pour être prévenu·e.</p>')
    prochaine = soirees_a_venir[0] if soirees_a_venir else None
    og_image = (prochaine or {}).get("image") or ""
    t, a = cfg["TARIFS"], cfg["ADHESIONS"]
    domaine = cfg["SITE_URL"].replace("https://", "")
    remplacements = {
        "{{SITE_URL}}": cfg["SITE_URL"],
        "{{ACCROCHE}}": esc(cfg["ACCROCHE"]),
        "{{CARTES_SOIREES}}": cartes,
        "{{CARTES_VIDEOS}}": cartes_videos(videos or []),
        "{{YOUTUBE_RSS_URL}}": esc(url_flux_youtube(cfg)),
        "{{JSONLD}}": jsonld(soirees_a_venir, cfg),
        "{{OG_IMAGE}}": esc(og_image),
        "{{ICS_WEBCAL}}": f"webcal://{domaine}/agenda.ics",
        "{{ICS_GOOGLE}}": "https://calendar.google.com/calendar/r?cid=" + urllib.parse.quote(f"webcal://{domaine}/agenda.ics", safe=""),
        "{{ICS_URL}}": f"{cfg['SITE_URL']}/agenda.ics",
        "{{ADRESSE_RUE}}": esc(cfg["ADRESSE"]["rue"]),
        "{{ADRESSE_VILLE}}": esc(f"{cfg['ADRESSE']['code_postal']} {cfg['ADRESSE']['ville']}"),
        "{{ITINERAIRE_URL}}": esc(cfg["ITINERAIRE_URL"]),
        "{{HORAIRES}}": esc(cfg["HORAIRES"]),
        "{{T1}}": str(t[0]["montant"]), "{{T1D}}": esc(t[0]["detail"]),
        "{{T2}}": str(t[1]["montant"]), "{{T2D}}": esc(t[1]["detail"]),
        "{{T3}}": str(t[2]["montant"]), "{{T3D}}": esc(t[2]["detail"]),
        "{{A1}}": str(a[0]["montant"]), "{{A1D}}": esc(a[0]["duree"]),
        "{{A2}}": str(a[1]["montant"]), "{{A2D}}": esc(a[1]["duree"]),
        "{{ADHESION_URL}}": esc(cfg["ADHESION_URL"]),
        "{{BILLETTERIE_URL}}": esc(cfg["BILLETTERIE_URL"]),
        "{{PROPOSER_URL}}": esc(cfg["PROPOSER_URL"]),
        "{{BENEVOLAT_URL}}": esc(cfg["BENEVOLAT_URL"]),
        "{{WHATSAPP_URL}}": esc(cfg["WHATSAPP_URL"]),
        "{{YOUTUBE_URL}}": esc(cfg["YOUTUBE_URL"]),
        "{{YOUTUBE_ABONNEMENT_URL}}": esc(cfg["YOUTUBE_ABONNEMENT_URL"]),
        "{{YOUTUBE_PODCASTS_URL}}": esc(cfg["YOUTUBE_PODCASTS_URL"]),
        "{{NB_SETS}}": esc(cfg["NB_SETS"]),
        "{{INSTAGRAM_URL}}": esc(cfg["INSTAGRAM_URL"]),
        "{{FACEBOOK_URL}}": esc(cfg["FACEBOOK_URL"]),
        "{{TIKTOK_URL}}": esc(cfg["TIKTOK_URL"]),
        "{{OPENAGENDA_URL}}": esc(cfg["OPENAGENDA"]["url"]),
        "{{EMAIL}}": esc(cfg["EMAIL"]),
        "{{ASSO_NOM}}": esc(cfg["ASSOCIATION"]["nom"]),
        "{{ASSO_SIEGE}}": esc(cfg["ASSOCIATION"]["siege"]),
        "{{ASSO_SIRET}}": esc(cfg["ASSOCIATION"]["siret"]),
        "{{ANNEE}}": str(maint.year),
        "{{MAJ}}": esc(fr_date_longue(maint)),
    }
    for k, v in remplacements.items():
        gabarit = gabarit.replace(k, v)
    reste = [m for m in set(__import__("re").findall(r"\{\{[A-Z0-9_]+\}\}", gabarit))]
    if reste:
        raise SystemExit(f"Gabarit : variables non remplacées {reste}")
    return gabarit


def page_redirection(cible: str, titre: str) -> str:
    c = esc(cible)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{esc(titre)}</title><meta http-equiv="refresh" content="0; url={c}">
<style>body{{background:#000;color:#fff;font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px;text-align:center}}a{{color:#ff3b3b}}</style>
</head><body><p>Redirection vers {esc(titre)}…<br><a href="{c}">Continuer</a></p>
<script>location.replace({json.dumps(cible)});</script></body></html>"""


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hors-ligne", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()

    cfg = config()
    maint = maintenant()
    if args.date:
        maint = dt.datetime.fromisoformat(args.date).replace(hour=8, tzinfo=PARIS)

    cache = lire_json(DATA / "helloasso_cache.json", {"formulaires": []})
    if not args.hors_ligne:
        cache = lire_helloasso(cfg, cache)
    overrides = lire_json(DATA / "overrides.json", {})
    toutes = soirees_depuis_cache(cache, overrides, cfg)

    limite_passe = maint - dt.timedelta(days=GARDER_PASSEES_JOURS)
    agenda = [e for e in toutes if date_iso(e["end"]) >= limite_passe]
    a_venir = [e for e in toutes if date_iso(e["end"]) >= maint]

    if SORTIE.exists():
        shutil.rmtree(SORTIE)
    SORTIE.mkdir(parents=True)
    if (RACINE / "static").exists():
        shutil.copytree(RACINE / "static", SORTIE, dirs_exist_ok=True)

    etat = lire_json(DATA / "agenda_etat.json", {})
    (SORTIE / "agenda.ics").write_bytes(faire_ics(agenda, cfg, etat, maint).encode("utf-8"))
    ecrire_json(DATA / "agenda_etat.json", etat)

    ecrire_json(SORTIE / "events.json", {"genere_le": maint.isoformat(timespec="seconds"),
                                         "conditions": phrase_conditions(cfg), "events": agenda})
    ecrire_json(DATA / "events.json", {"genere_le": maint.isoformat(timespec="seconds"), "events": agenda})

    videos = lire_youtube(cfg, args.hors_ligne)
    (SORTIE / "index.html").write_text(faire_index(a_venir, cfg, maint, videos), encoding="utf-8")
    (SORTIE / "whatsapp").mkdir()
    (SORTIE / "whatsapp" / "index.html").write_text(page_redirection(cfg["WHATSAPP_URL"], "la communauté WhatsApp GOЯRIA"), encoding="utf-8")
    (SORTIE / "adhesion").mkdir()
    (SORTIE / "adhesion" / "index.html").write_text(page_redirection(cfg["ADHESION_URL"], "l'adhésion HelloAsso"), encoding="utf-8")
    (SORTIE / "CNAME").write_text(cfg["SITE_URL"].replace("https://", "") + "\n", encoding="utf-8")
    (SORTIE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {cfg['SITE_URL']}/sitemap.xml\n", encoding="utf-8")
    (SORTIE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{cfg['SITE_URL']}/</loc><lastmod>{maint:%Y-%m-%d}</lastmod><changefreq>daily</changefreq></url>\n"
        "</urlset>\n", encoding="utf-8")
    (SORTIE / ".nojekyll").write_text("", encoding="utf-8")

    log(f"Site fabriqué : {len(a_venir)} soirée(s) à venir, {len(agenda)} dans l'agenda.ics")
    for e in a_venir:
        log(f"  · {e['start'][:16]}  {e['title']}  [{e['status']}]  {' • '.join(e['lineup'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
