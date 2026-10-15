"""Turns a match-v5 match + timeline into a compact record with only what aggregation needs."""

SLOTS = {1: "Q", 2: "W", 3: "E", 4: "R"}
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
STARTING_WINDOW_MS = 90_000
SESSION_GAP_MS = 30_000


def summarize(match, timeline, static, tier):
    info = match["info"]
    if info.get("queueId") != 420 or info.get("gameDuration", 0) < 15 * 60:
        return None  # ranked solo only; skip remakes and early surrenders
    patch = ".".join(info["gameVersion"].split(".")[:2])
    purchases, skills = _timeline_events(timeline)
    frames = timeline["info"]["frames"] if timeline else []

    participants = []
    for p in info["participants"]:
        role = p.get("teamPosition")
        if role not in ROLES:
            return None
        pid = p["participantId"]
        bought = purchases.get(pid, [])
        styles = p["perks"]["styles"]
        stats = p["perks"]["statPerks"]
        participants.append({
            "champion": static.champion_by_key.get(p["championId"], str(p["championId"])),
            "role": role,
            "team": p["teamId"],
            "win": p["win"],
            "k": p["kills"], "d": p["deaths"], "a": p["assists"],
            "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
            "gold": p["goldEarned"],
            "dmg": p["totalDamageDealtToChampions"],
            "vision": p["visionScore"],
            "spells": sorted([static.spell_by_key.get(p["summoner1Id"], ""), static.spell_by_key.get(p["summoner2Id"], "")],
                             key=lambda s: (s != "SummonerFlash", s)),
            "perks": {
                "primary": styles[0]["style"],
                "sub": styles[1]["style"],
                "ids": [s["perk"] for s in styles[0]["selections"]] + [s["perk"] for s in styles[1]["selections"]]
                       + [stats["offense"], stats["flex"], stats["defense"]],
            },
            "skills": "".join(skills.get(pid, []))[:18],
            "start": _starting_items(bought, static),
            "firstBack": _first_back(bought, static),
            "completed": _completed_order(bought, static),
            "boots": next((i for _, i in bought if static.is_boots(i)), None),
            "pet": next((i for _, i in bought if static.is_jungle_pet(i)), None),
            "gold15": _frame_value(frames, 15, pid, "totalGold"),
            "levels": [_frame_value(frames, m, pid, "level") for m in range(0, min(len(frames), 41))],
        })

    return {
        "id": match["metadata"]["matchId"],
        "patch": patch,
        "tier": tier,
        "duration": info["gameDuration"],
        "bans": [b["championId"] for t in info["teams"] for b in t.get("bans", []) if b["championId"] > 0],
        "participants": participants,
    }


def _timeline_events(timeline):
    purchases, skills = {}, {}
    if not timeline:
        return purchases, skills
    for frame in timeline["info"]["frames"]:
        for event in frame.get("events", []):
            kind = event.get("type")
            pid = event.get("participantId")
            if kind == "ITEM_PURCHASED":
                purchases.setdefault(pid, []).append((event["timestamp"], event["itemId"]))
            elif kind == "ITEM_UNDO" and purchases.get(pid):
                before = event.get("beforeId")
                for index in range(len(purchases[pid]) - 1, -1, -1):
                    if purchases[pid][index][1] == before:
                        del purchases[pid][index]
                        break
            elif kind == "SKILL_LEVEL_UP" and event.get("levelUpType") == "NORMAL":
                skills.setdefault(pid, []).append(SLOTS.get(event["skillSlot"], "?"))
    return purchases, skills


def _starting_items(bought, static):
    return sorted(i for t, i in bought if t <= STARTING_WINDOW_MS and not _is_noise(i, static, keep_potions=True))


def _first_back(bought, static):
    later = [(t, i) for t, i in bought if t > STARTING_WINDOW_MS and not _is_noise(i, static)]
    if not later:
        return []
    first_time = later[0][0]
    return sorted(i for t, i in later if t - first_time <= SESSION_GAP_MS and not static.is_completed(i))


def _completed_order(bought, static):
    seen, order = set(), []
    for _, item in bought:
        if static.is_completed(item) and item not in seen:
            seen.add(item)
            order.append(item)
    return order[:6]


def _is_noise(item_id, static, keep_potions=False):
    if keep_potions and item_id in (2003, 2031, 2033):
        return False
    return static.is_trinket_or_consumable(item_id) or item_id in (2055, 2056, 2010)


def _frame_value(frames, minute, pid, key):
    if minute >= len(frames):
        return None
    return frames[minute]["participantFrames"].get(str(pid), {}).get(key)
