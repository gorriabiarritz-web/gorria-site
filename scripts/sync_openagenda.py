#!/usr/bin/env python3
"""
GORRIA — pousse les soirées vers OpenAgenda (agenda « Studio GOЯRIA Biarritz »).

Upsert par identifiant externe : PUT /v2/agendas/{agenda}/events/ext/helloasso/{slug}
→ jamais de doublon. Seules les soirées modifiées depuis le dernier envoi sont
renvoyées (data/openagenda_sync.json).

Interrupteur : rien n'est envoyé tant que la variable OPENAGENDA_ACTIF ne vaut
pas 1 (sinon simulation : le journal montre ce qui partirait).
Secret : OA_SECRET_KEY (clé secrète du compte, https://openagenda.com/settings/apiKey).
Identifiants agenda et lieu : data/config.json (non secrets).

Options : --simulation (force la simulation)
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from commun import (DATA, config, date_iso, ecrire_json, empreinte, filtrer_mots, lire_json, log,
                    maintenant, phrase_conditions)

API = "https://api.openagenda.com/v2"
STATUTS = {"scheduled": 1, "postponed": 4, "full": 5, "cancelled": 6}


def appel(methode: str, url: str, corps: dict | None = None, jeton: str | None = None) -> dict:
    entetes = {"Content-Type": "application/json", "Accept": "application/json", "lang": "fr"}
    if jeton:
        entetes["access-token"] = jeton
    data = json.dumps(corps).encode("utf-8") if corps is not None else None
    req = urllib.request.Request(url, data=data, headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"OpenAgenda {methode} {url.replace(API, '')} → HTTP {e.code} : {detail}")


def charge_utile(e: dict, cfg: dict) -> dict:
    debut, fin = date_iso(e["start"]), date_iso(e["end"])
    mots = filtrer_mots(["musique électronique", "techno", "DJ set", "DJ", "Biarritz", "Pays Basque"]
                        + [s for s in e["styles"]][:6], cfg.get("MOTS_INTERDITS", []))
    long = []
    if e["lineup"]:
        long.append("**DJ :** " + " • ".join(e["lineup"]))
    if e["styles"]:
        long.append("**Styles :** " + " / ".join(e["styles"]))
    if e.get("description_long"):
        long.append(e["description_long"])
    long.append(phrase_conditions(cfg))
    long.append(f"Réservation : {e['ticket_url']}\n\nAdhésion : {cfg['ADHESION_URL']}")
    titre = e["title"] + (f" ({e['collective']})" if e.get("collective") else "")
    data = {
        "title": {"fr": titre[:140]},
        "description": {"fr": e["description_short"][:200]},
        "longDescription": {"fr": "\n\n".join(long)[:10000]},
        "conditions": {"fr": phrase_conditions(cfg)[:255]},
        "keywords": {"fr": mots},
        "age": {"min": 18, "max": 99},
        "timings": [{"begin": debut.isoformat(), "end": fin.isoformat()}],
        "locationUid": cfg["OPENAGENDA"]["location_uid"],
        "attendanceMode": 1,
        "registration": [e["ticket_url"]],
        "status": STATUTS.get(e["status"], 1),
    }
    if e.get("image"):
        data["image"] = {"url": e["image"]}
        data["imageCredits"] = "Visuel du collectif"
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulation", action="store_true")
    args = ap.parse_args()

    cfg = config()
    actif = os.environ.get("OPENAGENDA_ACTIF") == "1" and not args.simulation
    cle = os.environ.get("OA_SECRET_KEY")
    if actif and not cle:
        log("OpenAgenda : non configuré (secret OA_SECRET_KEY absent) — rien à faire")
        return 0
    if not actif:
        log("OpenAgenda : SIMULATION (OPENAGENDA_ACTIF ≠ 1) — rien n'est envoyé")

    events = (lire_json(DATA / "events.json", {}) or {}).get("events", [])
    suivi = lire_json(DATA / "openagenda_sync.json", {})
    agenda = cfg["OPENAGENDA"]["agenda_uid"]
    maint = maintenant()

    jeton = None
    if actif:
        r = appel("POST", f"{API}/requestAccessToken", {"code": cle})
        jeton = r.get("access_token")
        if not jeton:
            raise SystemExit("OpenAgenda : pas de jeton d'accès (clé secrète refusée ?)")

    envoyes = 0
    for e in events:
        if date_iso(e["end"]) < maint:
            continue  # on ne réécrit pas le passé
        if "helloasso.com" not in (e.get("ticket_url") or ""):
            log(f"  · {e['slug']} : pas encore de billetterie, attend")
            continue
        corps = {"data": charge_utile(e, cfg)}
        h = empreinte(corps)
        if suivi.get(e["slug"], {}).get("empreinte") == h:
            log(f"  · {e['slug']} : inchangée")
            continue
        url = f"{API}/agendas/{agenda}/events/ext/helloasso/{e['slug']}"
        if not actif:
            log(f"  → PUT {url.replace(API, '')}")
            log("    " + json.dumps(corps["data"], ensure_ascii=False)[:900])
            continue
        r = appel("PUT", url, corps, jeton)
        uid = (r.get("event") or {}).get("uid")
        suivi[e["slug"]] = {"empreinte": h, "uid": uid, "envoye": maint.isoformat(timespec="seconds")}
        envoyes += 1
        log(f"  ✓ {e['slug']} → OpenAgenda (uid {uid})")
    if actif:
        ecrire_json(DATA / "openagenda_sync.json", suivi)
    log(f"OpenAgenda : {envoyes} soirée(s) envoyée(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
