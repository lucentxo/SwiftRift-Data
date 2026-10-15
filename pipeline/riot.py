"""Minimal Riot API client with rate limiting and retry. Standard library only."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

PLATFORM_TO_REGION = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "kr": "asia", "jp1": "asia",
    "oc1": "sea", "sg2": "sea", "tw2": "sea", "vn2": "sea",
}


class RateLimiter:
    """Sliding-window limiter for several (count, seconds) windows at once."""

    def __init__(self, windows):
        self.windows = [(count, seconds, deque()) for count, seconds in windows]

    def wait(self):
        while True:
            now = time.monotonic()
            delay = 0.0
            for count, seconds, stamps in self.windows:
                while stamps and now - stamps[0] >= seconds:
                    stamps.popleft()
                if len(stamps) >= count:
                    delay = max(delay, seconds - (now - stamps[0]) + 0.05)
            if delay <= 0:
                for _, _, stamps in self.windows:
                    stamps.append(now)
                return
            time.sleep(delay)


class RiotClient:
    # Development keys: 20 requests / 1 s and 100 / 2 min. Production keys can raise these via env.
    def __init__(self, api_key, platform="na1", windows=((20, 1), (100, 120))):
        self.api_key = api_key
        self.platform = platform
        self.region = PLATFORM_TO_REGION[platform]
        self.limiter = RateLimiter(windows)
        self.requests = 0

    def _get(self, host, path, params=None):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        url = "https://{}.api.riotgames.com{}{}".format(host, path, query)
        for attempt in range(6):
            self.limiter.wait()
            self.requests += 1
            request = urllib.request.Request(url, headers={"X-Riot-Token": self.api_key, "User-Agent": "SwiftRift-Data"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if error.code == 429 or error.code >= 500:
                    retry_after = float(error.headers.get("Retry-After") or 2 ** attempt)
                    time.sleep(min(retry_after, 120))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** attempt)
        raise RuntimeError("Gave up on " + url)

    # league-exp-v4 lists every tier including apex tiers, with puuids.
    def league_entries(self, tier, division, page=1, queue="RANKED_SOLO_5x5"):
        path = "/lol/league-exp/v4/entries/{}/{}/{}".format(queue, tier, division)
        return self._get(self.platform, path, {"page": page}) or []

    def match_ids(self, puuid, start_time=None, count=20, queue=420):
        params = {"queue": queue, "count": count, "type": "ranked"}
        if start_time:
            params["startTime"] = int(start_time)
        return self._get(self.region, "/lol/match/v5/matches/by-puuid/{}/ids".format(puuid), params) or []

    def match(self, match_id):
        return self._get(self.region, "/lol/match/v5/matches/{}".format(match_id))

    def timeline(self, match_id):
        return self._get(self.region, "/lol/match/v5/matches/{}/timeline".format(match_id))
