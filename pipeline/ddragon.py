"""Static game data from Data Dragon: current patch, champions and item classification."""
import json
import urllib.request

BASE = "https://ddragon.leagueoflegends.com"


def _fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


class StaticData:
    def __init__(self, version=None):
        self.version = version or _fetch(BASE + "/api/versions.json")[0]
        self.patch = ".".join(self.version.split(".")[:2])
        champions = _fetch("{}/cdn/{}/data/en_US/champion.json".format(BASE, self.version))["data"]
        self.champion_by_key = {int(c["key"]): c["id"] for c in champions.values()}
        items = _fetch("{}/cdn/{}/data/en_US/item.json".format(BASE, self.version))["data"]
        self.items = {int(k): v for k, v in items.items()}
        spells = _fetch("{}/cdn/{}/data/en_US/summoner.json".format(BASE, self.version))["data"]
        self.spell_by_key = {int(s["key"]): s["id"] for s in spells.values()}
        runes = _fetch("{}/cdn/{}/data/en_US/runesReforged.json".format(BASE, self.version))
        self.rune_names = {}
        for style in runes:
            self.rune_names[style["id"]] = style["name"]
            for slot in style["slots"]:
                for rune in slot["runes"]:
                    self.rune_names[rune["id"]] = rune["name"]

    def item_name(self, item_id):
        item = self.items.get(item_id)
        return item["name"] if item else str(item_id)

    def item_price(self, item_id):
        item = self.items.get(item_id)
        return item["gold"]["total"] if item else 0

    def is_boots(self, item_id):
        """Tier-2 boots (built from Boots, 1001)."""
        item = self.items.get(item_id)
        return bool(item) and "1001" in item.get("from", [])

    def is_completed(self, item_id):
        """A finished legendary item: builds from something, builds into nothing, costs at least 2,200."""
        item = self.items.get(item_id)
        if not item or self.is_boots(item_id):
            return False
        return not item.get("into") and item.get("from") and item["gold"]["total"] >= 2200

    def is_jungle_pet(self, item_id):
        return item_id in (1101, 1102, 1103)

    def is_trinket_or_consumable(self, item_id):
        item = self.items.get(item_id)
        if not item:
            return True
        tags = item.get("tags", [])
        return "Trinket" in tags or "Consumable" in tags
