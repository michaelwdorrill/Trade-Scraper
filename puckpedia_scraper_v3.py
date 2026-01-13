#!/usr/bin/env python3
"""
Puckpedia Trade Scraper v3 - Based on actual HTML structure

Scrapes trade data from puckpedia.com/trades (pages 0-46).

For each trade, extracts:
- Largest cap hit among all signed players
- Age, position, contract years of that player
- Trade date, summary text, and page URL

Usage:
    python puckpedia_scraper_v3.py [--output trades.csv] [--format csv|json] [--max-pages N]

Requirements:
    pip install -r requirements.txt
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from typing import Optional, List
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("Error: Required packages not installed.")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)


@dataclass
class PlayerInfo:
    """Information about a player in a trade."""
    name: str
    age: Optional[int] = None
    position: Optional[str] = None
    cap_hit: Optional[float] = None
    years_left: Optional[int] = None
    total_years: Optional[int] = None
    expiry_year: Optional[int] = None


@dataclass
class TradeData:
    """Data for a single trade with highest cap hit player info."""
    trade_date: str
    trade_summary: str
    trade_url: str
    highest_cap_hit: Optional[float] = None
    highest_cap_player_name: Optional[str] = None
    highest_cap_player_age: Optional[int] = None
    highest_cap_player_position: Optional[str] = None
    highest_cap_player_years_left: Optional[int] = None
    highest_cap_player_total_years: Optional[int] = None
    has_signed_players: bool = False
    all_players: List[dict] = field(default_factory=list)


class PuckpediaScraper:
    """Scraper for Puckpedia trade data based on actual HTML structure."""

    BASE_URL = "https://puckpedia.com"
    TRADES_URL = "https://puckpedia.com/trades"
    MAX_PAGE = 46  # Pages 0-46

    def __init__(self, delay: float = 1.0, debug: bool = False):
        self.session = requests.Session()
        # Comprehensive browser headers to avoid 403 blocks
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Cache-Control': 'max-age=0',
            'DNT': '1',
        })
        self.delay = delay
        self.debug = debug

    def fetch_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Fetch a page and return parsed BeautifulSoup object."""
        for attempt in range(retries):
            try:
                print(f"  Fetching: {url}")
                # Add Referer header to look more like normal browsing
                headers = {'Referer': self.TRADES_URL}
                response = self.session.get(url, timeout=30, headers=headers)
                response.raise_for_status()
                return BeautifulSoup(response.text, 'lxml')
            except requests.RequestException as e:
                print(f"    Attempt {attempt + 1}/{retries} failed: {e}")
                if '403' in str(e):
                    print("    Note: 403 errors often mean the site uses Cloudflare protection.")
                    print("    Try using a browser automation tool like Selenium or Playwright.")
                if attempt < retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    print(f"    Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
        return None

    def parse_cap_hit(self, text: str) -> Optional[float]:
        """Parse cap hit from text like '$1,950,000' or '$1.95M'."""
        if not text:
            return None

        # Try full format first: $1,950,000
        match = re.search(r'\$([\d,]+)', text)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass

        # Try abbreviated format: $1.95M or $950K
        match = re.search(r'\$([\d.]+)\s*([MK])', text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
                multiplier = match.group(2).upper()
                if multiplier == 'M':
                    return value * 1_000_000
                elif multiplier == 'K':
                    return value * 1_000
            except ValueError:
                pass

        return None

    def parse_contract_years(self, text: str) -> tuple[Optional[int], Optional[int]]:
        """
        Parse contract years from text like 'Yr 2/4'.

        'Yr 2' = current year of contract (2nd year)
        '/4' = total contract length (4 years)
        Returns: (years_left, total_years) where years_left = total - current + 1

        Example: 'Yr 2/4' -> years_left=3, total_years=4 (3 years remaining including this one)
        Example: 'Yr 2/2' -> years_left=1, total_years=2 (final year of contract)
        """
        if not text:
            return None, None

        # Look for pattern: Yr X/Y or just X/Y
        match = re.search(r'Yr\s*(\d+)\s*/\s*(\d+)', text, re.IGNORECASE)
        if match:
            current_year = int(match.group(1))
            total_years = int(match.group(2))
            years_left = total_years - current_year + 1
            return years_left, total_years

        # Fallback pattern without Yr prefix
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match:
            current_year = int(match.group(1))
            total_years = int(match.group(2))
            years_left = total_years - current_year + 1
            return years_left, total_years

        return None, None

    def extract_player_from_card(self, player_div: Tag) -> Optional[PlayerInfo]:
        """Extract player info from a player card div."""
        try:
            # Get player name from the link
            name_link = player_div.select_one('a.pp_link')
            if not name_link:
                return None
            name = name_link.get_text(strip=True)

            # Get age
            age = None
            age_span = player_div.find('span', string='age')
            if age_span:
                age_value = age_span.find_next_sibling('span')
                if age_value:
                    try:
                        age = int(age_value.get_text(strip=True))
                    except ValueError:
                        pass

            # Get position
            position = None
            pos_span = player_div.find('span', string='pos')
            if not pos_span:
                pos_span = player_div.find('span', string=re.compile(r'pos', re.IGNORECASE))
            if pos_span:
                pos_value = pos_span.find_next_sibling('span')
                if pos_value:
                    position = pos_value.get_text(strip=True)

            # Get contract years (Yr X/Y)
            years_left, total_years = None, None
            years_div = player_div.find(string=re.compile(r'Yr\s*\d+', re.IGNORECASE))
            if years_div:
                years_left, total_years = self.parse_contract_years(str(years_div.parent.get_text()))

            # Get expiry year
            expiry_year = None
            expiry_match = re.search(r'Exp(?:iry)?\s*(\d{4})', player_div.get_text())
            if expiry_match:
                expiry_year = int(expiry_match.group(1))

            # Get cap hit
            cap_hit = None
            cap_div = player_div.find('div', string=re.compile(r'Cap\s*Hit', re.IGNORECASE))
            if cap_div:
                # Cap hit value is in the next sibling div
                cap_value_div = cap_div.find_next_sibling('div')
                if cap_value_div:
                    cap_hit = self.parse_cap_hit(cap_value_div.get_text())

            # If we didn't find cap hit that way, try searching the whole card
            if not cap_hit:
                cap_hit = self.parse_cap_hit(player_div.get_text())

            # Only return if we found a name
            if name:
                return PlayerInfo(
                    name=name,
                    age=age,
                    position=position,
                    cap_hit=cap_hit,
                    years_left=years_left,
                    total_years=total_years,
                    expiry_year=expiry_year
                )
        except Exception as e:
            if self.debug:
                print(f"    Error parsing player card: {e}")

        return None

    def extract_players_from_trade(self, trade_div: Tag) -> List[PlayerInfo]:
        """Extract all players from a trade div."""
        players = []

        # Find all player card divs
        # Player cards have this structure: flex items-start mb-1 border border-pp-border rounded-lg
        player_cards = trade_div.select('div.flex.items-start.mb-1.border.rounded-lg')

        for card in player_cards:
            # Skip draft pick cards (they have "Draft Pick" text)
            if card.find(string=re.compile(r'Draft Pick', re.IGNORECASE)):
                continue

            # Skip "No Current Contract" players
            if card.find(string=re.compile(r'No Current Contract', re.IGNORECASE)):
                continue

            # Skip salary retained cards
            if card.find(string=re.compile(r'Salary Retained', re.IGNORECASE)):
                continue

            player = self.extract_player_from_card(card)
            if player and player.cap_hit and player.cap_hit > 0:
                players.append(player)

        return players

    def parse_trade(self, trade_header_div: Tag, trade_content_div: Tag) -> Optional[TradeData]:
        """Parse a single trade from its header and content divs."""
        try:
            # Extract trade date from header div
            # Format: "Trade ➤ Oct 1 2025"
            date_div = trade_header_div.select_one('div.pl-2.text-pp-copy_dk')
            trade_date = date_div.get_text(strip=True) if date_div else ""

            # Extract trade summary and URL from content div
            summary_link = trade_content_div.select_one('div.pp_content a')
            if summary_link:
                trade_summary = summary_link.get_text(strip=True)
                trade_url = urljoin(self.BASE_URL, summary_link.get('href', ''))
            else:
                trade_summary = ""
                trade_url = ""

            # Extract all players from the trade
            players = self.extract_players_from_trade(trade_content_div)

            if self.debug:
                print(f"    Date: {trade_date}")
                print(f"    Summary: {trade_summary[:80]}...")
                print(f"    URL: {trade_url}")
                print(f"    Players found: {len(players)}")
                for p in players:
                    print(f"      - {p.name}: ${p.cap_hit:,.0f}" if p.cap_hit else f"      - {p.name}")

            if players:
                # Find player with highest cap hit
                players_with_cap = [p for p in players if p.cap_hit and p.cap_hit > 0]
                if players_with_cap:
                    highest = max(players_with_cap, key=lambda p: p.cap_hit or 0)
                    return TradeData(
                        trade_date=trade_date,
                        trade_summary=trade_summary,
                        trade_url=trade_url,
                        highest_cap_hit=highest.cap_hit,
                        highest_cap_player_name=highest.name,
                        highest_cap_player_age=highest.age,
                        highest_cap_player_position=highest.position,
                        highest_cap_player_years_left=highest.years_left,
                        highest_cap_player_total_years=highest.total_years,
                        has_signed_players=True,
                        all_players=[asdict(p) for p in players]
                    )

            # Trade with no signed players (picks only or unsigned prospects)
            return TradeData(
                trade_date=trade_date,
                trade_summary=trade_summary,
                trade_url=trade_url,
                has_signed_players=False,
                all_players=[]
            )

        except Exception as e:
            print(f"    Error parsing trade: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    def scrape_page(self, page_num: int) -> List[TradeData]:
        """Scrape a single page of trades."""
        url = f"{self.TRADES_URL}?page={page_num}"
        print(f"\n[Page {page_num}] {url}")

        soup = self.fetch_page(url)
        if not soup:
            return []

        trades = []

        # Find all trade containers
        # Each trade has:
        # 1. A header div with class "flex items-end px-1.5 uppercase tracking-widest text-sm"
        # 2. A content div with class "border rounded-lg mb-8 border-pp-border"

        trade_containers = soup.select('div.border.rounded-lg.mb-8.border-pp-border')
        print(f"  Found {len(trade_containers)} trade containers")

        for i, trade_content in enumerate(trade_containers):
            # Find the preceding header div (contains the date)
            prev_sibling = trade_content.find_previous_sibling('div')
            if prev_sibling and 'tracking-widest' in ' '.join(prev_sibling.get('class', [])):
                trade_header = prev_sibling
            else:
                # Create a dummy header if not found
                trade_header = BeautifulSoup('<div></div>', 'html.parser').div

            print(f"  Parsing trade {i + 1}/{len(trade_containers)}...")
            trade = self.parse_trade(trade_header, trade_content)
            if trade:
                trades.append(trade)

        return trades

    def scrape_all(self, max_pages: Optional[int] = None) -> List[TradeData]:
        """Scrape all trades from all pages."""
        all_trades = []
        last_page = max_pages if max_pages else self.MAX_PAGE + 1

        for page in range(last_page):
            trades = self.scrape_page(page)
            all_trades.extend(trades)

            print(f"  Collected {len(trades)} trades, total: {len(all_trades)}")

            if page < last_page - 1:
                print(f"\n  Waiting {self.delay}s before next page...")
                time.sleep(self.delay)

        return all_trades


def save_csv(trades: List[TradeData], filename: str):
    """Save trades to CSV."""
    fieldnames = [
        'trade_date', 'trade_summary', 'trade_url',
        'highest_cap_hit', 'highest_cap_player_name',
        'highest_cap_player_age', 'highest_cap_player_position',
        'highest_cap_player_years_left', 'highest_cap_player_total_years',
        'has_signed_players'
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            row = asdict(trade)
            del row['all_players']  # Don't include nested list in CSV
            writer.writerow(row)

    print(f"\nSaved {len(trades)} trades to {filename}")


def save_json(trades: List[TradeData], filename: str):
    """Save trades to JSON."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump([asdict(t) for t in trades], f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(trades)} trades to {filename}")


def main():
    parser = argparse.ArgumentParser(description='Scrape NHL trades from Puckpedia')
    parser.add_argument('-o', '--output', default='puckpedia_trades.csv', help='Output file')
    parser.add_argument('-f', '--format', choices=['csv', 'json'], default='csv')
    parser.add_argument('-m', '--max-pages', type=int, help='Max pages to scrape (0-46)')
    parser.add_argument('-d', '--delay', type=float, default=1.5, help='Delay between pages')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    print("=" * 70)
    print("Puckpedia Trade Scraper v3")
    print("=" * 70)
    print(f"Output: {args.output} ({args.format})")
    print(f"Max pages: {args.max_pages or 'all (0-46)'}")
    print(f"Delay: {args.delay}s")
    print(f"Debug: {args.debug}")
    print("=" * 70)

    scraper = PuckpediaScraper(delay=args.delay, debug=args.debug)
    trades = scraper.scrape_all(max_pages=args.max_pages)

    if args.format == 'csv':
        save_csv(trades, args.output)
    else:
        save_json(trades, args.output)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total trades: {len(trades)}")

    with_players = [t for t in trades if t.has_signed_players]
    print(f"With signed players: {len(with_players)}")
    print(f"Picks/prospects only: {len(trades) - len(with_players)}")

    if with_players:
        caps = [t.highest_cap_hit for t in with_players if t.highest_cap_hit]
        if caps:
            print(f"Average highest cap: ${sum(caps)/len(caps):,.0f}")
            print(f"Max cap hit: ${max(caps):,.0f}")

            # Show top 5 highest cap trades
            print("\nTop 5 highest cap hit trades:")
            sorted_trades = sorted(with_players, key=lambda t: t.highest_cap_hit or 0, reverse=True)
            for i, t in enumerate(sorted_trades[:5], 1):
                print(f"  {i}. ${t.highest_cap_hit:,.0f} - {t.highest_cap_player_name} ({t.trade_date})")


if __name__ == '__main__':
    main()
