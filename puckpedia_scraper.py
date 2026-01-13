#!/usr/bin/env python3
"""
Puckpedia Trade Scraper

This script scrapes trade data from puckpedia.com/trades and extracts:
- Largest cap hit among all players involved in each trade
- Age of that player
- Number of years left on that player's contract
- Total years on the original contract
- That player's position
- Date of the trade
- Trade summary text
- Link to the trade page

Usage:
    python puckpedia_scraper.py [--output trades.csv] [--format csv|json] [--max-pages N]

Requirements:
    pip install requests beautifulsoup4 lxml
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: Required packages not installed.")
    print("Please run: pip install requests beautifulsoup4 lxml")
    sys.exit(1)


@dataclass
class TradeData:
    """Data class representing a single trade with the highest cap hit player info."""
    trade_date: str
    trade_summary: str
    trade_url: str
    highest_cap_hit: Optional[float]
    highest_cap_player_name: Optional[str]
    highest_cap_player_age: Optional[int]
    highest_cap_player_position: Optional[str]
    highest_cap_player_years_left: Optional[int]
    highest_cap_player_total_years: Optional[int]
    has_signed_players: bool


class PuckpediaScraper:
    """Scraper for Puckpedia trade data."""

    BASE_URL = "https://puckpedia.com"
    TRADES_URL = "https://puckpedia.com/trades"

    def __init__(self, delay: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.delay = delay

    def fetch_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Fetch a page and return parsed BeautifulSoup object."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return BeautifulSoup(response.text, 'lxml')
            except requests.RequestException as e:
                print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        return None

    def parse_cap_hit(self, cap_text: str) -> Optional[float]:
        """Parse cap hit string like '$825,000' or '$6,250,000' to float."""
        if not cap_text:
            return None
        # Remove $ and commas, convert to float
        cleaned = cap_text.replace('$', '').replace(',', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def parse_contract_years(self, years_text: str) -> tuple[Optional[int], Optional[int]]:
        """
        Parse contract years like 'YR 5/5' or 'YR 3/4'.
        Returns (years_left, total_years).
        """
        if not years_text:
            return None, None
        # Look for pattern like "5/5" or "3/4"
        match = re.search(r'(\d+)\s*/\s*(\d+)', years_text)
        if match:
            years_left = int(match.group(1))
            total_years = int(match.group(2))
            return years_left, total_years
        return None, None

    def parse_age(self, age_text: str) -> Optional[int]:
        """Parse age from text like 'age 22' or '22'."""
        if not age_text:
            return None
        match = re.search(r'(\d+)', str(age_text))
        if match:
            return int(match.group(1))
        return None

    def parse_trade_date(self, date_element) -> str:
        """Parse trade date from the trade header."""
        if not date_element:
            return ""
        # Look for date text like "JAN 8 2026"
        text = date_element.get_text(strip=True)
        # Extract date portion after "TRADE"
        match = re.search(r'(?:TRADE\s*[➤→]?\s*)?([A-Z]{3}\s+\d{1,2}\s+\d{4})', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text

    def extract_players_from_trade(self, trade_element) -> list[dict]:
        """Extract all player information from a trade element."""
        players = []

        # Find all player rows/cards in the trade
        # Based on the screenshot, players have name, age, position, contract info, and cap hit
        player_elements = trade_element.select('.player-row, .trade-player, [class*="player"]')

        if not player_elements:
            # Try alternative selectors based on common patterns
            player_elements = trade_element.find_all(['div', 'tr'], class_=lambda x: x and ('player' in x.lower() if x else False))

        for player_el in player_elements:
            player_data = self.extract_player_data(player_el)
            if player_data and player_data.get('cap_hit'):
                players.append(player_data)

        return players

    def extract_player_data(self, player_element) -> Optional[dict]:
        """Extract individual player data from a player element."""
        try:
            text = player_element.get_text(' ', strip=True)

            # Extract name - usually the first text
            name_el = player_element.select_one('[class*="name"], .player-name, a')
            name = name_el.get_text(strip=True) if name_el else None

            # Extract age - look for "age XX" pattern
            age = None
            age_match = re.search(r'age\s*(\d+)', text, re.IGNORECASE)
            if age_match:
                age = int(age_match.group(1))

            # Extract position - look for "pos X" or single letter positions
            position = None
            pos_match = re.search(r'pos\s*([A-Z]+)', text, re.IGNORECASE)
            if pos_match:
                position = pos_match.group(1)

            # Extract contract years - look for "YR X/Y"
            years_left, total_years = None, None
            years_match = re.search(r'YR\s*(\d+)\s*/\s*(\d+)', text, re.IGNORECASE)
            if years_match:
                years_left = int(years_match.group(1))
                total_years = int(years_match.group(2))

            # Extract cap hit - look for $X,XXX,XXX pattern
            cap_hit = None
            cap_match = re.search(r'\$[\d,]+', text)
            if cap_match:
                cap_hit = self.parse_cap_hit(cap_match.group())

            if cap_hit:  # Only return if we found a cap hit
                return {
                    'name': name,
                    'age': age,
                    'position': position,
                    'years_left': years_left,
                    'total_years': total_years,
                    'cap_hit': cap_hit
                }
        except Exception as e:
            print(f"  Error parsing player: {e}")

        return None

    def parse_trade_element(self, trade_element, page_url: str) -> Optional[TradeData]:
        """Parse a single trade element and return TradeData."""
        try:
            # Extract trade date
            date_el = trade_element.select_one('[class*="date"], [class*="trade-header"], .trade-date')
            if not date_el:
                # Try finding text that contains a date pattern
                header = trade_element.find(string=re.compile(r'[A-Z]{3}\s+\d{1,2}\s+\d{4}'))
                trade_date = header.strip() if header else ""
            else:
                trade_date = self.parse_trade_date(date_el)

            # Extract trade summary - usually at the top of the trade card
            summary_el = trade_element.select_one('[class*="summary"], [class*="description"], .trade-summary, .trade-text')
            if summary_el:
                trade_summary = summary_el.get_text(' ', strip=True)
            else:
                # Try to find the descriptive text
                trade_summary = ""
                for el in trade_element.select('p, span, div'):
                    text = el.get_text(strip=True)
                    if 'acquired' in text.lower():
                        trade_summary = text
                        break

            # Extract trade URL
            link_el = trade_element.select_one('a[href*="trade"]')
            if link_el and link_el.get('href'):
                trade_url = urljoin(self.BASE_URL, link_el['href'])
            else:
                trade_url = page_url

            # Extract all players from this trade
            players = self.extract_players_from_trade(trade_element)

            # Find player with highest cap hit
            if players:
                highest_cap_player = max(players, key=lambda p: p.get('cap_hit', 0) or 0)
                return TradeData(
                    trade_date=trade_date,
                    trade_summary=trade_summary,
                    trade_url=trade_url,
                    highest_cap_hit=highest_cap_player.get('cap_hit'),
                    highest_cap_player_name=highest_cap_player.get('name'),
                    highest_cap_player_age=highest_cap_player.get('age'),
                    highest_cap_player_position=highest_cap_player.get('position'),
                    highest_cap_player_years_left=highest_cap_player.get('years_left'),
                    highest_cap_player_total_years=highest_cap_player.get('total_years'),
                    has_signed_players=True
                )
            else:
                # Trade with no signed players (picks only)
                return TradeData(
                    trade_date=trade_date,
                    trade_summary=trade_summary,
                    trade_url=trade_url,
                    highest_cap_hit=None,
                    highest_cap_player_name=None,
                    highest_cap_player_age=None,
                    highest_cap_player_position=None,
                    highest_cap_player_years_left=None,
                    highest_cap_player_total_years=None,
                    has_signed_players=False
                )

        except Exception as e:
            print(f"  Error parsing trade: {e}")
            return None

    def scrape_trades_page(self, page_num: int) -> tuple[list[TradeData], bool]:
        """
        Scrape a single page of trades.
        Returns (list of TradeData, has_more_pages).
        """
        url = f"{self.TRADES_URL}?page={page_num}"
        print(f"Fetching page {page_num}: {url}")

        soup = self.fetch_page(url)
        if not soup:
            print(f"  Failed to fetch page {page_num}")
            return [], False

        trades = []

        # Find trade containers - adjust selectors based on actual HTML structure
        trade_elements = soup.select('.trade-card, .trade-item, .trade-row, [class*="trade"]')

        if not trade_elements:
            # Try alternative approach - look for divs with trade-like content
            trade_elements = soup.find_all('div', class_=lambda x: x and 'trade' in x.lower() if x else False)

        print(f"  Found {len(trade_elements)} potential trade elements")

        for trade_el in trade_elements:
            trade_data = self.parse_trade_element(trade_el, url)
            if trade_data:
                trades.append(trade_data)

        # Check if there are more pages
        has_more = self.has_next_page(soup, page_num)

        return trades, has_more

    def has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        """Check if there's a next page of trades."""
        # Look for pagination elements
        next_link = soup.select_one(f'a[href*="page={current_page + 1}"], .next-page, [class*="next"]')
        if next_link:
            return True

        # Check for page numbers
        page_links = soup.select('[class*="pagination"] a, .pages a')
        for link in page_links:
            href = link.get('href', '')
            if f'page={current_page + 1}' in href:
                return True

        return False

    def scrape_all_trades(self, max_pages: Optional[int] = None) -> list[TradeData]:
        """Scrape all trades from the website."""
        all_trades = []
        page_num = 0

        while True:
            if max_pages and page_num >= max_pages:
                print(f"\nReached max pages limit ({max_pages})")
                break

            trades, has_more = self.scrape_trades_page(page_num)
            all_trades.extend(trades)

            print(f"  Collected {len(trades)} trades from page {page_num}")
            print(f"  Total trades so far: {len(all_trades)}")

            if not has_more:
                print("\nNo more pages to scrape")
                break

            page_num += 1
            time.sleep(self.delay)  # Be respectful to the server

        return all_trades


def save_to_csv(trades: list[TradeData], filename: str):
    """Save trades to CSV file."""
    if not trades:
        print("No trades to save")
        return

    fieldnames = [
        'trade_date',
        'trade_summary',
        'trade_url',
        'highest_cap_hit',
        'highest_cap_player_name',
        'highest_cap_player_age',
        'highest_cap_player_position',
        'highest_cap_player_years_left',
        'highest_cap_player_total_years',
        'has_signed_players'
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(asdict(trade))

    print(f"\nSaved {len(trades)} trades to {filename}")


def save_to_json(trades: list[TradeData], filename: str):
    """Save trades to JSON file."""
    if not trades:
        print("No trades to save")
        return

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump([asdict(t) for t in trades], f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(trades)} trades to {filename}")


def main():
    parser = argparse.ArgumentParser(
        description='Scrape NHL trade data from Puckpedia',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python puckpedia_scraper.py
    python puckpedia_scraper.py --output trades.csv --format csv
    python puckpedia_scraper.py --output trades.json --format json --max-pages 10
    python puckpedia_scraper.py --delay 2.0  # Slower scraping to be gentle on server
        """
    )
    parser.add_argument(
        '--output', '-o',
        default='puckpedia_trades.csv',
        help='Output filename (default: puckpedia_trades.csv)'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['csv', 'json'],
        default='csv',
        help='Output format (default: csv)'
    )
    parser.add_argument(
        '--max-pages', '-m',
        type=int,
        default=None,
        help='Maximum number of pages to scrape (default: all)'
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=1.0,
        help='Delay between page requests in seconds (default: 1.0)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Puckpedia Trade Scraper")
    print("=" * 60)
    print(f"Output file: {args.output}")
    print(f"Output format: {args.format}")
    print(f"Max pages: {args.max_pages or 'unlimited'}")
    print(f"Request delay: {args.delay}s")
    print("=" * 60)
    print()

    scraper = PuckpediaScraper(delay=args.delay)
    trades = scraper.scrape_all_trades(max_pages=args.max_pages)

    if args.format == 'csv':
        save_to_csv(trades, args.output)
    else:
        save_to_json(trades, args.output)

    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total trades scraped: {len(trades)}")

    trades_with_players = [t for t in trades if t.has_signed_players]
    print(f"Trades with signed players: {len(trades_with_players)}")
    print(f"Trades with only picks/unsigned prospects: {len(trades) - len(trades_with_players)}")

    if trades_with_players:
        avg_cap_hit = sum(t.highest_cap_hit for t in trades_with_players if t.highest_cap_hit) / len(trades_with_players)
        max_cap = max(t.highest_cap_hit for t in trades_with_players if t.highest_cap_hit)
        print(f"Average highest cap hit: ${avg_cap_hit:,.0f}")
        print(f"Largest cap hit in any trade: ${max_cap:,.0f}")


if __name__ == '__main__':
    main()
