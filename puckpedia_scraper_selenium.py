#!/usr/bin/env python3
"""
Puckpedia Trade Scraper - Selenium Version

Uses Selenium to bypass Cloudflare/bot protection that blocks regular requests.

Scrapes trade data from puckpedia.com/trades (pages 0-46).

For each trade, extracts:
- Largest cap hit among all signed players
- Age, position, contract years of that player
- Trade date, summary text, and page URL

Usage:
    python puckpedia_scraper_selenium.py [--output trades.csv] [--format csv|json] [--max-pages N]

Requirements:
    pip install selenium webdriver-manager beautifulsoup4 lxml
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from typing import Optional, List

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from webdriver_manager.chrome import ChromeDriverManager
    from bs4 import BeautifulSoup, Tag
except ImportError as e:
    print(f"Error: Required package not installed: {e}")
    print("Please run: pip install selenium webdriver-manager beautifulsoup4 lxml")
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


class PuckpediaSeleniumScraper:
    """Selenium-based scraper for Puckpedia trade data."""

    BASE_URL = "https://puckpedia.com"
    TRADES_URL = "https://puckpedia.com/trades"
    MAX_PAGE = 46  # Pages 0-46

    def __init__(self, delay: float = 2.0, debug: bool = False, headless: bool = True):
        self.delay = delay
        self.debug = debug
        self.headless = headless
        self.driver = None

    def setup_driver(self):
        """Initialize the Selenium WebDriver."""
        options = Options()
        if self.headless:
            options.add_argument('--headless=new')

        # Make Chrome look more like a regular browser
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

        # Disable automation flags
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)

            # Additional anti-detection
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })

            print("Chrome WebDriver initialized successfully")
        except Exception as e:
            print(f"Error initializing WebDriver: {e}")
            print("\nTroubleshooting:")
            print("1. Make sure Chrome is installed")
            print("2. Try: pip install --upgrade selenium webdriver-manager")
            sys.exit(1)

    def close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def fetch_page(self, url: str, wait_time: int = 10) -> Optional[BeautifulSoup]:
        """Fetch a page using Selenium and return parsed BeautifulSoup object."""
        try:
            print(f"  Fetching: {url}")
            self.driver.get(url)

            # Wait for trade content to load
            WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.border.rounded-lg.mb-8"))
            )

            # Additional wait for dynamic content
            time.sleep(1)

            html = self.driver.page_source
            return BeautifulSoup(html, 'lxml')

        except TimeoutException:
            print(f"    Timeout waiting for page content")
            # Try to get whatever loaded
            html = self.driver.page_source
            if 'trade' in html.lower():
                return BeautifulSoup(html, 'lxml')
            return None
        except WebDriverException as e:
            print(f"    WebDriver error: {e}")
            return None

    def parse_cap_hit(self, text: str) -> Optional[float]:
        """Parse cap hit from text like '$1,950,000' or '$1.95M'."""
        if not text:
            return None

        # Try full format: $1,950,000
        match = re.search(r'\$([0-9,]+)(?:\s|$)', text)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass

        # Try abbreviated format: $1.95M
        match = re.search(r'\$([\d.]+)M', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1)) * 1_000_000
            except ValueError:
                pass

        # Try K format: $950K
        match = re.search(r'\$([\d.]+)K', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1)) * 1_000
            except ValueError:
                pass

        return None

    def parse_contract_years(self, text: str) -> tuple[Optional[int], Optional[int]]:
        """Parse contract years from text like 'Yr 2/4' -> (years_left=2, total_years=4)."""
        if not text:
            return None, None

        match = re.search(r'Yr\s*(\d+)/(\d+)', text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def parse_player_card(self, player_div: Tag) -> Optional[PlayerInfo]:
        """Parse a player card div to extract player information."""
        # Get all text content
        text_content = player_div.get_text(separator=' ', strip=True)

        # Skip draft picks and salary retained
        if 'Draft Pick' in text_content or 'Salary Retained' in text_content:
            return None

        # Skip if no current contract
        if 'No Current Contract' in text_content:
            return None

        # Find player name (look for pp_link class)
        name_link = player_div.select_one('a.pp_link')
        if not name_link:
            # Try any link that looks like a player link
            for link in player_div.select('a[href*="/player/"]'):
                name_link = link
                break

        if not name_link:
            return None

        name = name_link.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        player = PlayerInfo(name=name)

        # Parse age - look for "age" label followed by value
        age_match = re.search(r'age\s*(\d+)', text_content, re.IGNORECASE)
        if age_match:
            player.age = int(age_match.group(1))

        # Parse position - look for "pos" label followed by value
        pos_match = re.search(r'pos\s*(C|LW|RW|D|G|F|W)', text_content, re.IGNORECASE)
        if pos_match:
            player.position = pos_match.group(1).upper()

        # Parse contract years
        player.years_left, player.total_years = self.parse_contract_years(text_content)

        # Parse cap hit
        player.cap_hit = self.parse_cap_hit(text_content)

        return player

    def parse_trade(self, trade_div: Tag) -> Optional[TradeData]:
        """Parse a trade container div to extract trade information."""
        # Find trade date - in the header area
        date_div = trade_div.select_one('div.pl-2.text-pp-copy_dk')
        if not date_div:
            # Try alternative selectors
            date_div = trade_div.select_one('div.text-pp-copy_dk')

        trade_date = date_div.get_text(strip=True) if date_div else "Unknown Date"

        # Find trade summary and URL
        summary_link = trade_div.select_one('div.pp_content a')
        if not summary_link:
            # Try alternative
            summary_link = trade_div.select_one('a[href*="/trade/"]')

        if summary_link:
            trade_summary = summary_link.get_text(strip=True)
            trade_url = summary_link.get('href', '')
            if trade_url and not trade_url.startswith('http'):
                trade_url = self.BASE_URL + trade_url
        else:
            trade_summary = "Unknown Trade"
            trade_url = ""

        trade = TradeData(
            trade_date=trade_date,
            trade_summary=trade_summary,
            trade_url=trade_url
        )

        # Find all player cards
        player_cards = trade_div.select('div.flex.items-start.mb-1.border.rounded-lg')
        if not player_cards:
            # Try alternative selector
            player_cards = trade_div.select('div.border.rounded-lg.p-2')

        players = []
        highest_cap_player = None

        for card in player_cards:
            player = self.parse_player_card(card)
            if player:
                players.append(player)
                if player.cap_hit is not None:
                    if highest_cap_player is None or player.cap_hit > (highest_cap_player.cap_hit or 0):
                        highest_cap_player = player

        if self.debug:
            print(f"    Found {len(players)} players in trade")
            for p in players:
                print(f"      - {p.name}: cap_hit={p.cap_hit}")

        # Store all players
        trade.all_players = [asdict(p) for p in players]

        # Set highest cap hit player info
        if highest_cap_player and highest_cap_player.cap_hit:
            trade.has_signed_players = True
            trade.highest_cap_hit = highest_cap_player.cap_hit
            trade.highest_cap_player_name = highest_cap_player.name
            trade.highest_cap_player_age = highest_cap_player.age
            trade.highest_cap_player_position = highest_cap_player.position
            trade.highest_cap_player_years_left = highest_cap_player.years_left
            trade.highest_cap_player_total_years = highest_cap_player.total_years

        return trade

    def scrape_page(self, page_num: int) -> List[TradeData]:
        """Scrape a single page of trades."""
        url = f"{self.TRADES_URL}?page={page_num}"
        soup = self.fetch_page(url)

        if not soup:
            print(f"    Failed to fetch page {page_num}")
            return []

        # Find all trade containers
        trade_divs = soup.select('div.border.rounded-lg.mb-8.border-pp-border')
        if not trade_divs:
            # Try without the border-pp-border class
            trade_divs = soup.select('div.border.rounded-lg.mb-8')

        if self.debug:
            print(f"    Found {len(trade_divs)} trade containers on page {page_num}")

        trades = []
        for trade_div in trade_divs:
            trade = self.parse_trade(trade_div)
            if trade:
                trades.append(trade)

        return trades

    def scrape_all(self, max_pages: Optional[int] = None) -> List[TradeData]:
        """Scrape all trade pages."""
        self.setup_driver()

        try:
            all_trades = []
            end_page = min(self.MAX_PAGE, max_pages - 1) if max_pages else self.MAX_PAGE

            for page in range(0, end_page + 1):
                print(f"[Page {page}] {self.TRADES_URL}?page={page}")

                trades = self.scrape_page(page)
                all_trades.extend(trades)

                print(f"  Collected {len(trades)} trades, total: {len(all_trades)}")

                if page < end_page:
                    print(f"\n  Waiting {self.delay}s before next page...")
                    time.sleep(self.delay)

            return all_trades
        finally:
            self.close_driver()


def save_csv(trades: List[TradeData], filename: str):
    """Save trades to CSV file."""
    if not trades:
        print("No trades to save")
        return

    fieldnames = [
        'trade_date', 'trade_summary', 'trade_url',
        'highest_cap_hit', 'highest_cap_player_name',
        'highest_cap_player_age', 'highest_cap_player_position',
        'highest_cap_player_years_left', 'highest_cap_player_total_years',
        'has_signed_players'
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for trade in trades:
            writer.writerow(asdict(trade))

    print(f"Saved {len(trades)} trades to {filename}")


def save_json(trades: List[TradeData], filename: str):
    """Save trades to JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump([asdict(t) for t in trades], f, indent=2)

    print(f"Saved {len(trades)} trades to {filename}")


def main():
    parser = argparse.ArgumentParser(description='Scrape NHL trade data from Puckpedia (Selenium version)')
    parser.add_argument('-o', '--output', default='trades_selenium.csv',
                        help='Output file name (default: trades_selenium.csv)')
    parser.add_argument('-f', '--format', choices=['csv', 'json'], default='csv',
                        help='Output format (default: csv)')
    parser.add_argument('-m', '--max-pages', type=int,
                        help='Maximum number of pages to scrape (default: all 47 pages)')
    parser.add_argument('-d', '--delay', type=float, default=2.0,
                        help='Delay between page requests in seconds (default: 2.0)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode with verbose output')
    parser.add_argument('--no-headless', action='store_true',
                        help='Run browser in visible mode (not headless)')

    args = parser.parse_args()

    print("=" * 60)
    print("Puckpedia Trade Scraper (Selenium Version)")
    print("=" * 60)
    print(f"Output: {args.output}")
    print(f"Format: {args.format}")
    print(f"Max pages: {args.max_pages or 'all (47)'}")
    print(f"Delay: {args.delay}s")
    print(f"Headless: {not args.no_headless}")
    print("=" * 60)

    scraper = PuckpediaSeleniumScraper(
        delay=args.delay,
        debug=args.debug,
        headless=not args.no_headless
    )

    trades = scraper.scrape_all(max_pages=args.max_pages)

    print("\n" + "=" * 60)
    print(f"Scraping complete! Total trades: {len(trades)}")

    trades_with_cap = [t for t in trades if t.has_signed_players]
    print(f"Trades with signed players: {len(trades_with_cap)}")
    print("=" * 60)

    if args.format == 'json':
        save_json(trades, args.output)
    else:
        save_csv(trades, args.output)


if __name__ == '__main__':
    main()
