<p align="center"><img src="assets/logo.png" width="96" alt="SwiftRift logo"></p>

# SwiftRift Data

Hosted meta data for SwiftRift (macOS League of Legends companion): tier lists, builds,
matchups and per-tier benchmarks, aggregated from ranked solo/duo matches through the Riot API.

The app downloads `manifest.json`, then only the files it needs, through jsDelivr:

```
https://cdn.jsdelivr.net/gh/lucentxo/SwiftRift-Data@main/manifest.json
https://cdn.jsdelivr.net/gh/lucentxo/SwiftRift-Data@main/data/<patch>/tierlist/emerald_plus.json
```

## Layout

| Path | Contents |
|---|---|
| `manifest.json` | Schema version, patch, generation time, sample size, and every file with its SHA-256 |
| `data/<patch>/tierlist/<bracket>.json` | Champion × role win/pick/ban rates and S+…D tiers. Brackets: `all`, `emerald_plus`, `diamond_plus`, `master_plus` |
| `data/<patch>/builds/<Champion>.json` | Per role: top builds (item path, runes, spells, skill order) |
| `data/<patch>/matchups/<Champion>.json` | Per role: lane opponents with win rate and gold difference at 15 |
| `data/<patch>/benchmarks/<TIER>.json` | Per role averages: gold/min, CS/min, KP, vision/min, damage share, deaths, level by minute |
| `state/` | Compact match records and seen match IDs, so each run builds on the last |

## Updating without the app

- **Automatically:** `.github/workflows/update.yml` runs every 6 hours. It crawls new matches, re-aggregates and commits.
- **On demand:** Actions › *Update meta data* › *Run workflow*. Set a request budget, or choose *aggregate only*.
- **Locally:** `RIOT_API_KEY=... python3 pipeline/crawl.py --max-requests 900`, then commit and push.
- **By hand:** edit any JSON file and commit. Run `python3 pipeline/crawl.py --aggregate-only` to refresh the manifest hashes.

The Riot API key is the `RIOT_API_KEY` repository secret. Development keys expire every 24 hours; a production key
(apply at developer.riotgames.com) is needed for unattended updates and higher rate limits.

---

SwiftRift isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
