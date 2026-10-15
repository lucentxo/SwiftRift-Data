"""SwiftRift data pipeline: crawl ranked matches, aggregate them and publish JSON.

Usage: RIOT_API_KEY=... python3 pipeline/crawl.py [--max-requests 900] [--platform na1] [--aggregate-only]

State lives in state/ (compact match records, gzipped JSONL per patch, plus the seen-ID list),
so every run adds to what earlier runs collected. Output goes to data/<patch>/ and manifest.json.
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import aggregate  # noqa: E402
from ddragon import StaticData  # noqa: E402
from riot import RiotClient  # noqa: E402
from summarize import summarize  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE = os.path.join(ROOT, "state")
DATA = os.path.join(ROOT, "data")
SCHEMA_VERSION = 1
CRAWL_TIERS = [("CHALLENGER", "I"), ("GRANDMASTER", "I"), ("MASTER", "I"), ("DIAMOND", "I"), ("DIAMOND", "III"),
               ("EMERALD", "I"), ("EMERALD", "III"), ("PLATINUM", "II"), ("GOLD", "II"), ("SILVER", "II"),
               ("BRONZE", "II"), ("IRON", "II")]


def load_json(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(value, handle, separators=(",", ":"), sort_keys=True)


def records_path(patch):
    return os.path.join(STATE, "records-{}.jsonl.gz".format(patch))


def load_records(patch):
    try:
        with gzip.open(records_path(patch), "rt") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []


def crawl(client, static, max_requests, max_hours):
    seen = set(load_json(os.path.join(STATE, "seen.json"), []))
    deadline = time.time() + max_hours * 3600
    week_ago = time.time() - 7 * 86400
    new_records = 0

    # Seed players from every tier so benchmarks cover the whole ladder; weight toward Emerald+.
    players = []
    for tier, division in CRAWL_TIERS:
        entries = client.league_entries(tier, division)
        random.shuffle(entries)
        take = 40 if tier in ("EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER") else 12
        players += [(e["puuid"], tier) for e in entries[:take] if e.get("puuid")]
    random.shuffle(players)

    with gzip.open(records_path(static.patch), "at") as out:
        for puuid, tier in players:
            if client.requests >= max_requests or time.time() > deadline:
                break
            for match_id in client.match_ids(puuid, start_time=week_ago, count=5):
                if match_id in seen or client.requests + 2 > max_requests:
                    continue
                seen.add(match_id)
                match = client.match(match_id)
                if not match or not match["info"]["gameVersion"].startswith(static.patch + "."):
                    continue
                record = summarize(match, client.timeline(match_id), static, tier)
                if record:
                    out.write(json.dumps(record, separators=(",", ":")) + "\n")
                    new_records += 1
    write_json(os.path.join(STATE, "seen.json"), sorted(seen)[-200_000:])
    return new_records


def publish(static):
    records = load_records(static.patch)
    out_dir = os.path.join(DATA, static.patch)
    files = {}

    def emit(relative, value):
        path = os.path.join(out_dir, relative)
        write_json(path, value)
        with open(path, "rb") as handle:
            body = handle.read()
        files["data/{}/{}".format(static.patch, relative)] = {"path": "data/{}/{}".format(static.patch, relative),
                                                             "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}

    previous_patch = _previous_patch(static.patch)
    for bracket in aggregate.BRACKETS:
        previous = load_json(os.path.join(DATA, previous_patch, "tierlist", bracket + ".json"), None) if previous_patch else None
        table = aggregate.tier_list(records, bracket, previous)
        bans = table.pop("_bans")
        champion_bans = {static.champion_by_key.get(k, str(k)): v for k, v in bans.items()}
        for entry in table["entries"]:
            entry["banRate"] = round(champion_bans.get(entry["champion"], 0) / table["matches"], 4) if table["matches"] else 0
        emit("tierlist/{}.json".format(bracket), dict(table, patch=static.patch))

    champions = sorted({p["champion"] for r in records for p in r["participants"]})
    for champion in champions:
        builds = aggregate.builds_for(records, champion, static)
        if builds["roles"]:
            emit("builds/{}.json".format(champion), dict(builds, patch=static.patch))
        matchups = aggregate.matchups_for(records, champion)
        if matchups["roles"]:
            emit("matchups/{}.json".format(champion), dict(matchups, patch=static.patch))

    for tier in aggregate.TIER_ORDER:
        bench = aggregate.benchmarks(records, tier)
        if bench["roles"]:
            emit("benchmarks/{}.json".format(tier), dict(bench, patch=static.patch))

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "patch": static.patch,
        "ddragonVersion": static.version,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sampleSize": len(records),
        "tiers": [t for t in aggregate.TIER_ORDER if "data/{}/benchmarks/{}.json".format(static.patch, t) in files],
        "brackets": list(aggregate.BRACKETS),
        "files": files,
    }
    write_json(os.path.join(ROOT, "manifest.json"), manifest)
    return manifest


def _previous_patch(patch):
    if not os.path.isdir(DATA):
        return None
    patches = sorted((p for p in os.listdir(DATA) if p != patch), key=lambda p: [int(x) for x in p.split(".")])
    return patches[-1] if patches else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default=os.environ.get("RIOT_PLATFORM", "na1"))
    parser.add_argument("--max-requests", type=int, default=int(os.environ.get("MAX_REQUESTS", "900")))
    parser.add_argument("--max-hours", type=float, default=float(os.environ.get("MAX_HOURS", "5")))
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()

    static = StaticData()
    print("Patch {} (Data Dragon {})".format(static.patch, static.version))
    if not args.aggregate_only:
        key = os.environ.get("RIOT_API_KEY")
        if not key:
            sys.exit("RIOT_API_KEY is not set")
        client = RiotClient(key, args.platform)
        added = crawl(client, static, args.max_requests, args.max_hours)
        print("Added {} matches using {} requests".format(added, client.requests))
    manifest = publish(static)
    print("Published {} files from {} matches".format(len(manifest["files"]), manifest["sampleSize"]))


if __name__ == "__main__":
    main()
