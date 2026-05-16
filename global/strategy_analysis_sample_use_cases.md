# Strategy Analysis Sample Use Cases

## Recommended EU-hosted approach

Put these files on the EU server:

```text
C:\Roll\global\analyze_strategies.py
C:\Roll\global\strategy_analysis_config_all.json
```

Run from EU:

```powershell
cd C:\Roll\global
C:\Roll\python-embed\App\Python\python.exe analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --category crossfire
```

## Analyze all strategies globally

```powershell
python analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --strategy all
```

## Analyze only Crossfire globally

```powershell
python analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --category crossfire
```

## Analyze Crossfire per wheel

```powershell
python analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --wheel eu-wheel --category crossfire
python analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --wheel flash-wheel --category crossfire
python analyze_strategies.py --db C:\Roll\global\global_rolls.sqlite --wheel classic-wheel --category crossfire
```

## Analyze all strategies per wheel

```powershell
python analyze_strategies.py --wheel eu-wheel --strategy all
python analyze_strategies.py --wheel flash-wheel --strategy all
python analyze_strategies.py --wheel classic-wheel --strategy all
```

## Analyze one exact strategy

```powershell
python analyze_strategies.py --strategy "Crossfire, 1st & top"
python analyze_strategies.py --strategy "Red"
python analyze_strategies.py --strategy "Neighbors 0 ±3"
```

## Analyze rolling recent history

```powershell
python analyze_strategies.py --category crossfire --rolling 2000
python analyze_strategies.py --strategy all --rolling 500
```

## Change maximum exposure and progression

```powershell
python analyze_strategies.py --category crossfire --max-bet 2000 --base 3
python analyze_strategies.py --category crossfire --max-bet 200 --base 3
python analyze_strategies.py --category crossfire --base 2
```

## Entry delay range

```powershell
python analyze_strategies.py --category crossfire --min-entry-delay 5 --max-entry-delay 10
```

## Save to a specific CSV

```powershell
python analyze_strategies.py --category crossfire --out C:\Roll\global\crossfire_analysis.csv
```

## Available categories

```text
outside
dozen
row
two_dozen
two_row
crossfire
line
street
french
horizontal_double
vertical_double
zero_double
quad
zero_triple
neighbors
```

## Profit model

Each strategy has one or more components. Each component is modeled as one chip group with the same progression stake.

Example:

```text
Crossfire, 1st & top
$N on 1st & 12
$N on Top Row
```

Result:

```text
Miss both = -2N
Hit one = +N
Hit overlap = +4N
```

The simulator stops the session on any hit by default.
