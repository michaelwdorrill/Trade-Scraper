#!/usr/bin/env python3
"""
Puckpedia Trade Scraper - Enhanced Version

This script scrapes trade data from puckpedia.com/trades with better HTML parsing
and debug capabilities.

For each trade, it extracts:
- Largest cap hit among all players involved
- Age of that player
- Number of years left on that player's contract
- Total years on the original contract
- That player's position
- Date of the trade
- Trade summary text
- Link to the trade page

Usage:
    python puckpedia_scraper_v2.py [--output trades.csv] [--format csv|json] [--max-pages N]
    python puckpedia_scraper_v2.py --debug  # Save raw HTML for inspection

Requirements:
    pip install -r requirements.txt
"""

import argparse
import csv
import json
import os
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
    """Data class representing a single trade with the highest cap hit player info."""
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
    """Enhanced scraper for Puckpedia trade data."""

    BASE_URL = "https://puckpedia.com"
    TRADES_URL = "https://puckpedia.com/trades"

    def __init__(self, delay: float = 1.0, debug: bool = False):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        self.delay = delay
        self.debug = debug
        self.debug_dir = "debug_html"

    def fetch_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Fetch a page and return parsed BeautifulSoup object."""
        for attempt in range(retries):
            try:
                print(f"  Fetching: {url}")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()

                if self.debug:
                    self._save_debug_html(url, response.text)

                return BeautifulSoup(response.text, 'lxml')
            except requests.RequestException as e:
                print(f"    Attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    print(f"    Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
        return None

    def _save_debug_html(self, url: str, html: str):
        """Save raw HTML for debugging."""
        if not os.path.exists(self.debug_dir):
            os.makedirs(self.debug_dir)

        # Create filename from URL
        filename = re.sub(r'[^\w\-_]', '_', url.replace(self.BASE_URL, ''))
        filepath = os.path.join(self.debug_dir, f"{filename}.html")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"    Saved debug HTML to: {filepath}")

    def parse_cap_hit(self, text: str) -> Optional[float]:
        """Parse cap hit string like '$825,000' or '$6,250,000' to float."""
        if not text:
            return None
        match = re.search(r'\$[\d,]+', text)
        if match:
            cleaned = match.group().replace('$', '').replace(',', '')
            try:
                return float(cleaned)
            except ValueError:
                pass
        return None

    def parse_contract_years(self, text: str) -> tuple[Optional[int], Optional[int]]:
        """
        Parse contract years like 'YR 5/5' or 'YR 3/4'.
        Returns (years_left, total_years).
        """
        if not text:
            return None, None
        match = re.search(r'YR\s*(\d+)\s*/\s*(\d+)', text, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
        # Try without YR prefix
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def discover_html_structure(self, soup: BeautifulSoup) -> dict:
        """Analyze the HTML structure to find trade elements."""
        structure = {
            'trade_containers': [],
            'player_containers': [],
            'date_elements': [],
            'cap_hit_elements': []
        }

        # Look for common patterns
        for tag in soup.find_all(['div', 'article', 'section', 'tr']):
            classes = tag.get('class', [])
            class_str = ' '.join(classes) if classes else ''

            # Look for trade-related elements
            if 'trade' in class_str.lower():
                structure['trade_containers'].append({
                    'tag': tag.name,
                    'classes': classes,
                    'sample': tag.get_text()[:100]
                })

            # Look for player-related elements
            if 'player' in class_str.lower():
                structure['player_containers'].append({
                    'tag': tag.name,
                    'classes': classes
                })

        return structure

    def find_trades_on_page(self, soup: BeautifulSoup) -> List[Tag]:
        """Find all trade elements on the page using multiple strategies."""
        trade_elements = []

        # Strategy 1: Look for elements with 'trade' in class
        selectors = [
            '[class*="trade-card"]',
            '[class*="trade-item"]',
            '[class*="trade-row"]',
            '[class*="tradeCard"]',
            '[class*="TradeCard"]',
            'div[class*="trade"]',
            'article[class*="trade"]',
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                print(f"    Found {len(elements)} trades using selector: {selector}")
                trade_elements.extend(elements)
                break

        # Strategy 2: Look for containers with trade text patterns
        if not trade_elements:
            # Find elements containing "acquired" text
            for div in soup.find_all('div'):
                text = div.get_text()
                if 'acquired' in text.lower() and len(text) < 500:
                    # Check if this looks like a trade summary
                    if re.search(r'from the .* for', text, re.IGNORECASE):
                        parent = div.find_parent(['div', 'article', 'section'])
                        if parent and parent not in trade_elements:
                            trade_elements.append(parent)

        # Strategy 3: Look for date + team logo patterns
        if not trade_elements:
            date_pattern = re.compile(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2}\s+\d{4}', re.IGNORECASE)
            for element in soup.find_all(string=date_pattern):
                parent = element.find_parent(['div', 'article', 'section'])
                if parent and parent not in trade_elements:
                    trade_elements.append(parent)

        return trade_elements

    def extract_trade_date(self, trade_element: Tag) -> str:
        """Extract the trade date from a trade element."""
        text = trade_element.get_text()
        # Look for date pattern
        match = re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2},?\s*\d{4}', text, re.IGNORECASE)
        if match:
            return match.group()
        return ""

    def extract_trade_summary(self, trade_element: Tag) -> str:
        """Extract the trade summary text."""
        text = trade_element.get_text(' ', strip=True)
        # Look for the "Team acquired X from Y for Z" pattern
        match = re.search(r'The\s+[\w\s]+acquired[\s\S]*?(?:from|for)[\s\S]*?(?:pick|prospect|\d{4})', text, re.IGNORECASE)
        if match:
            summary = match.group().strip()
            # Clean up the summary
            summary = re.sub(r'\s+', ' ', summary)
            return summary[:500]  # Limit length

        # Alternative: look for text containing "acquired"
        for element in trade_element.find_all(['p', 'span', 'div', 'a']):
            el_text = element.get_text(strip=True)
            if 'acquired' in el_text.lower() and len(el_text) > 20:
                return el_text[:500]

        return ""

    def extract_trade_url(self, trade_element: Tag) -> str:
        """Extract the URL for the trade detail page."""
        # Look for links within the trade element
        for link in trade_element.find_all('a'):
            href = link.get('href', '')
            if 'trade' in href.lower() or '/t/' in href:
                return urljoin(self.BASE_URL, href)

        # Look for "DETAILS" or "Comments" link
        for link in trade_element.find_all('a'):
            text = link.get_text(strip=True).lower()
            if 'detail' in text or 'comment' in text:
                return urljoin(self.BASE_URL, link.get('href', ''))

        return ""

    def extract_players(self, trade_element: Tag) -> List[PlayerInfo]:
        """Extract all players from a trade element."""
        players = []
        text = trade_element.get_text(' ', strip=True)

        # Look for player patterns in the text
        # Pattern: Name, age XX pos Y, YR X/X, $X,XXX,XXX
        player_pattern = re.compile(
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*'  # Name
            r'(?:age\s*)?(\d{2})\s*'  # Age
            r'(?:pos\s*)?([CLFWRGD]+)\s*'  # Position
            r'.*?'
            r'YR\s*(\d+)\s*/\s*(\d+)\s*'  # Contract years
            r'.*?'
            r'\$?([\d,]+)',  # Cap hit
            re.IGNORECASE
        )

        for match in player_pattern.finditer(text):
            try:
                cap_hit = float(match.group(6).replace(',', ''))
                if cap_hit > 100000:  # Likely a real cap hit
                    player = PlayerInfo(
                        name=match.group(1).strip(),
                        age=int(match.group(2)),
                        position=match.group(3).upper(),
                        years_left=int(match.group(4)),
                        total_years=int(match.group(5)),
                        cap_hit=cap_hit
                    )
                    players.append(player)
            except (ValueError, IndexError):
                continue

        # Alternative approach: look for structured elements
        if not players:
            # Find elements that look like player rows
            for element in trade_element.find_all(['div', 'tr', 'li']):
                el_text = element.get_text(' ', strip=True)

                # Check if this element has cap hit info
                cap_match = re.search(r'\$[\d,]+', el_text)
                if not cap_match:
                    continue

                cap_hit = self.parse_cap_hit(cap_match.group())
                if not cap_hit or cap_hit < 100000:
                    continue

                # Extract other info
                name = None
                age = None
                position = None
                years_left = None
                total_years = None

                # Look for name (typically at start or in a link)
                name_link = element.find('a')
                if name_link:
                    name = name_link.get_text(strip=True)
                else:
                    # First capitalized words
                    name_match = re.match(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', el_text)
                    if name_match:
                        name = name_match.group(1)

                # Age
                age_match = re.search(r'age\s*(\d{2})', el_text, re.IGNORECASE)
                if age_match:
                    age = int(age_match.group(1))
                else:
                    age_match = re.search(r'\b(\d{2})\b', el_text)
                    if age_match and 18 <= int(age_match.group(1)) <= 45:
                        age = int(age_match.group(1))

                # Position
                pos_match = re.search(r'pos\s*([CLFWRGD]+)', el_text, re.IGNORECASE)
                if pos_match:
                    position = pos_match.group(1).upper()
                else:
                    pos_match = re.search(r'\b([CLFWRGD])\b', el_text)
                    if pos_match:
                        position = pos_match.group(1).upper()

                # Contract years
                years_left, total_years = self.parse_contract_years(el_text)

                if name:
                    player = PlayerInfo(
                        name=name,
                        age=age,
                        position=position,
                        cap_hit=cap_hit,
                        years_left=years_left,
                        total_years=total_years
                    )
                    players.append(player)

        return players

    def parse_trade(self, trade_element: Tag, page_url: str) -> Optional[TradeData]:
        """Parse a single trade element into TradeData."""
        try:
            trade_date = self.extract_trade_date(trade_element)
            trade_summary = self.extract_trade_summary(trade_element)
            trade_url = self.extract_trade_url(trade_element) or page_url
            players = self.extract_players(trade_element)

            if self.debug:
                print(f"    Date: {trade_date}")
                print(f"    Summary: {trade_summary[:100]}...")
                print(f"    URL: {trade_url}")
                print(f"    Players found: {len(players)}")
                for p in players:
                    print(f"      - {p.name}: ${p.cap_hit:,.0f}" if p.cap_hit else f"      - {p.name}")

            if players:
                # Find player with highest cap hit
                highest = max(players, key=lambda p: p.cap_hit or 0)
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
            else:
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

    def check_pagination(self, soup: BeautifulSoup, current_page: int) -> bool:
        """Check if there's another page of results."""
        # Look for next page link
        next_patterns = [
            f'a[href*="page={current_page + 1}"]',
            'a.next',
            'a[rel="next"]',
            '[class*="next"] a',
            '[class*="pagination"] a'
        ]

        for pattern in next_patterns:
            elements = soup.select(pattern)
            for el in elements:
                href = el.get('href', '')
                if f'page={current_page + 1}' in href or 'next' in href.lower():
                    return True

        # Also check for page numbers
        page_links = soup.find_all('a')
        for link in page_links:
            href = link.get('href', '')
            if f'page={current_page + 1}' in href:
                return True

        return False

    def scrape_page(self, page_num: int) -> tuple[List[TradeData], bool]:
        """Scrape a single page of trades."""
        url = f"{self.TRADES_URL}?page={page_num}"
        print(f"\n[Page {page_num}] {url}")

        soup = self.fetch_page(url)
        if not soup:
            return [], False

        # Debug: analyze structure
        if self.debug and page_num == 0:
            structure = self.discover_html_structure(soup)
            print("\n  HTML Structure Analysis:")
            print(f"    Trade containers found: {len(structure['trade_containers'])}")
            for tc in structure['trade_containers'][:3]:
                print(f"      - {tc['tag']}.{'.'.join(tc.get('classes', []))}")

        # Find and parse trades
        trade_elements = self.find_trades_on_page(soup)
        print(f"  Found {len(trade_elements)} trade elements")

        trades = []
        for i, trade_el in enumerate(trade_elements):
            print(f"  Parsing trade {i + 1}/{len(trade_elements)}...")
            trade = self.parse_trade(trade_el, url)
            if trade:
                trades.append(trade)

        has_more = self.check_pagination(soup, page_num)
        return trades, has_more

    def scrape_all(self, max_pages: Optional[int] = None) -> List[TradeData]:
        """Scrape all trades."""
        all_trades = []
        page = 0

        while True:
            if max_pages and page >= max_pages:
                print(f"\nReached max pages limit ({max_pages})")
                break

            trades, has_more = self.scrape_page(page)
            all_trades.extend(trades)

            print(f"  Collected {len(trades)} trades, total: {len(all_trades)}")

            if not has_more:
                print("\nNo more pages")
                break

            page += 1
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
    parser.add_argument('-m', '--max-pages', type=int, help='Max pages to scrape')
    parser.add_argument('-d', '--delay', type=float, default=1.5, help='Delay between pages')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    print("=" * 70)
    print("Puckpedia Trade Scraper v2")
    print("=" * 70)
    print(f"Output: {args.output} ({args.format})")
    print(f"Max pages: {args.max_pages or 'all'}")
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


if __name__ == '__main__':
    main()
