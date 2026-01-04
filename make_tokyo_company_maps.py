#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
make_tokyo_company_maps.py

Google My Maps にインポートできるCSVを生成

データソース:
  - 日本Top200: CompaniesMarketCap (CSV download)
  - 外資系: S&P500/Fortune Global 500 × Japan Dev "global-offices" の交差

出力:
  - japan_top200_mymaps.csv
  - foreign_tokyo50_mymaps.csv
"""

from __future__ import annotations

import argparse
import csv
import html as html_std
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

# =========================
# Config
# =========================
OUT_DIR = Path(__file__).resolve().parent
DEBUG_DIR = OUT_DIR / "debug"

CMCAP_CSV_URLS = [
    "https://companiesmarketcap.com/japan/largest-companies-in-japan-by-market-cap/?download=csv",
]

# S&P 500 リスト取得元
SP500_URL = "https://www.slickcharts.com/sp500"

# Japan Dev - Global Offices タグ
JAPAN_DEV_URL = "https://japan-dev.com/companies/tags/global-offices"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 30


@dataclass
class CompanyRow:
    name: str
    rank: Optional[int] = None
    market_cap_usd: Optional[str] = None
    ticker: Optional[str] = None
    category: Optional[str] = None
    address_query: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


# =========================
# HTTP helpers
# =========================
def _get(url: str, *, timeout: int = TIMEOUT, retries: int = 3, debug: bool = False, debug_name: str = "") -> Optional[str]:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            r.raise_for_status()
            text = r.text
            if debug:
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", debug_name or url)[:180]
                (DEBUG_DIR / safe).write_text(text, encoding="utf-8", errors="ignore")
            return text
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(1.0 * (i + 1))
    print(f"  [WARN] GET failed: {url}: {repr(last_err)}")
    return None


def _looks_like_html(s: str) -> bool:
    t = s.lstrip().lower()
    return t.startswith("<!doctype") or t.startswith("<html") or "<html" in t[:800]


def _looks_like_block_page(s: str) -> bool:
    t = s.lower()
    return ("cloudflare" in t) or ("just a moment" in t) or ("attention required" in t)


def _normalize_csv_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = html_std.unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_text(s: str) -> str:
    s = (s or "").replace("\xa0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\s\-–—:]+$", "", s).strip()
    return s


def _format_marketcap(num_str: str) -> Optional[str]:
    if not num_str:
        return None
    s = num_str.strip().replace(",", "")
    if s.startswith("$"):
        return s
    try:
        v = float(s)
    except:
        return None
    if v >= 1e12:
        return f"${v/1e12:.2f} T"
    if v >= 1e9:
        return f"${v/1e9:.2f} B"
    if v >= 1e6:
        return f"${v/1e6:.2f} M"
    return f"${v:.0f}"


# =========================
# Japan Top200
# =========================
def _parse_cmc_csv(csv_text: str) -> List[CompanyRow]:
    csv_text = csv_text.lstrip("\ufeff")
    f = io.StringIO(csv_text)
    reader = csv.reader(f)
    first = next(reader, None)
    if not first:
        return []

    def norm(h): return re.sub(r"\s+", "", h.strip().lower())

    if any("rank" in norm(c) for c in first):
        headers = first
        dict_reader = csv.DictReader(io.StringIO(csv_text), fieldnames=headers)
        next(dict_reader, None)
        keys = {norm(h): h for h in headers}

        def pick(*cands):
            for c in cands:
                for k_norm, k_raw in keys.items():
                    if c == k_norm:
                        return k_raw
            return None

        k_rank, k_name = pick("rank"), pick("name")
        k_sym, k_mcap = pick("symbol", "ticker"), pick("marketcap", "marketcapitalization")

        rows = []
        for row in dict_reader:
            if not row:
                continue
            rank_raw = (row.get(k_rank) or "").strip() if k_rank else ""
            name_raw = (row.get(k_name) or "").strip() if k_name else ""
            sym_raw = (row.get(k_sym) or "").strip() if k_sym else ""
            mcap_raw = (row.get(k_mcap) or "").strip() if k_mcap else ""

            m = re.search(r"\d+", rank_raw)
            if not m or not name_raw:
                continue

            rows.append(CompanyRow(
                name=name_raw,
                rank=int(m.group(0)),
                ticker=sym_raw or None,
                market_cap_usd=_format_marketcap(mcap_raw),
                category="JapanTop200",
                address_query=f"{name_raw} 本社",
                source="CompaniesMarketCap",
            ))

        by_rank = {}
        for r in rows:
            if r.rank and r.rank not in by_rank:
                by_rank[r.rank] = r
        return [by_rank[k] for k in sorted(by_rank)]
    return []


def fetch_japan_top200(*, debug: bool = False) -> List[CompanyRow]:
    for url in CMCAP_CSV_URLS:
        txt = _get(url, debug=debug, debug_name="cmc_japan.csv")
        if not txt or _looks_like_html(txt) or _looks_like_block_page(txt):
            continue
        rows = _parse_cmc_csv(txt)
        if rows:
            by_rank = {r.rank: r for r in rows if r.rank and 1 <= r.rank <= 200}
            return [by_rank[i] for i in sorted(by_rank)]
    raise RuntimeError("Failed to fetch CompaniesMarketCap CSV")


# =========================
# S&P 500 リスト取得
# =========================
def fetch_sp500_companies(*, debug: bool = False) -> Set[str]:
    """
    S&P 500 企業名を取得（slickcharts.comから）
    """
    print("  [1] Fetching S&P 500 list...")
    html = _get(SP500_URL, debug=debug, debug_name="sp500.html")
    if not html:
        print("      Failed to fetch, using fallback")
        return _get_fallback_sp500()
    
    soup = BeautifulSoup(html, "html.parser")
    companies = set()
    
    # テーブルから企業名を抽出
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 2:
            # 2列目が企業名
            name_cell = cells[1]
            link = name_cell.find("a")
            if link:
                name = _clean_text(link.get_text())
                if name:
                    companies.add(name)
    
    print(f"      Found {len(companies)} S&P 500 companies")
    return companies


def _get_fallback_sp500() -> Set[str]:
    """S&P500のフォールバックリスト（主要企業のみ）"""
    return {
        # Big Tech
        "Apple", "Microsoft", "Nvidia", "Alphabet", "Amazon", "Meta Platforms",
        "Broadcom", "Tesla", "Oracle", "Salesforce", "Adobe", "Cisco",
        "Intel", "IBM", "Qualcomm", "AMD", "Netflix", "ServiceNow",
        # Finance
        "Berkshire Hathaway", "JPMorgan Chase", "Visa", "Mastercard",
        "Bank of America", "Wells Fargo", "Goldman Sachs", "Morgan Stanley",
        "American Express", "Citigroup", "BlackRock", "Charles Schwab",
        # Healthcare
        "Eli Lilly", "UnitedHealth", "Johnson & Johnson", "Merck", "AbbVie",
        "Pfizer", "Thermo Fisher Scientific", "Abbott Laboratories",
        # Consumer
        "Walmart", "Costco", "Home Depot", "McDonald's", "Nike", "Starbucks",
        "Procter & Gamble", "Coca-Cola", "PepsiCo",
        # Industrial
        "GE Aerospace", "Caterpillar", "Boeing", "Honeywell", "3M",
        "Lockheed Martin", "RTX Corporation",
        # Energy
        "ExxonMobil", "Chevron",
        # Others
        "Accenture", "Uber", "Airbnb", "PayPal", "Booking Holdings",
    }


# =========================
# Japan Dev 企業リスト取得
# =========================
def fetch_japan_dev_companies(*, debug: bool = False) -> Dict[str, str]:
    """
    Japan Dev の global-offices タグから企業名を取得
    戻り値: {企業名: Japan Dev URL}
    """
    print("  [2] Fetching Japan Dev global-offices list...")
    html = _get(JAPAN_DEV_URL, debug=debug, debug_name="japan_dev.html")
    if not html:
        print("      Failed to fetch")
        return {}
    
    soup = BeautifulSoup(html, "html.parser")
    companies = {}
    
    # 企業カードから名前を抽出
    # h2タグの中のリンクが企業名
    for h2 in soup.find_all("h2"):
        link = h2.find("a")
        if link and link.get("href", "").startswith("/companies/"):
            name = _clean_text(link.get_text())
            # "NEW!" プレフィックスを除去
            name = re.sub(r"^NEW!\s*", "", name, flags=re.I).strip()
            if name and len(name) > 1:
                url = f"https://japan-dev.com{link.get('href')}"
                companies[name] = url
    
    print(f"      Found {len(companies)} companies with Tokyo offices")
    return companies


# =========================
# 日本企業判定
# =========================
JP_BLACKLIST = {
    x.lower() for x in [
        # 明らかな日本企業
        "Rakuten", "SoftBank", "Sony", "Toyota", "Honda", "Nintendo",
        "Mercari", "LINE", "DeNA", "GREE", "CyberAgent", "Cookpad",
        "SmartNews", "Wantedly", "Sansan", "M3", "Kaizen Platform",
        "Fast Retailing", "Preferred Networks", "Cybozu", "GLOBIS",
        # GitHub READMEに含まれる日本企業
        "dentsu", "nomura", "recruit", "kakaku", "moneyforward", "pixiv",
        "retty", "septeni", "interspace", "mediweb", "gmo", "dmm", "dwango",
        "gungho", "gunosy", "i-mobile", "freakout", "finc", "crowdworks",
        "bizreach", "voyagegroup", "hitachi", "panasonic", "toshiba",
        "fujitsu", "nec", "sharp", "canon", "nikon", "mitsubishi",
        "mitsui", "sumitomo", "mizuho", "Sony Interactive Entertainment",
    ]
}


def is_japanese(name: str, url: Optional[str] = None) -> bool:
    nlow = name.lower()
    if nlow in JP_BLACKLIST:
        return True
    # 日本語が含まれる
    if re.search(r"(株式会社|有限会社|合同会社|ホールディングス|銀行|証券)", name):
        return True
    return False


# =========================
# 住所クエリ生成
# =========================
def make_address_query(name: str) -> str:
    """
    Google My Mapsのジオコーディング用の住所クエリを生成
    """
    # 会社名から余計な suffix を除去
    clean_name = re.sub(
        r'\s*(Inc\.?|Corp\.?|Ltd\.?|LLC|Co\.?,?\s*Ltd\.?|Corporation|,?\s*Inc\.?|plc)$',
        '', name, flags=re.I
    ).strip()
    return f"{clean_name} 東京オフィス"


# =========================
# Foreign Tokyo 50
# =========================
def build_foreign_tokyo50(*, debug: bool = False, exclude_names: Optional[Set[str]] = None) -> List[CompanyRow]:
    """
    外資系企業リストを構築
    
    方法: S&P 500 × Japan Dev "global-offices" の交差
    """
    # 1. S&P 500 リストを取得
    sp500_companies = fetch_sp500_companies(debug=debug)
    
    time.sleep(0.5)
    
    # 2. Japan Dev リストを取得
    japan_dev_companies = fetch_japan_dev_companies(debug=debug)
    
    # 3. 交差を計算
    print("  [3] Computing intersection...")
    
    # 名前の正規化関数
    def normalize(name: str) -> str:
        n = name.lower().strip()
        # 一般的な suffix を除去
        n = re.sub(r'\s*(inc\.?|corp\.?|ltd\.?|llc|co\.?,?\s*ltd\.?|corporation|,?\s*inc\.?|plc|\(the\))$', '', n, flags=re.I)
        n = re.sub(r'\s+', ' ', n).strip()
        return n
    
    # S&P 500 の正規化名 -> 元の名前
    sp500_normalized = {normalize(name): name for name in sp500_companies}
    
    # Japan Dev の正規化名 -> (元の名前, URL)
    japan_dev_normalized = {normalize(name): (name, url) for name, url in japan_dev_companies.items()}
    
    # 交差を見つける
    intersection = []
    matched_sp500 = set()
    
    for jd_norm, (jd_name, jd_url) in japan_dev_normalized.items():
        # 完全一致
        if jd_norm in sp500_normalized:
            intersection.append((sp500_normalized[jd_norm], jd_url, "S&P500 × JapanDev"))
            matched_sp500.add(jd_norm)
            continue
        
        # 部分一致（例: "Google" in "Alphabet Inc."）
        for sp_norm, sp_name in sp500_normalized.items():
            if sp_norm in matched_sp500:
                continue
            # 一方が他方を含む
            if jd_norm in sp_norm or sp_norm in jd_norm:
                intersection.append((sp_name, jd_url, "S&P500 × JapanDev"))
                matched_sp500.add(sp_norm)
                break
    
    print(f"      Found {len(intersection)} matching companies")
    
    # 4. フィルタリング
    out = []
    seen = set()
    
    for name, url, source in intersection:
        name = _clean_text(name)
        if not name:
            continue
        nlow = name.lower()
        if nlow in seen:
            continue
        if exclude_names and nlow in exclude_names:
            continue
        if is_japanese(name, url):
            continue
        
        seen.add(nlow)
        out.append(CompanyRow(
            name=name,
            category="ForeignTokyoOffice",
            address_query=make_address_query(name),
            source=source,
            url=url,
        ))
    
    # 50社に満たない場合、S&P500上位から追加
    if len(out) < 50:
        print(f"  [4] Adding more S&P 500 companies (current: {len(out)})...")
        # S&P 500 の上位企業を追加（東京オフィスがある可能性が高い大企業）
        priority_companies = [
            "Apple", "Microsoft", "Nvidia", "Amazon", "Meta Platforms",
            "Alphabet", "Broadcom", "Tesla", "Oracle", "Salesforce",
            "Adobe", "Cisco", "Intel", "IBM", "Qualcomm",
            "JPMorgan Chase", "Goldman Sachs", "Morgan Stanley",
            "Visa", "Mastercard", "American Express", "BlackRock",
            "Accenture", "Netflix", "Uber", "PayPal", "Airbnb",
            "Johnson & Johnson", "Pfizer", "Merck", "Eli Lilly",
            "Procter & Gamble", "Coca-Cola", "PepsiCo",
            "Caterpillar", "Boeing", "3M", "Honeywell",
            "ExxonMobil", "Chevron",
        ]
        
        for name in priority_companies:
            if len(out) >= 50:
                break
            nlow = name.lower()
            if nlow in seen:
                continue
            if exclude_names and nlow in exclude_names:
                continue
            if is_japanese(name):
                continue
            
            seen.add(nlow)
            out.append(CompanyRow(
                name=name,
                category="ForeignTokyoOffice",
                address_query=make_address_query(name),
                source="S&P500 (Top)",
                url=None,
            ))
    
    return out[:50]


# =========================
# CSV writer
# =========================
def write_csv(filename: str, rows: List[CompanyRow]) -> None:
    path = OUT_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Address", "Category", "Rank", "MarketCapUSD", "Ticker", "Source", "URL"])
        for r in rows:
            w.writerow([
                _normalize_csv_text(r.name),
                _normalize_csv_text(r.address_query),
                _normalize_csv_text(r.category),
                r.rank if r.rank is not None else "",
                _normalize_csv_text(r.market_cap_usd),
                _normalize_csv_text(r.ticker),
                _normalize_csv_text(r.source),
                _normalize_csv_text(r.url),
            ])
    print(f"Wrote: {path} ({len(rows)} rows)")


# =========================
# main
# =========================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    print("=" * 60)
    print("Japan Top200 + Foreign Tokyo 50 CSV Generator")
    print("=" * 60)

    jp_exclude = set()
    print("\n[Japan Top200]")
    try:
        jp = fetch_japan_top200(debug=args.debug)
        print(f"  Retrieved {len(jp)} companies")
        if jp:
            print(f"  Top 3: {[(r.rank, r.name) for r in jp[:3]]}")
        write_csv("japan_top200_mymaps.csv", jp)
        jp_exclude = {(r.name or "").lower() for r in jp}
    except Exception as e:
        print(f"  [ERROR] {repr(e)}")
        write_csv("japan_top200_mymaps.csv", [])

    print("\n[Foreign Tokyo 50]")
    try:
        foreign = build_foreign_tokyo50(debug=args.debug, exclude_names=jp_exclude)
        print(f"  Retrieved {len(foreign)} companies")
        if foreign:
            print(f"  Top 5: {[r.name for r in foreign[:5]]}")
        write_csv("foreign_tokyo50_mymaps.csv", foreign)
    except Exception as e:
        print(f"  [ERROR] {repr(e)}")
        import traceback
        traceback.print_exc()
        write_csv("foreign_tokyo50_mymaps.csv", [])

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
