import math

import cloudscraper

from state import target_names

scraper = cloudscraper.create_scraper()


def scrape_tracker(tracker_url):
    resp = scraper.get(tracker_url)
    resp.raise_for_status()
    data = resp.json()

    segments = data["data"]["segments"]

    ranks = {}
    for seg in segments:
        name = seg.get("metadata", {}).get("name")
        seg_type = seg.get("type")
        stats = seg.get("stats", {})

        if name not in target_names:
            continue

        key = target_names[name]

        if seg_type == "playlist":
            current = stats.get("rating", {}).get("value")
            if current is not None:
                ranks[f"{key}_elo"] = current

        elif seg_type == "peak-rating":
            peak = stats.get("peakRating", {}).get("value")
            if peak is not None:
                ranks[f"{key}_peak"] = peak

    ones_mmr = ranks.get("ones_elo")
    ones_peak = ranks.get("ones_peak")
    twos_mmr = ranks.get("twos_elo")
    twos_peak = ranks.get("twos_peak")
    threes_mmr = ranks.get("threes_elo")
    threes_peak = ranks.get("threes_peak")
    print(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak)
    return get_elo(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak)

def get_elo(ones_mmr, ones_peak, twos_mmr, twos_peak, threes_mmr, threes_peak):
    ones_elo = math.ceil(ones_peak * 0.8 + ones_mmr * 0.2)
    twos_elo = math.ceil(twos_peak * 0.8 + twos_mmr * 0.2)
    threes_elo = math.ceil(threes_peak * 0.8 + threes_mmr * 0.2)
    return ones_elo, twos_elo, threes_elo

def format_link(tracker_url):
    parts = tracker_url.split("/")
    print(parts)
    platform = parts[5]
    username = parts[6]
    link = f"https://api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{username}?"
    print(link)
    return link
