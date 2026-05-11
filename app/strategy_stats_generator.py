
import json
import pandas as pd

calc_success = 0
skip_high_risk = 0
skip_too_far = 0

def calculate_martingale_risk(rolls_since, max_delay, strategy=""):
    global skip_high_risk, skip_too_far, calc_success
    try:
        rs = int(float(rolls_since))
        md = int(float(max_delay))
        levels = max(0, md - rs)

        if levels > 10:
            skip_too_far += 1
            return ""

        strategy_lower = strategy.strip().lower()
        if "tiers" in strategy_lower:
            base = 6
        elif "voisins" in strategy_lower:
            base = 9
        elif "orphelins" in strategy_lower:
            base = 5
        else:
            base = 1

        total = sum(base * (2 ** i) for i in range(levels))
        if total > 2000:
            skip_high_risk += 1
            return ""

        calc_success += 1
        return f"${total:,}"
    except Exception as e:
        print(f"[ERROR] Martingale calculation failed for rs={rolls_since}, md={max_delay}, strategy={strategy} -> {e}")
        return ""

def generate_strategy_stats(input_json_path, output_csv_path):
    with open(input_json_path, "r") as f:
        data = json.load(f)

    data.reverse()
    df = pd.DataFrame(data)
    df["number"] = df["number"].astype(int)
    df["Index"] = df.index + 1
    latest_index = df["Index"].max()
    reversed_df = df.sort_values("Index", ascending=False).reset_index(drop=True)

    general_bets = {
        "Tiers": [5, 8, 10, 11, 13, 16, 23, 24, 27, 30, 33, 36],
        "Orphelins": [1, 6, 9, 14, 17, 20, 31, 34],
        "Voisins Du Zero": [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],
        "Zero": [0,3,12,15,26,32,35],
        "Top Row": list(range(3, 37, 3)),
        "Middle Row": list(range(2, 36, 3)),
        "Bottom Row": list(range(1, 35, 3)),
        "1st & 12": list(range(1, 13)),
        "2nd & 12": list(range(13, 25)),
        "3rd & 12": list(range(25, 37)),
# Combinations:
        "1st & 2nd & 12": list(range(1, 25)),  # or: list(range(1, 13)) + list(range(13, 25))
        "1st & 3rd & 12": list(range(1, 13)) + list(range(25, 37)),
        "2nd & 3rd & 12": list(range(13, 25)) + list(range(25, 37)),
        "Top & Middle Row": list(range(3, 37, 3)) + list(range(2, 36, 3)),
        "Top & Bottom Row": list(range(3, 37, 3)) + list(range(1, 35, 3)),
        "Middle & Bottom Row": list(range(2, 36, 3)) + list(range(1, 35, 3)),
        # Crossfire strategies: selected dozen OR selected row.
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
        "1 to 18": list(range(1,19)),
        "19 to 36": list(range(19,37))
    }

    horizontal_doubles = {
        f"{i}/{i+3}": [i, i+3] for i in range(1, 34)
    }

    #edge cases with 0
    horizontal_doubles.update({
        "0/1": [0, 1],
        "0/2": [0, 2],
        "0/3": [0, 3],
    })

    vertical_doubles = {
        f"{i}/{i+1}": [i, i+1] for i in range(1, 36) if i % 3 != 0
    }
    quads = {
        f"{i}/{i+1}/{i+3}/{i+4}": [i, i+1, i+3, i+4]
        for i in range(1, 33)
        if i % 3 != 0 and (i + 4) <= 36
    }

    #edge cases with 0
    # Add edge cases like {0,3,2} and {0,2,1}
    quads.update({
        "0/1/2": [0, 1, 2],
        "0/2/3": [0, 2, 3],  # adjust label for consistency
    })

    general_df = pd.DataFrame([
        {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": "General"}
        for k, v in general_bets.items()
    ])

    outside_df = pd.DataFrame([
        {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": "Outside"}
        for k, v in outside_bets.items()
    ])

    alt_bets_dfs = []
    for bet_type, bet_data in [("Horizontal Doubles", horizontal_doubles), ("Vertical Doubles", vertical_doubles), ("Quads", quads)]:
        df_alt = pd.DataFrame([
            {"Betting Strategy": f"'{k}", "Numbers": v, "BetType": bet_type}
            for k, v in bet_data.items()
        ])
        alt_bets_dfs.append(df_alt)

    all_bets_df = pd.concat([general_df] + alt_bets_dfs + [outside_df], ignore_index=True)

    def rolls_since_last_hit(numbers, data, latest_index):
        for _, row in data.iterrows():
            if row["number"] in numbers:
                return latest_index - row["Index"]
        return None

    all_bets_df["Rolls Since Last Hit"] = all_bets_df["Numbers"].apply(
        lambda nums: rolls_since_last_hit(nums, reversed_df, latest_index)
    )

    def calculate_delays(numbers, df_with_index):
        hits = df_with_index[df_with_index['number'].isin(numbers)].sort_values('Index')
        indices = hits['Index'].tolist()
        delays = [j - i for i, j in zip(indices[:-1], indices[1:])]
        return {
            "Avg Delay": round(sum(delays)/len(delays), 2) if delays else None,
            "Min Delay": min(delays) if delays else None,
            "Max Delay": max(delays) if delays else None,
            "Last Hit Index": indices[-1] if indices else None,
            "Rolls Since Last Hit": latest_index - indices[-1] if indices else None
        }

    stats_results = all_bets_df.copy()
    stats_results[["Avg Delay", "Min Delay", "Max Delay", "Last Hit Index", "Rolls Since Last Hit"]] = (
        all_bets_df["Numbers"].apply(lambda nums: pd.Series(calculate_delays(nums, df)))
    )

    def bet_signal(row):
        try:
            if pd.notna(row["Rolls Since Last Hit"]) and pd.notna(row["Avg Delay"]):
                return "? Consider betting" if row["Rolls Since Last Hit"] >= row["Avg Delay"] else "? Wait"
        except:
            return None
        return None

    stats_results["Bet Signal"] = stats_results.apply(bet_signal, axis=1)

    recent_df = df.tail(100)

    # ---- Bias Integration (100 & 500 rolls) ----
    def compute_bias_map(target_df):
        observed_counts = target_df["number"].value_counts().sort_index()
        all_numbers = list(range(37))
        observed_counts = observed_counts.reindex(all_numbers, fill_value=0)
        expected = len(target_df) / 37
        bias_score = (observed_counts - expected) / expected
        return dict(zip(all_numbers, bias_score))

    def classify(score):
        if score > 0.1:
            return "+"
        elif score < -0.1:
            return "-"
        return "0"

    def compute_bias_combined(numbers):
        scores_100 = [bias_map_100.get(n, 0) for n in numbers]
        scores_500 = [bias_map_500.get(n, 0) for n in numbers]
        bias_100 = round(sum(scores_100)/len(scores_100), 2) if scores_100 else 0.0
        bias_500 = round(sum(scores_500)/len(scores_500), 2) if scores_500 else 0.0
        return f"{bias_100} | {bias_500}", f"{classify(bias_100)} | {classify(bias_500)}"

    bias_map_500 = compute_bias_map(df)
    bias_map_100 = compute_bias_map(recent_df)

    stats_results[["Bias Score", "Bias Classification"]] = stats_results["Numbers"].apply(
        lambda nums: pd.Series(compute_bias_combined(nums))
    )

    # export only the 500-roll bias for number-based CSV
    observed_counts = df["number"].value_counts().sort_index()
    all_numbers = list(range(37))
    observed_counts = observed_counts.reindex(all_numbers, fill_value=0)
    expected = len(df) / 37
    bias_score = (observed_counts - expected) / expected

    # bias_df = pd.DataFrame({
    #     "Number": all_numbers,
    #     "Bias Score": bias_score.round(2),
    #     "Bias Classification": bias_score.apply(lambda x: classify(x))
    # })

    bias_score_500 = bias_map_500
    bias_score_100 = bias_map_100

    bias_df = pd.DataFrame({
        "Number": all_numbers,
        "Bias Score": [f"{round(bias_score_100[n], 2)} | {round(bias_score_500[n], 2)}" for n in all_numbers],
        "Bias Classification": [f"{classify(bias_score_100[n])} | {classify(bias_score_500[n])}" for n in all_numbers]
    })

    # Finalize output
    final_stats_df = stats_results.drop(columns=["Numbers", "Last Hit Index"])
    final_stats_df["Martingale Risk"] = final_stats_df.apply(lambda row: calculate_martingale_risk(row["Rolls Since Last Hit"], row["Max Delay"], row["Betting Strategy"]), axis=1)

    final_stats_df.to_csv(output_csv_path, index=False)
    bias_df.to_csv("bias_by_number_output.csv", index=False)

    print("🎯 Strategy Statistics:")
    print(final_stats_df)
    print("🎯 Bias by Number:")
    print(bias_df)
    print(f"[SUMMARY] Martingale Risk: {calc_success} calculated, {skip_too_far} skipped (distance > 10), {skip_high_risk} skipped (risk > $1,000)")

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
    final_stats_df = generate_strategy_stats("roulette_data.json", "strategy_statistics_output.csv")
    
    # Call the function and write result
    preferred_group = determine_group_strategy(final_stats_df)
    with open("preferred_group_strategy.txt", "w", encoding="utf-8") as f:
        f.write(preferred_group)
