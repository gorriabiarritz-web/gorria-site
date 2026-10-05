# Diffusion des soirées vers les agendas tiers

Une seule source : **HelloAsso**. Chaque matin (6h UTC), l'action *Mise a jour du site* :
1. fabrique la page, `agenda.ics` et le balisage schema.org (`scripts/build.py`) ;
2. envoie les soirées sur **OpenAgenda** (`scripts/sync_openagenda.py`) ;
3. publie un post « Événement » sur la **fiche Google** vers J-10 (`scripts/post_gbp.py`) ;
4. enregistre les fichiers de suivi (`data/`) et publie le site.

Les étapes 2 et 3 restent en **simulation** tant que leur interrupteur (`OPENAGENDA_ACTIF`, `GBP_ACTIF`) ne vaut pas `1`. Elles ne bloquent jamais le site.

## Tableau de bord (5/10/2026)

| # | Canal | Statut | Reste à faire |
|---|---|---|---|
| 1 | Abonnement ICS (Google, Apple, Outlook) | ✅ automatique dès la mise en ligne | Tester les 2 boutons de la section Agenda |
| 2 | OpenAgenda | ✅ agenda `9684453` et lieu `14089959` créés (5/10) | Coller `OA_SECRET_KEY`, relire une simulation, puis `OPENAGENDA_ACTIF` = 1 |
| 3 | Google Business Profile | ⏳ demande d'accès API envoyée par Cyril (5/10), projet Google Cloud `gorria-wallet` (n° 225517416852) | Attendre l'accord ; mettre `gorria.online` comme site web de la fiche ; OAuth une fois |
| 4 | Infolocale (connecteur HelloAsso) | ⏳ compte créé (5/10) | Relier HelloAsso, puis 1 clic « médiatiser » par soirée |
| 5 | Annuaire HelloAsso | ✅ automatique | Chaque billetterie publique, adresse complète |
| 6 | Wander | ✅ compte organisateur créé (5/10) | Rien |
| 7 | Mobilizon | ✖ abandonné (décision du 5/10) | — |
| + | Search Console, Bing (schema.org `MusicEvent`) | après mise en ligne | Déclarer le site, soumettre `sitemap.xml` |
| ✋ | Resident Advisor | manuel | 3 min par soirée : https://ra.co/pro/submit-event-venue.aspx |

## Abonnement ICS
- Flux : `https://gorria.online/agenda.ics` (soirées passées gardées 30 jours).
- Boutons : `webcal://gorria.online/agenda.ics` (iPhone, Mac, Outlook) et Google Agenda.
- `UID` stable `<slug>@gorria.online`, `SEQUENCE` +1 à chaque changement (`data/agenda_etat.json`), `STATUS:CANCELLED` si annulée, ` — COMPLET` dans le titre si complet.

## OpenAgenda
- Agenda : https://openagenda.com/studio-gorria-biarritz (contribution réduite, publication directe).
- Upsert `PUT /v2/agendas/9684453/events/ext/helloasso/<slug>` : jamais de doublon. Seules les soirées modifiées repartent (`data/openagenda_sync.json`).
- Clé : https://openagenda.com/settings/apiKey → secret `OA_SECRET_KEY`.
- Plus tard : proposer à l'OT (sirtaqui@tourisme64.com) de reprendre l'agenda dans SIRTAQUI.

## Google Business Profile
- Un post par soirée, au passage de J-10 (rattrapage jusqu'à J-1). Trace : `data/gbp_posted.json`.
- Après accord de Google : client OAuth, autorisation par Cyril, 5 secrets `GBP_*`, simulation, puis `GBP_ACTIF` = 1.
- Catégorie conseillée de la fiche : « Salle de concert » ou « Association culturelle ».

## Registre éditorial
Jamais « club », « boîte », « clubbing », « fête libre », « free party » ni « rave ». À la place : musiques électroniques, DJ set, tiers-lieu culturel, communauté.
