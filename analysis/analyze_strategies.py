import argparse
import csv
import json
import sqlite3
from pathlib import Path
from datetime import datetime

DEFAULT_DB = r"C:\Roll\global\global_rolls.sqlite"
DEFAULT_CONFIG = r"C:\Roll\global\strategy_analysis_config_all.json"

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def resolve_table(conn, table_name):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if table_name in tables:
        return table_name
    if "global_rolls" in tables:
        return "global_rolls"
    if "wheel_rolls" in tables:
        return "wheel_rolls"
    raise RuntimeError(f"No roll table found. Existing tables: {sorted(tables)}")

def load_rolls(conn, table_name="global_rolls", wheel="global", rolling=None):
    table_name = resolve_table(conn, table_name)
    params = []
    sql = f"SELECT wheel_id, seq, number, color, created_at_utc FROM {table_name}"
    if wheel and wheel.lower() != "global":
        sql += " WHERE wheel_id = ?"
        params.append(wheel)
        sql += " ORDER BY seq"
    else:
        sql += " ORDER BY created_at_utc, wheel_id, seq"

    rows = []
    for r in conn.execute(sql, params).fetchall():
        rows.append({
            "wheel_id": r[0],
            "seq": int(r[1]),
            "number": int(r[2]),
            "color": r[3],
            "created_at_utc": r[4],
        })

    if rolling and rolling > 0:
        rows = rows[-rolling:]
    return rows

def strategy_matches(strategy, wanted_strategy, categories):
    if wanted_strategy and wanted_strategy.lower() != "all":
        return strategy["name"].lower() == wanted_strategy.lower()
    if categories:
        return strategy.get("category", "") in categories
    return True

def component_numbers(component):
    return set(int(n) for n in component["numbers"])

def is_strategy_hit(number, strategy):
    return any(number in component_numbers(c) for c in strategy["components"])

def spin_profit(number, strategy, stake):
    total = 0.0
    hit_any = False
    hit_count = 0

    for component in strategy["components"]:
        nums = component_numbers(component)
        payout = float(component["payout"])

        if number in nums:
            total += stake * payout
            hit_any = True
            hit_count += 1
        else:
            total -= stake

    return total, hit_any, hit_count

def simulate_strategy(rolls, strategy, entry_delay, max_bet=2000, progression_base=3, stop_on_any_hit=True):
    delay = 0
    active = False
    step = 0

    total_profit = 0.0
    total_staked = 0.0
    peak_profit = 0.0
    max_drawdown = 0.0

    sessions = 0
    wins = 0
    busts = 0
    overlap_hits = 0
    largest_step = 0

    for roll in rolls:
        number = int(roll["number"])
        natural_hit = is_strategy_hit(number, strategy)

        # Entry is based on drought before current spin.
        if not active and delay >= entry_delay:
            active = True
            step = 0
            sessions += 1

        if active:
            stake = progression_base ** step
            exposure = stake * len(strategy["components"])

            if exposure > max_bet:
                busts += 1
                active = False
                step = 0
            else:
                profit, hit_any, hit_count = spin_profit(number, strategy, stake)
                total_profit += profit
                total_staked += exposure
                largest_step = max(largest_step, step)

                if hit_count > 1:
                    overlap_hits += 1

                if hit_any:
                    wins += 1
                    if stop_on_any_hit:
                        active = False
                        step = 0
                else:
                    step += 1

        if natural_hit:
            delay = 0
        else:
            delay += 1

        peak_profit = max(peak_profit, total_profit)
        max_drawdown = max(max_drawdown, peak_profit - total_profit)

    win_rate = wins / sessions if sessions else 0
    avg_profit = total_profit / sessions if sessions else 0
    roi = total_profit / total_staked if total_staked else 0

    return {
        "strategy": strategy["name"],
        "category": strategy.get("category", ""),
        "entry_delay": entry_delay,
        "sessions": sessions,
        "wins": wins,
        "busts": busts,
        "overlap_hits": overlap_hits,
        "win_rate": round(win_rate, 4),
        "total_profit": round(total_profit, 2),
        "avg_profit_per_session": round(avg_profit, 2),
        "max_drawdown": round(max_drawdown, 2),
        "largest_progression_step": largest_step,
        "total_staked": round(total_staked, 2),
        "roi": round(roi, 6),
    }

def write_csv(path, rows):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser = argparse.ArgumentParser(description="Roulette strategy entry-delay simulator against global SQLite rolls.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--table", default="global_rolls")
    parser.add_argument("--wheel", default="global", help="global or wheel_id")
    parser.add_argument("--strategy", default="all", help="Exact strategy name or all")
    parser.add_argument("--category", action="append", help="Filter by category; can repeat")
    parser.add_argument("--min-entry-delay", type=int, default=0)
    parser.add_argument("--max-entry-delay", type=int, default=30)
    parser.add_argument("--max-bet", type=int, default=None)
    parser.add_argument("--base", type=int, default=None)
    parser.add_argument("--rolling", type=int, default=None)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    max_bet = args.max_bet if args.max_bet is not None else int(cfg.get("default_max_bet", 2000))
    base = args.base if args.base is not None else int(cfg.get("default_progression_base", 3))
    stop_on_any_hit = bool(cfg.get("stop_on_any_hit", True))

    conn = sqlite3.connect(args.db)
    rolls = load_rolls(conn, args.table, args.wheel, args.rolling)

    categories = set(args.category or [])
    selected = [
        s for s in cfg["strategies"]
        if strategy_matches(s, args.strategy, categories)
    ]

    results = []
    for strategy in selected:
        for entry in range(args.min_entry_delay, args.max_entry_delay + 1):
            result = simulate_strategy(
                rolls=rolls,
                strategy=strategy,
                entry_delay=entry,
                max_bet=max_bet,
                progression_base=base,
                stop_on_any_hit=stop_on_any_hit,
            )
            result["wheel"] = args.wheel
            result["rolling"] = args.rolling or "all"
            result["max_bet"] = max_bet
            result["base"] = base
            results.append(result)

    results.sort(key=lambda r: (r["total_profit"], r["roi"], -r["max_drawdown"]), reverse=True)

    print(f"Loaded rolls: {len(rolls)}")
    print(f"Strategies analyzed: {len(selected)}")
    print(f"Result rows: {len(results)}")
    print("")
    print("TOP RESULTS")
    print("=" * 120)

    for r in results[:args.top]:
        print(
            f"{r['strategy'][:36]:36} "
            f"{r['category'][:16]:16} "
            f"delay={r['entry_delay']:2} "
            f"profit={r['total_profit']:11,.2f} "
            f"drawdown={r['max_drawdown']:11,.2f} "
            f"sessions={r['sessions']:6} "
            f"wins={r['wins']:6} "
            f"busts={r['busts']:4} "
            f"roi={r['roi']:.4f}"
        )

    if args.out:
        out = Path(args.out)
    else:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        label = "_".join(args.category) if args.category else (args.strategy if args.strategy != "all" else "all")
        label = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in label)
        out = Path(f"strategy_analysis_{label}_{args.wheel}_{ts}.csv")

    write_csv(out, results)
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
