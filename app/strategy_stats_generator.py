import json
import os
from collections import Counter

import pandas as pd


calc_success = 0
skip_high_risk = 0
skip_too_far = 0


DEFAULT_MARTINGALE_CONFIG = {
    "default": {
        "progression": "double",
        "base_stake": 1,
        "max_risk": 2000,
        "max_levels": 10,
    },
    "bet_type_defaults": {
        "General": {"base_stake": 1, "progression": "double"},
        "Outside": {"base_stake": 1, "progression": "double"},
        "Horizontal Doubles": {"base_stake": 1, "progression": "double"},
        "Vertical Doubles": {"base_stake": 1, "progression": "double"},
        "Quads": {"base_stake": 1, "progression": "double"},
    },
    "strategy_overrides": {
        "Zero": {"base_stake": 4, "progression": "double"},
        "Tiers": {"base_stake": 6, "progression": "double"},
        "Orphelins": {"base_stake": 5, "progression": "double"},
        "Voisins Du Zero": {"base_stake": 9, "progression": "double"},

        "Crossfire, 1st & top": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 1st & middle": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 1st & bottom": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 2nd & top": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 2nd & middle": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 2nd & bottom": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 3rd & top": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 3rd & middle": {"base_stake": 2, "progression": "triple"},
        "Crossfire, 3rd & bottom": {"base_stake": 2, "progression": "triple"},

        "1st & 2nd & 12": {"base_stake": 2, "progression": "double"},
        "1st & 3rd & 12": {"base_stake": 2, "progression": "double"},
        "2nd & 3rd & 12": {"base_stake": 2, "progression": "double"},
        "Top & Middle Row": {"base_stake": 2, "progression": "double"},
        "Top & Bottom Row": {"base_stake": 2, "progression": "double"},
        "Middle & Bottom Row": {"base_stake": 2, "progression": "double"},
    },
    "adjusted_rolls": {
        "enabled": True,
        "subtract_zero": True,
        "subtract_duplicate_occurrences": True,
        "minimum_adjusted_rolls": 0,
    },
}


def normalize_strategy_name(strategy):
    return str(strategy or "").lstrip("'").replace(" and ", " & ").strip()


def load_martingale_config(config_path="martingale_config.json"):
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        config = DEFAULT_MARTINGALE_CONFIG.copy()
        config.update(loaded)
        return config

    return DEFAULT_MARTINGALE_CONFIG


def get_strategy_settings(strategy, bet_type, config):
    clean_strategy = normalize_strategy_name(strategy)

    default_settings = dict(config.get("default", {}))
    bet_type_settings = dict(config.get("bet_type_defaults", {}).get(str(bet_type or ""), {}))
    strategy_settings = dict(config.get("strategy_overrides", {}).get(clean_strategy, {}))

    settings = {}
    settings.update(default_settings)
    settings.update(bet_type_settings)
    settings.update(strategy_settings)

    settings["base_stake"] = int(settings.get("base_stake", 1))
    settings["progression"] = str(settings.get("progression", "double")).lower()
    settings["max_risk"] = int(settings.get("max_risk", 2000))
    settings["max_levels"] = int(settings.get("max_levels", 10))

    return settings


def progression_multiplier(progression):
    progression = str(progression or "double").lower().strip()

    if progression == "double":
        return 2
    if progression == "triple":
        return 3

    try:
        parsed = int(progression)
        return max(parsed, 1)
    except Exception:
        return 2


def calculate_martingale_risk_from_settings(rolls_since, max_delay, settings):
    global skip_high_risk, skip_too_far, calc_success

    try:
        if rolls_since is None or max_delay is None:
            return ""

        rs = int(float(rolls_since))
        md = int(float(max_delay))

        levels = max(0, md - rs)

        if levels > settings["max_levels"]:
            skip_too_far += 1
            return ""

        base_stake = int(settings["base_stake"])
        multiplier = progression_multiplier(settings["progression"])

        total = sum(base_stake * (multiplier ** i) for i in range(levels))

        if total > settings["max_risk"]:
            skip_high_risk += 1
            return ""

        calc_success += 1
        return f"${total:,}"

    except Exception as e:
        print(
            f"[ERROR] Martingale calculation failed "
            f"for rs={rolls_since}, md={max_delay}, settings={settings} -> {e}"
        )
        return ""


def calculate_adjusted_rolls_since_last_hit(numbers, df_with_index, last_hit_index, latest_index, config):
    adjusted_cfg = config.get("adjusted_rolls", {})

    if not adjusted_cfg.get("enabled", True):
        return latest_index - last_hit_index if last_hit_index is not None else None

    if last_hit_index is None:
        return None

    raw_rolls_since = latest_index - last_hit_index

    if raw_rolls_since <= 0:
        return raw_rolls_since

    window_df = df_with_index[
        (df_with_index["Index"] > last_hit_index) &
        (df_with_index["Index"] <= latest_index)
    ]

    recent_numbers = [int(n) for n in window_df["number"].tolist()]
    counts = Counter(recent_numbers)

    adjustment = 0

    if adjusted_cfg.get("subtract_zero", True):
        adjustment += counts.get(0, 0)

    if adjusted_cfg.get("subtract_consecutive_duplicate_occurrences", True):
        consecutive_duplicates = 0

        for prev, curr in zip(recent_numbers[:-1], recent_numbers[1:]):
            if curr == prev and curr != 0:
                consecutive_duplicates += 1

        adjustment += consecutive_duplicates

    minimum = int(adjusted_cfg.get("minimum_adjusted_rolls", 0))

    return max(minimum, raw_rolls_since - adjustment)


def generate_strategy_stats(
    input_json_path,
    output_csv_path,
    martingale_config_path="martingale_config.json",
):
    global calc_success, skip_high_risk, skip_too_far
    calc_success = 0
    skip_high_risk = 0
    skip_too_far = 0

    martingale_config = load_martingale_config(martingale_config_path)

    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.reverse()

    df = pd.DataFrame(data)
    df["number"] = df["number"].astype(int)
    df["Index"] = df.index + 1

    latest_index = df["Index"].max()

    general_bets = {
        "Tiers": [5, 8, 10, 11, 13, 16, 23, 24, 27, 30, 33, 36],
        "Orphelins": [1, 6, 9, 14, 17, 20, 31, 34],
        "Voisins Du Zero": [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],
        "Zero": [0, 3, 12, 15, 26, 32, 35],

        "Top Row": list(range(3, 37, 3)),
        "Middle Row": list(range(2, 36, 3)),
        "Bottom Row": list(range(1, 35, 3)),

        "1st & 12": list(range(1, 13)),
        "2nd & 12": list(range(13, 25)),
        "3rd & 12": list(range(25, 37)),

        "1st & 2nd & 12": list(range(1, 25)),
        "1st & 3rd & 12": list(range(1, 13)) + list(range(25, 37)),
        "2nd & 3rd & 12": list(range(13, 25)) + list(range(25, 37)),

        "Top & Middle Row": list(range(3, 37, 3)) + list(range(2, 36, 3)),
        "Top & Bottom Row": list(range(3, 37, 3)) + list(range(1, 35, 3)),
        "Middle & Bottom Row": list(range(2, 36, 3)) + list(range(1, 35, 3)),

        "Crossfire, 1st & top": sorted(set(list(range(1, 13)) + list(range(3, 37, 3)))),
        "Crossfire, 1st & middle": sorted(set(list(range(1, 13)) + list(range(2, 36, 3)))),
        "Crossfire, 1st & bottom": sorted(set(list(range(1, 13)) + list(range(1, 35, 3)))),
        "Crossfire, 2nd & top": sorted(set(list(range(13, 25)) + list(range(3, 37, 3)))),
        "Crossfire, 2nd & middle": sorted(set(list(range(13, 25)) + list(range(2, 36, 3)))),
        "Crossfire, 2nd & bottom": sorted(set(list(range(13, 25)) + list(range(1, 35, 3)))),
        "Crossfire, 3rd & top": sorted(set(list(range(25, 37)) + list(range(3, 37, 3)))),
        "Crossfire, 3rd & middle": sorted(set(list(range(25, 37)) + list(range(2, 36, 3)))),
        "Crossfire, 3rd & bottom": sorted(set(list(range(25, 37)) + list(range(1, 35, 3)))),

        "First Line": [1, 2, 3, 4, 5, 6],
        "Second Line": [7, 8, 9, 10, 11, 12],
        "Third Line": [13, 14, 15, 16, 17, 18],
        "Fourth Line": [19, 20, 21, 22, 23, 24],
        "Fifth Line": [25, 26, 27, 28, 29, 30],
        "Sixth Line": [31, 32, 33, 34, 35, 36],

        "First Street (1, 2, 3)": [1, 2, 3],
        "Second Street (4, 5, 6)": [4, 5, 6],
        "Third Street (7, 8, 9)": [7, 8, 9],
        "Fourth Street (10, 11, 12)": [10, 11, 12],
        "Fifth Street (13, 14, 15)": [13, 14, 15],
        "Sixth Street (16, 17, 18)": [16, 17, 18],
        "Seventh Street (19, 20, 21)": [19, 20, 21],
        "Eighth Street (22, 23, 24)": [22, 23, 24],
        "Ninth Street (25, 26, 27)": [25, 26, 27],
        "Tenth Street (28, 29, 30)": [28, 29, 30],
        "Eleventh Street (31, 32, 33)": [31, 32, 33],
        "Twelfth Street (34, 35, 36)": [34, 35, 36],
    }

    outside_bets = {
        "Odds": list(range(1, 37, 2)),
        "Even": list(range(2, 37, 2)),
        "Red": [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36],
        "Black": [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35],
        "1 to 18": list(range(1, 19)),
        "19 to 36": list(range(19, 37)),
    }

    horizontal_doubles = {f"{i}/{i+3}": [i, i + 3] for i in range(1, 34)}
    horizontal_doubles.update({"0/1": [0, 1], "0/2": [0, 2], "0/3": [0, 3]})

    vertical_doubles = {f"{i}/{i+1}": [i, i + 1] for i in range(1, 36) if i % 3 != 0}

    quads = {
        f"{i}/{i+1}/{i+3}/{i+4}": [i, i + 1, i + 3, i + 4]
        for i in range(1, 33)
        if i % 3 != 0 and (i + 4) <= 36
    }
    quads.update({"0/1/2": [0, 1, 2], "0/2/3": [0, 2, 3]})

    general_df = pd.DataFrame([
        {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": "General"}
        for k, v in general_bets.items()
    ])
    outside_df = pd.DataFrame([
        {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": "Outside"}
        for k, v in outside_bets.items()
    ])

    alt_bets_dfs = []
    for bet_type, bet_data in [
        ("Horizontal Doubles", horizontal_doubles),
        ("Vertical Doubles", vertical_doubles),
        ("Quads", quads),
    ]:
        alt_bets_dfs.append(pd.DataFrame([
            {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": bet_type}
            for k, v in bet_data.items()
        ]))

    all_bets_df = pd.concat([general_df] + alt_bets_dfs + [outside_df], ignore_index=True)

    def calculate_delays(numbers, df_with_index):
        hits = df_with_index[df_with_index["number"].isin(numbers)].sort_values("Index")
        indices = hits["Index"].tolist()
        delays = [j - i for i, j in zip(indices[:-1], indices[1:])]

        last_hit_index = indices[-1] if indices else None
        raw_rolls_since = latest_index - last_hit_index if last_hit_index is not None else None
        adjusted_rolls_since = calculate_adjusted_rolls_since_last_hit(
            numbers=numbers,
            df_with_index=df_with_index,
            last_hit_index=last_hit_index,
            latest_index=latest_index,
            config=martingale_config,
        )

        return {
            "Avg Delay": round(sum(delays) / len(delays), 2) if delays else None,
            "Min Delay": min(delays) if delays else None,
            "Max Delay": max(delays) if delays else None,
            "Last Hit Index": last_hit_index,
            "Rolls Since Last Hit": raw_rolls_since,
            "Adjusted Rolls Since Last Hit": adjusted_rolls_since,
        }

    stats_results = all_bets_df.copy()
    stats_results[
        ["Avg Delay", "Min Delay", "Max Delay", "Last Hit Index", "Rolls Since Last Hit", "Adjusted Rolls Since Last Hit"]
    ] = all_bets_df["Numbers"].apply(lambda nums: pd.Series(calculate_delays(nums, df)))

    def bet_signal(row):
        try:
            if pd.notna(row["Rolls Since Last Hit"]) and pd.notna(row["Avg Delay"]):
                return "? Consider betting" if row["Rolls Since Last Hit"] >= row["Avg Delay"] else "? Wait"
        except Exception:
            return None
        return None

    stats_results["Bet Signal"] = stats_results.apply(bet_signal, axis=1)

    final_stats_df = stats_results.drop(columns=["Numbers", "Last Hit Index"])

    def add_martingale_columns(row):
        settings = get_strategy_settings(row["Betting Strategy"], row["BetType"], martingale_config)

        raw_risk = calculate_martingale_risk_from_settings(
            row["Rolls Since Last Hit"], row["Max Delay"], settings
        )
        adjusted_risk = calculate_martingale_risk_from_settings(
            row["Adjusted Rolls Since Last Hit"], row["Max Delay"], settings
        )

        return pd.Series({
            "Martingale Base Stake": settings["base_stake"],
            "Martingale Progression": settings["progression"],
            "Martingale Risk": raw_risk,
            "Adjusted Martingale Risk": adjusted_risk,
        })

    final_stats_df[
        ["Martingale Base Stake", "Martingale Progression", "Martingale Risk", "Adjusted Martingale Risk"]
    ] = final_stats_df.apply(add_martingale_columns, axis=1)

    final_stats_df.to_csv(output_csv_path, index=False)

    print("🎯 Strategy Statistics:")
    print(final_stats_df)
    print(
        f"[SUMMARY] Martingale Risk: {calc_success} calculated, "
        f"{skip_too_far} skipped (distance > 10), {skip_high_risk} skipped (risk > max_risk)"
    )

    return final_stats_df


def determine_group_strategy(stats_df):
    group_a_names = ["'1st & 12", "'2nd & 12", "'3rd & 12"]
    group_b_names = ["'Top Row", "'Middle Row", "'Bottom Row"]

    def get_top2_avg_and_sum(group_names):
        valid = stats_df[stats_df["Betting Strategy"].isin(group_names)]
        valid = valid[["Betting Strategy", "Rolls Since Last Hit"]].dropna()
        top2 = valid.sort_values("Rolls Since Last Hit", ascending=False).head(2)["Rolls Since Last Hit"].tolist()
        if len(top2) < 2:
            return None, None
        avg = sum(top2) / 2
        total = sum(top2)
        return avg, total

    a_avg, a_sum = get_top2_avg_and_sum(group_a_names)
    b_avg, b_sum = get_top2_avg_and_sum(group_b_names)

    if a_avg is None or b_avg is None:
        return "❓ Not enough data"

    if a_avg > b_avg:
        return "✅ Prefer Thirds"
    elif b_avg > a_avg:
        return "✅ Prefer Rows"
    else:
        return "✅ Prefer Thirds" if a_sum > b_sum else "✅ Prefer Rows"


if __name__ == "__main__":
    final_stats_df = generate_strategy_stats(
        "roulette_data.json",
        "strategy_statistics_output.csv",
        martingale_config_path="martingale_config.json",
    )

    preferred_group = determine_group_strategy(final_stats_df)

    with open("preferred_group_strategy.txt", "w", encoding="utf-8") as f:
        f.write(preferred_group)
