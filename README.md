# gorria.online

Site mono-page du Studio GOЯRIA (association Sound Makers), mis à jour tout seul chaque matin depuis HelloAsso.

| Fichier | Rôle |
|---|---|
| `data/config.json` | Réglages : adresse, tarifs, adhésions, liens (WhatsApp, YouTube…), identifiants OpenAgenda |
| `data/overrides.json` | Corrections par soirée : complet, annulée, reportée, titre, masquer |
| `templates/index.html` | Gabarit de la page |
| `scripts/build.py` | Fabrique `_site/` : page, `agenda.ics`, `events.json`, `sitemap.xml`, `/whatsapp`, `/adhesion` |
| `scripts/sync_openagenda.py` | Envoie les soirées sur OpenAgenda |
| `scripts/post_gbp.py` | Post « Événement » sur la fiche Google, à J-10 |
| `.github/workflows/update.yml` | Tous les jours à 6h UTC + après chaque modification |
| `docs/AGENDAS-TIERS.md` | Diffusion vers les agendas tiers : état et actions |

## Changer une soirée
Ouvre `data/overrides.json` sur GitHub (crayon), ajoute la soirée par la fin de son adresse HelloAsso :

```json
"night-pulse-dopamine-gorria-biarritz": { "status": "full" }
```

`full` = complet · `cancelled` = annulée · `postponed` = reportée · `""` = normal. Valide (« Commit changes ») : le site, l'agenda et OpenAgenda suivent en 2 minutes.

## Secrets et interrupteurs (Settings › Secrets and variables › Actions)
| Nom | Type | Rôle |
|---|---|---|
| `HELLOASSO_CLIENT_ID`, `HELLOASSO_CLIENT_SECRET` | secrets | lecture des billetteries |
| `OA_SECRET_KEY` | secret | OpenAgenda |
| `OPENAGENDA_ACTIF` | variable | `1` = envoi réel (sinon simulation) |
| `GBP_CLIENT_ID`, `GBP_CLIENT_SECRET`, `GBP_REFRESH_TOKEN`, `GBP_ACCOUNT_ID`, `GBP_LOCATION_ID` | secrets | fiche Google |
| `GBP_ACTIF` | variable | `1` = publication réelle (sinon simulation) |

Registre éditorial : jamais « club », « boîte », « clubbing », « fête libre », « free party » ni « rave ». Les scripts les retirent des mots-clés et signalent leur présence dans le journal.
