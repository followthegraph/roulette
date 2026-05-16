# Optional EU Flask Endpoint

This lets you submit analysis requests from local to the EU machine.

Add to EU app.py only.

```python
@app.route("/global-strategy-analysis")
def global_strategy_analysis():
    import subprocess
    import csv
    from flask import request, jsonify

    wheel = request.args.get("wheel", "global")
    category = request.args.get("category")
    strategy = request.args.get("strategy", "all")
    rolling = request.args.get("rolling")
    max_bet = request.args.get("max_bet", "2000")
    base = request.args.get("base", "3")
    max_entry_delay = request.args.get("max_entry_delay", "30")
    min_entry_delay = request.args.get("min_entry_delay", "0")

    python_exe = r"C:\Roll\python-embed\App\Python\python.exe"
    script_path = r"C:\Roll\global\analyze_strategies.py"
    db_path = r"C:\Roll\global\global_rolls.sqlite"
    config_path = r"C:\Roll\global\strategy_analysis_config_all.json"
    out_path = r"C:\Roll\global\latest_strategy_analysis.csv"

    cmd = [
        python_exe,
        script_path,
        "--db", db_path,
        "--config", config_path,
        "--wheel", wheel,
        "--strategy", strategy,
        "--max-bet", str(max_bet),
        "--base", str(base),
        "--min-entry-delay", str(min_entry_delay),
        "--max-entry-delay", str(max_entry_delay),
        "--out", out_path,
    ]

    if category:
        cmd.extend(["--category", category])

    if rolling:
        cmd.extend(["--rolling", str(rolling)])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if proc.returncode != 0:
        return jsonify({
            "status": "error",
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }), 500

    with open(out_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    return jsonify({
        "status": "success",
        "count": len(rows),
        "top": rows[:25],
        "stdout": proc.stdout
    })
```

Example:

```cmd
curl "https://eu.getdatbp.com/global-strategy-analysis?category=crossfire&wheel=global&max_bet=2000&base=3"
```
