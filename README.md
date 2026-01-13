# Puckpedia Trade Scraper

A Python scraper to collect NHL trade data from [Puckpedia.com](https://puckpedia.com/trades).

## What It Collects

For each trade, the scraper extracts:

- **Largest cap hit** among all signed players involved in the trade
- **Player name** of the highest cap hit player
- **Age** of that player
- **Position** (C, LW, RW, D, G)
- **Years left** on their contract (from "YR X/Y" format)
- **Total years** on the original contract
- **Trade date**
- **Trade summary** (e.g., "The San Jose Sharks acquired Laurent Brossoit...")
- **Trade URL** link to the detailed trade page

Note: Some trades involve only draft picks and unsigned prospects - these will have `has_signed_players: false` and null cap hit data.

## Installation

```bash
# Clone or navigate to this directory
cd Trade-Scraper

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Scrape all trades and save to CSV
python puckpedia_scraper_v2.py

# Scrape with custom output file
python puckpedia_scraper_v2.py -o my_trades.csv

# Save as JSON instead
python puckpedia_scraper_v2.py -f json -o trades.json

# Limit to first 10 pages
python puckpedia_scraper_v2.py -m 10

# Slower scraping (more polite to server)
python puckpedia_scraper_v2.py -d 2.0
```

### Debug Mode

If the scraper isn't finding trades correctly, use debug mode to save raw HTML:

```bash
python puckpedia_scraper_v2.py --debug -m 1
```

This will:
1. Save raw HTML to `debug_html/` directory
2. Print detailed parsing information
3. Help identify the correct CSS selectors

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output` | Output filename | `puckpedia_trades.csv` |
| `-f, --format` | Output format (`csv` or `json`) | `csv` |
| `-m, --max-pages` | Maximum pages to scrape | All pages |
| `-d, --delay` | Delay between requests (seconds) | `1.5` |
| `--debug` | Enable debug mode | Off |

## Output Format

### CSV Columns

| Column | Description |
|--------|-------------|
| `trade_date` | Date of the trade (e.g., "JAN 8 2026") |
| `trade_summary` | Full trade description text |
| `trade_url` | Link to trade details page |
| `highest_cap_hit` | Largest cap hit amount (dollars) |
| `highest_cap_player_name` | Name of highest cap player |
| `highest_cap_player_age` | Age of that player |
| `highest_cap_player_position` | Position (C/LW/RW/D/G) |
| `highest_cap_player_years_left` | Years remaining on contract |
| `highest_cap_player_total_years` | Total contract length |
| `has_signed_players` | Whether trade included signed players |

### JSON Format

JSON output includes all the same fields, plus an `all_players` array with details for every player in the trade (not just the highest cap hit).

## Example Output

```csv
trade_date,trade_summary,trade_url,highest_cap_hit,highest_cap_player_name,highest_cap_player_age,highest_cap_player_position,highest_cap_player_years_left,highest_cap_player_total_years,has_signed_players
"JAN 8 2026","The San Jose Sharks acquired Laurent Brossoit, Nolan Allan and a 2028 7th round pick from the Chicago Blackhawks for Ryan Ellis, Jake Furlong and a 2028 4th round pick","https://puckpedia.com/trade/123",6250000,Ellis Ryan,35,D,7,8,True
```

## Troubleshooting

### "No trades found"

1. Run with `--debug` flag to inspect the HTML
2. Check if the website structure has changed
3. Try updating the CSS selectors in the code

### Connection Errors

1. Check your internet connection
2. Try increasing the delay: `-d 3.0`
3. The site may be blocking requests - try again later

### Missing Data

Some trades only involve draft picks and unsigned prospects. These trades will have:
- `has_signed_players: false`
- `highest_cap_hit: null`
- Other player fields as null

## Files

- `puckpedia_scraper_v2.py` - Main scraper script (recommended)
- `puckpedia_scraper.py` - Original simpler version
- `requirements.txt` - Python dependencies

## License

For personal use. Please be respectful of Puckpedia's servers and their terms of service.
