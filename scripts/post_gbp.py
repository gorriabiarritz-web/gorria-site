#!/usr/bin/env python3
"""
GORRIA — publie un post « Événement » sur la fiche Google « Studio GOЯRIA Biarritz ».

Un seul post par soirée, au passage quotidien de J-10 (fenêtre J-10 → J-1 pour
rattraper un jour manqué). Trace : data/gbp_posted.json (supprimer une ligne
pour republier une soirée). Les soirées annulées ne sont jamais publiées.

Interrupteur : rien n'est publié tant que la variable GBP_ACTIF ne vaut pas 1.
Secrets : GBP_CLIENT_ID, GBP_CLIENT_SECRET, GBP_REFRESH_TOKEN, GBP_ACCOUNT_ID, GBP_LOCATION_ID
(disponibles seulement après l'accord de Google pour l'API Business Profile).

Options : --simulation, --date AAAA-MM-JJ (fait comme si on était ce jour-là)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from commun import DATA, PARIS, config, date_iso, ecrire_json, lire_json, log, maintenant

J_MAX, J_MIN = 10, 1
SECRETS = ("GBP_CLIENT_ID", "GBP_CLIENT_SECRET", "GBP_REFRESH_TOKEN", "GBP_ACCOUNT_ID", "GBP_LOCATION_ID")


def jeton() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["GBP_CLIENT_ID"], "client_secret": os.environ["GBP_CLIENT_SECRET"],
        "refresh_token": os.environ["GBP_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def corps_post(e: dict, cfg: dict) -> dict:
    d, f = date_iso(e["start"]), date_iso(e["end"])
    titre = e["title"]
    if len(titre) > 58:
        titre = titre[:57].rstrip() + "…"
    lignes = []
    if e["lineup"]:
        lignes.append("🎧 " + " • ".join(e["lineup"]))
    if e["styles"]:
        lignes.append("🔈 " + " / ".join(e["styles"]))
    t = cfg["TARIFS"]
    lignes.append(f"⏰ {d.hour}h › {f.hour}h · PAF Early {t[0]['montant']} € {t[0]['detail']}, puis {t[1]['montant']} € / {t[2]['montant']} €")
    lignes.append(f"👤 Adhésion obligatoire (dès {cfg['ADHESIONS'][0]['montant']} €) · +18 ans, pièce d'identité")
    lignes.append(f"🎟️ PAF en prévente : {e['ticket_url']}")
    corps = {
        "languageCode": "fr",
        "topicType": "EVENT",
        "summary": "\n".join(lignes)[:1500],
        "event": {
            "title": titre,
            "schedule": {
                "startDate": {"year": d.year, "month": d.month, "day": d.day},
                "startTime": {"hours": d.hour, "minutes": d.minute},
                "endDate": {"year": f.year, "month": f.month, "day": f.day},
                "endTime": {"hours": f.hour, "minutes": f.minute},
            },
        },
    }
    if e.get("image"):
        corps["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": e["image"]}]
    return corps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulation", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()

    cfg = config()
    maint = maintenant()
    if args.date:
        maint = dt.datetime.fromisoformat(args.date).replace(hour=8, tzinfo=PARIS)
    actif = os.environ.get("GBP_ACTIF") == "1" and not args.simulation
    manquants = [s for s in SECRETS if not os.environ.get(s)]
    if actif and manquants:
        log("Google Business Profile : non configuré (" + ", ".join(manquants) + ") — rien à faire")
        return 0
    if not actif:
        log("Google Business Profile : SIMULATION (GBP_ACTIF ≠ 1) — rien n'est publié")

    events = (lire_json(DATA / "events.json", {}) or {}).get("events", [])
    faits = lire_json(DATA / "gbp_posted.json", {})
    tok = jeton() if actif else None
    publies = 0
    for e in events:
        if e["status"] == "cancelled" or e["slug"] in faits:
            continue
        jours = (date_iso(e["start"]).date() - maint.date()).days
        if jours > J_MAX + 2 or jours < J_MIN:
            continue
        if jours > J_MAX:
            log(f"  · {e['slug']} : annoncée pour J-{J_MAX} (dans {jours - J_MAX} jour(s))")
            continue
        corps = corps_post(e, cfg)
        if not actif:
            log(f"  → post « {corps['event']['title']} » (J-{jours})")
            log("    " + json.dumps(corps, ensure_ascii=False)[:900])
            continue
        url = (f"https://mybusiness.googleapis.com/v4/accounts/{os.environ['GBP_ACCOUNT_ID']}"
               f"/locations/{os.environ['GBP_LOCATION_ID']}/localPosts")
        req = urllib.request.Request(url, data=json.dumps(corps).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                rep = json.loads(r.read())
        except urllib.error.HTTPError as err:
            log(f"  ✗ {e['slug']} : HTTP {err.code} {err.read().decode('utf-8', 'replace')[:500]}")
            continue
        faits[e["slug"]] = {"post": rep.get("name"), "le": maint.isoformat(timespec="seconds")}
        publies += 1
        log(f"  ✓ {e['slug']} publiée sur la fiche Google")
    if actif:
        ecrire_json(DATA / "gbp_posted.json", faits)
    log(f"Google Business Profile : {publies} post(s) publié(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
