# Crossfire Analyzer - Sample Use Cases

## Recommended local setup

SQLite is not ideal to query directly over HTTP. Best practical approach:

1. Expose or share the EU database folder over the local network, OR
2. Copy the SQLite file from EU to your local machine before running analysis.

Example local folder:

```powershell
C:\projects\roulette_dist\global_analysis\
```

Example copied DB path:

```powershell
C:\projects\roulette_dist\global_analysis\global_rolls.sqlite
```

---

## Basic commands

### Analyze all Crossfire strategies globally

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json
```

### Analyze only EU wheel

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --wheel eu-wheel --config crossfire_all_strategies_config.json
```

### Analyze only Classic wheel

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --wheel classic-wheel --config crossfire_all_strategies_config.json
```

### Analyze only Flash wheel

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --wheel flash-wheel --config crossfire_all_strategies_config.json
```

### Analyze one strategy

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --strategy crossfire_1_top
```

---

## Entry delay testing

### Test entry delays from 0 through 30

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --max-entry-delay 30
```

### Test entry delays from 0 through 60

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --max-entry-delay 60
```

---

## Betting limit scenarios

### Current higher threshold: max total exposure $2000

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --max-bet 2000
```

### Lower threshold: max total exposure $200

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --max-bet 200
```

---

## Progression scenarios

### Tripling progression

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --base 3
```

Progression:

```text
1, 3, 9, 27, 81, ...
```

### Doubling progression comparison

```powershell
python analyze_crossfire.py --db "C:\projects\roulette_dist\global_analysis\global_rolls.sqlite" --config crossfire_all_strategies_config.json --base 2
```

Progression:

```text
1, 2, 4, 8, 16, ...
```

---

## Suggested analysis workflow

1. Run global first.
2. Run each wheel individually.
3. Compare top entry delays by profit and drawdown.
4. Avoid choosing only highest profit if max drawdown is extreme.
5. Prefer candidates with strong profit, many sessions, low busts, and reasonable drawdown.

---

## Strategy names

```text
crossfire_1_top
crossfire_1_middle
crossfire_1_bottom
crossfire_2_top
crossfire_2_middle
crossfire_2_bottom
crossfire_3_top
crossfire_3_middle
crossfire_3_bottom
```
