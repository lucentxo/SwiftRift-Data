"""Aggregates match records into the JSON files the SwiftRift app reads."""
import math
from collections import Counter, defaultdict

TIER_ORDER = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
BRACKETS = {
    "all": TIER_ORDER,
    "emerald_plus": TIER_ORDER[5:],
    "diamond_plus": TIER_ORDER[6:],
    "master_plus": TIER_ORDER[7:],
}
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
PRIOR_GAMES = 40  # Bayesian smoothing toward 50% for small samples


def smoothed(wins, games):
    return (wins + PRIOR_GAMES * 0.5) / (games + PRIOR_GAMES)


def rate(wins, games):
    return round(wins / games, 4) if games else 0.0


def meta_tier(win_rate, pick_rate):
    score = (win_rate - 0.5) * 100 + 6 * math.sqrt(pick_rate)
    for label, threshold in (("S+", 3.6), ("S", 2.4), ("A", 1.2), ("B", 0.0), ("C", -1.2)):
        if score >= threshold:
            return label
    return "D"


def in_bracket(record, bracket):
    return record["tier"] in BRACKETS[bracket]


# MARK: Tier list

def tier_list(records, bracket, previous=None):
    matches = [r for r in records if in_bracket(r, bracket)]
    total = len(matches)
    games, wins, bans = Counter(), Counter(), Counter()
    for record in matches:
        for champion_key in set(record["bans"]):
            bans[champion_key] += 1
        for p in record["participants"]:
            key = (p["champion"], p["role"])
            games[key] += 1
            wins[key] += p["win"]
    previous_rates = {(e["champion"], e["role"]): e["winRate"] for e in (previous or {}).get("entries", [])}

    entries = []
    for (champion, role), count in games.items():
        if count < 5:
            continue
        win_rate = smoothed(wins[(champion, role)], count)
        pick_rate = count / total if total else 0
        entries.append({
            "champion": champion,
            "role": role,
            "games": count,
            "winRate": rate(wins[(champion, role)], count),
            "pickRate": round(pick_rate, 4),
            "banRate": 0.0,  # filled below by champion key lookup in the caller
            "tier": meta_tier(win_rate, pick_rate),
            "winRateDelta": round((rate(wins[(champion, role)], count) - previous_rates[(champion, role)]) * 100, 2)
            if (champion, role) in previous_rates else 0.0,
        })
    entries.sort(key=lambda e: (["S+", "S", "A", "B", "C", "D"].index(e["tier"]), -e["winRate"]))
    return {"bracket": bracket, "matches": total, "entries": entries, "_bans": bans}


# MARK: Builds

def _mode(values, default=None):
    values = [v for v in values if v not in (None, "", [], ())]
    return Counter(values).most_common(1)[0][0] if values else default


def _top(values, n):
    return [v for v, _ in Counter(v for v in values if v).most_common(n)]


MIN_BRACKET_GAMES = 30  # below this, builds for a role fall back to all ranks


def builds_for(records, champion, static, bracket="emerald_plus"):
    by_role = defaultdict(list)
    all_by_role = defaultdict(list)
    for record in records:
        high = in_bracket(record, bracket)
        for p in record["participants"]:
            if p["champion"] == champion:
                all_by_role[p["role"]].append(p)
                if high:
                    by_role[p["role"]].append(p)

    roles = {}
    for role in set(by_role) | set(all_by_role):
        players, used = by_role.get(role, []), bracket
        if len(players) < MIN_BRACKET_GAMES and len(all_by_role[role]) > len(players):
            players, used = all_by_role[role], "all"
        if len(players) < 5:
            continue
        groups = defaultdict(list)
        for p in players:
            if len(p["completed"]) >= 2:
                groups[tuple(p["completed"][:2])].append(p)
        ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:4]
        builds = [_build(core_pair, group, players, role, static) for core_pair, group in ranked if len(group) >= 2]
        if builds:
            roles[role] = {"games": len(players), "winRate": rate(sum(p["win"] for p in players), len(players)),
                           "bracket": used, "builds": builds}
    return {"champion": champion, "bracket": bracket, "roles": roles}


def _build(core_pair, group, all_players, role, static):
    third = _mode([p["completed"][2] for p in group if len(p["completed"]) > 2])
    core = list(core_pair) + ([third] if third else [])
    boots = _mode([p["boots"] for p in group])
    fourth = _top([p["completed"][3] for p in group if len(p["completed"]) > 3 and p["completed"][3] not in core], 3)
    starting = _mode([tuple(p["start"]) for p in group], ())
    first_back = _mode([tuple(p["firstBack"]) for p in group], ())
    pet = _mode([p["pet"] for p in group]) if role == "JUNGLE" else None

    perk_pages = Counter(tuple(p["perks"]["ids"]) + (p["perks"]["primary"], p["perks"]["sub"]) for p in group)
    page, page_count = perk_pages.most_common(1)[0]
    page_wins = sum(p["win"] for p in group if tuple(p["perks"]["ids"]) == page[:9])
    spells = list(_mode([tuple(p["spells"]) for p in group], ("SummonerFlash", "")))
    full_skills = [p["skills"] for p in group if len(p["skills"]) >= 15]
    skill_sequence = _mode(full_skills, "") or _mode([p["skills"] for p in group], "")
    skill_wins = [p["win"] for p in group if p["skills"] == skill_sequence]

    item_path = []
    if pet:
        item_path.append({"kind": "junglePet", "title": "Jungle Pet", "itemIDs": [pet], "note": static.item_name(pet)})
    if starting:
        item_path.append({"kind": "starting", "title": "Starting Items", "itemIDs": list(starting)})
    if first_back:
        item_path.append({"kind": "firstBack", "title": "First Component", "itemIDs": list(first_back)})
    core_with_boots = core[:2] + ([boots] if boots else []) + core[2:]
    item_path.append({"kind": "core", "title": "Core Items", "itemIDs": core_with_boots})
    if fourth:
        item_path.append({"kind": "fourthOptions", "title": "Fourth Item Options", "itemIDs": fourth})

    games = len(group)
    return {
        "name": static.item_name(core[0]),
        "role": role,
        "games": games,
        "winRate": rate(sum(p["win"] for p in group), games),
        "pickRate": round(games / len(all_players), 4),
        "itemPath": item_path,
        "runes": {
            "name": static.rune_names.get(page[0], "Runes"),
            "primaryStyleID": page[9],
            "subStyleID": page[10],
            "perkIDs": list(page[:9]),
            "winRate": rate(page_wins, page_count),
            "pickRate": round(page_count / games, 4),
        },
        "summonerSpells": [s for s in spells if s],
        "skillOrder": {"sequence": list(skill_sequence), "winRate": rate(sum(skill_wins), len(skill_wins))},
    }


# MARK: Matchups

def matchups_for(records, champion, bracket="emerald_plus"):
    results = defaultdict(lambda: {"games": 0, "wins": 0, "goldDiff": []})
    for record in records:
        if not in_bracket(record, bracket):
            continue
        for me in record["participants"]:
            if me["champion"] != champion:
                continue
            for other in record["participants"]:
                if other["team"] != me["team"] and other["role"] == me["role"]:
                    entry = results[(me["role"], other["champion"])]
                    entry["games"] += 1
                    entry["wins"] += me["win"]
                    if me["gold15"] is not None and other["gold15"] is not None:
                        entry["goldDiff"].append(me["gold15"] - other["gold15"])
    roles = defaultdict(list)
    for (role, opponent), entry in results.items():
        if entry["games"] < 3:
            continue
        diffs = entry["goldDiff"]
        roles[role].append({
            "opponent": opponent,
            "games": entry["games"],
            "winRate": rate(entry["wins"], entry["games"]),
            "goldDiffAt15": int(sum(diffs) / len(diffs)) if diffs else 0,
        })
    for role in roles:
        roles[role].sort(key=lambda m: -m["winRate"])
    return {"champion": champion, "bracket": bracket, "roles": dict(roles)}


# MARK: Benchmarks

def benchmarks(records, tier):
    by_role = defaultdict(list)
    for record in records:
        if record["tier"] != tier:
            continue
        minutes = record["duration"] / 60
        teams = defaultdict(list)
        for p in record["participants"]:
            teams[p["team"]].append(p)
        for p in record["participants"]:
            team = teams[p["team"]]
            team_kills = sum(q["k"] for q in team) or 1
            team_damage = sum(q["dmg"] for q in team) or 1
            by_role[p["role"]].append({
                "gold": p["gold"] / minutes, "cs": p["cs"] / minutes, "kp": (p["k"] + p["a"]) / team_kills,
                "vision": p["vision"] / minutes, "share": p["dmg"] / team_damage, "deaths": p["d"], "levels": p["levels"],
            })
    roles = {}
    for role, rows in by_role.items():
        if len(rows) < 5:
            continue
        def average(key):
            return round(sum(r[key] for r in rows) / len(rows), 3)
        levels = []
        for minute in range(41):
            values = [r["levels"][minute] for r in rows if len(r["levels"]) > minute and r["levels"][minute]]
            levels.append(round(sum(values) / len(values), 2) if values else (levels[-1] if levels else 1))
        roles[role] = {
            "samples": len(rows),
            "goldPerMinute": average("gold"), "csPerMinute": average("cs"), "killParticipation": average("kp"),
            "visionPerMinute": average("vision"), "damageShare": average("share"), "deathsPerGame": average("deaths"),
            "levelByMinute": levels,
        }
    return {"tier": tier, "roles": roles}
