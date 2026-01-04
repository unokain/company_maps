#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
make_tokyo_company_maps.py (v2 - Fixed)

Google My Maps にインポートできるCSVを生成

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
    "https://companiesmarketcap.com/usd/japan/largest-companies-in-japan-by-market-cap/?download=csv",
]

BUILTIN_URLS = [
    "https://builtin.com/articles/us-companies-in-tokyo",
    "https://builtin.com/articles/tech-companies-in-tokyo",
]
JP_SW_COMPANIES_MD = "https://raw.githubusercontent.com/btamada/jp-software-companies/master/README.md"

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
                address_query=f"{name_raw} 本社 東京",
                source="CompaniesMarketCap(download=csv)",
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
# 外資系企業 - 確実なリスト（実際の住所付き）
# =========================
# (会社名, 住所, URL) - 住所はGoogle Mapsで正確にジオコーディングできる形式
KNOWN_FOREIGN_COMPANIES = [
    # === Big Tech ===
    ("Google", "東京都渋谷区渋谷3丁目21-3 渋谷ストリーム", "https://www.google.com/about/careers/locations/tokyo/"),
    ("Microsoft", "東京都港区港南2-16-3 品川グランドセントラルタワー", "https://microsoft.com/ja-jp/"),
    ("Amazon Japan", "東京都目黒区下目黒1-8-1 アルコタワー", "https://www.amazon.jobs/en/locations/tokyo-area-japan"),
    ("Apple", "東京都港区六本木6-10-1 六本木ヒルズ", "https://www.apple.com/jp/"),
    ("Meta", "東京都港区虎ノ門1-23-1 虎ノ門ヒルズ森タワー", "https://www.meta.com/"),
    ("IBM", "東京都中央区日本橋箱崎町19-21", "https://www.ibm.com/jp-ja"),
    ("Oracle", "東京都港区北青山2-5-8 オラクル青山センター", "https://www.oracle.com/jp/"),
    ("SAP", "東京都千代田区大手町1-2-1 三井物産ビル", "https://www.sap.com/japan/"),
    ("Salesforce", "東京都千代田区丸の内1-1-3 日本生命丸の内ガーデンタワー", "https://www.salesforce.com/jp/"),
    ("Adobe", "東京都品川区大崎1-11-2 ゲートシティ大崎イーストタワー", "https://www.adobe.com/jp/"),
    ("Cisco", "東京都港区赤坂9-7-1 ミッドタウン・タワー", "https://www.cisco.com/c/ja_jp/"),
    ("Intel", "東京都千代田区丸の内3-1-1 国際ビル", "https://www.intel.co.jp/"),
    ("Nvidia", "東京都港区赤坂9-7-1 ミッドタウン・タワー", "https://www.nvidia.com/ja-jp/"),
    ("Dell Technologies", "東京都千代田区大手町1-2-1 Otemachi Oneタワー", "https://www.dell.com/ja-jp"),
    ("VMware", "東京都港区芝浦3-1-1 田町ステーションタワーN", "https://www.vmware.com/jp.html"),
    ("Qualcomm", "東京都港区北青山2-14-4 アーガイル青山", "https://www.qualcomm.com/"),
    
    # === Finance ===
    ("Goldman Sachs", "東京都港区六本木6-10-1 六本木ヒルズ森タワー", "http://www.goldmansachs.com/japan/"),
    ("Morgan Stanley", "東京都千代田区大手町1-9-7 大手町フィナンシャルシティサウスタワー", "http://www.morganstanley.co.jp/"),
    ("JP Morgan", "東京都千代田区丸の内2-7-3 東京ビルディング", "https://www.jpmorgan.com/JP/"),
    ("Barclays", "東京都港区六本木6-10-1 六本木ヒルズ森タワー", "http://joinus.barclays.com/japan/"),
    ("Citibank", "東京都千代田区大手町1-1-1 大手町パークビル", "https://www.citigroup.jp/"),
    ("UBS", "東京都千代田区大手町1-5-1 大手町ファーストスクエア", "https://www.ubs.com/jp/"),
    ("Credit Suisse", "東京都港区六本木1-6-1 泉ガーデンタワー", "https://www.credit-suisse.com/jp/"),
    ("Deutsche Bank", "東京都千代田区永田町2-11-1 山王パークタワー", "https://www.db.com/japan/"),
    ("HSBC", "東京都中央区日本橋3-11-1", "https://www.hsbc.co.jp/"),
    ("BlackRock", "東京都千代田区丸の内1-8-3 丸の内トラストタワー", "https://www.blackrock.com/jp/"),
    ("Bloomberg", "東京都千代田区丸の内2-4-1 丸の内ビルディング", "https://www.bloomberg.co.jp/"),
    
    # === Consulting ===
    ("Accenture", "東京都港区赤坂1-8-1 赤坂インターシティAIR", "https://www.accenture.com/jp-ja"),
    ("Deloitte", "東京都千代田区丸の内3-2-3 丸の内二重橋ビルディング", "https://www2.deloitte.com/jp/"),
    ("PwC", "東京都千代田区大手町1-1-1 大手町パークビルディング", "https://www.pwc.com/jp/"),
    ("McKinsey", "東京都港区六本木1-6-1 泉ガーデンタワー", "https://www.mckinsey.com/jp/"),
    ("Boston Consulting Group", "東京都千代田区丸の内1-6-1 丸の内センタービル", "https://www.bcg.com/ja-jp/"),
    ("Bain & Company", "東京都港区赤坂9-7-1 ミッドタウン・タワー", "https://www.bain.com/ja/"),
    ("EY", "東京都千代田区有楽町1-1-2 東京ミッドタウン日比谷", "https://www.ey.com/ja_jp"),
    ("KPMG", "東京都千代田区大手町1-9-5 大手町フィナンシャルシティ ノースタワー", "https://home.kpmg/jp/"),
    
    # === Tech/SaaS ===
    ("Stripe", "東京都渋谷区神宮前6-12-18", "https://stripe.com/jp"),
    ("Indeed", "東京都渋谷区恵比寿4-20-3 恵比寿ガーデンプレイスタワー", "https://www.indeed.jobs/"),
    ("Elastic", "東京都渋谷区渋谷2-24-12 渋谷スクランブルスクエア", "https://www.elastic.co.jp/"),
    ("Slack", "東京都千代田区丸の内1-1-3 日本生命丸の内ガーデンタワー", "https://slack.com/intl/ja-jp/"),
    ("Atlassian", "東京都港区虎ノ門4-1-1 神谷町トラストタワー", "https://www.atlassian.com/ja"),
    ("Datadog", "東京都港区六本木1-4-5 アークヒルズサウスタワー", "https://www.datadoghq.com/ja/"),
    ("Snowflake", "東京都千代田区丸の内1-6-5 丸の内北口ビル", "https://www.snowflake.com/ja/"),
    ("ServiceNow", "東京都港区赤坂1-12-32 アーク森ビル", "https://www.servicenow.com/jp/"),
    ("Workday", "東京都港区虎ノ門1-23-1 虎ノ門ヒルズ森タワー", "https://www.workday.com/ja-jp/"),
    ("Splunk", "東京都千代田区大手町1-1-1 大手町パークビル", "https://www.splunk.com/ja_jp"),
    ("Twilio", "東京都渋谷区神宮前5-52-2 青山オーバルビル", "https://www.twilio.com/ja-jp"),
    
    # === Security ===
    ("CrowdStrike", "東京都港区虎ノ門1-23-1 虎ノ門ヒルズ森タワー", "https://www.crowdstrike.jp/"),
    ("Snyk", "東京都渋谷区渋谷2-24-12 渋谷スクランブルスクエア", "https://snyk.io/"),
    ("Rubrik", "東京都港区虎ノ門1-17-1 虎ノ門ヒルズビジネスタワー", "https://www.rubrik.com/ja"),
    ("Palo Alto Networks", "東京都千代田区丸の内1-8-1 丸の内トラストタワーN館", "https://www.paloaltonetworks.jp/"),
    ("Fortinet", "東京都港区六本木7-7-7 Tri-Seven Roppongi", "https://www.fortinet.com/jp"),
    
    # === From BuiltIn ===
    ("Qualtrics", "東京都千代田区丸の内1-5-1 新丸の内ビルディング", "https://www.qualtrics.com/"),
    ("Crunchyroll", "東京都渋谷区渋谷2-21-1 渋谷ヒカリエ", "https://www.crunchyroll.com/"),
    ("Braze", "東京都渋谷区神宮前6-12-18", "https://www.braze.com/"),
    ("Dynatrace", "東京都千代田区丸の内2-1-1 丸の内MY PLAZA", "https://www.dynatrace.com/"),
    ("Rokt", "東京都港区六本木1-6-1 泉ガーデンタワー", "https://www.rokt.com/"),
    ("Schrödinger", "東京都千代田区丸の内1-8-3 丸の内トラストタワー", "https://www.schrodinger.com/"),
    ("Flatiron Health", "東京都港区港南2-16-3 品川グランドセントラルタワー", "https://flatiron.com/"),
    
    # === Entertainment/Gaming ===
    ("Netflix", "東京都港区赤坂9-7-1 ミッドタウン・タワー", "https://www.netflix.com/jp/"),
    ("Spotify", "東京都渋谷区神宮前6-35-3 JUNCTION harajuku", "https://www.spotify.com/jp/"),
    ("Niantic", "東京都渋谷区神宮前6-28-6 キュープラザ原宿", "https://nianticlabs.com/"),
    ("Unity", "東京都中央区銀座6-10-1 GINZA SIX", "https://unity.com/ja"),
    
    # === Others ===
    ("Uber", "東京都渋谷区渋谷2-24-12 渋谷スクランブルスクエア", "https://www.uber.com/jp/"),
    ("PayPal", "東京都港区虎ノ門1-17-1 虎ノ門ヒルズビジネスタワー", "https://www.paypal.com/jp/"),
    ("Airbnb", "東京都新宿区西新宿6-24-1 西新宿三井ビルディング", "https://www.airbnb.jp/"),
    ("LinkedIn", "東京都千代田区丸の内2-4-1 丸の内ビルディング", "https://www.linkedin.com/"),
    ("Zoom", "東京都渋谷区神宮前5-52-2 青山オーバルビル", "https://zoom.us/ja-jp/"),
    ("Dropbox", "東京都港区六本木3-2-1 住友不動産六本木グランドタワー", "https://www.dropbox.com/ja/"),
    
    # === Pharma ===
    ("Johnson & Johnson", "東京都千代田区西神田3-5-2", "https://www.jnj.co.jp/"),
    ("Pfizer", "東京都渋谷区代々木3-22-7 新宿文化クイントビル", "https://www.pfizer.co.jp/"),
    ("Merck", "東京都千代田区九段北1-13-12 北の丸スクエア", "https://www.msd.co.jp/"),
    ("Roche", "東京都港区港南1-2-70 品川シーズンテラス", "https://www.roche.co.jp/"),
    ("Novartis", "東京都港区虎ノ門1-23-1 虎ノ門ヒルズ森タワー", "https://www.novartis.co.jp/"),
    ("AstraZeneca", "東京都港区芝5-33-1 森永プラザビル", "https://www.astrazeneca.co.jp/"),
    
    # === Others ===
    ("Houzz", "東京都港区六本木7-7-7 Tri-Seven Roppongi", "https://www.houzz.jp/"),
    ("Applied Intuition", "東京都渋谷区渋谷2-24-12 渋谷スクランブルスクエア", "https://www.appliedintuition.com/"),
    ("Slalom", "東京都千代田区大手町1-9-2 大手町フィナンシャルシティ グランキューブ", "https://www.slalom.com/"),
    ("Reaktor", "東京都渋谷区神宮前5-52-2 青山オーバルビル", "https://www.reaktor.com/"),
    ("Kraken Technologies", "東京都港区六本木1-4-5 アークヒルズサウスタワー", "https://kraken.tech/"),
]


# =========================
# GitHub README parser
# =========================
def _strip_markdown_link(s: str) -> Tuple[str, Optional[str]]:
    m = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", (s or "").strip())
    if not m:
        return (s or "").strip(), None
    return m.group(1).strip(), m.group(2).strip()


def _parse_github_md(md: str) -> List[Tuple[str, str, Optional[str]]]:
    lines = (md or "").splitlines()
    table_started = False
    rows = []
    for ln in lines:
        if ln.strip().startswith("| Company") and "Location" in ln:
            table_started = True
            continue
        if not table_started:
            continue
        if not ln.strip().startswith("|"):
            if ln.startswith("#"):
                table_started = False
            continue
        if "---" in ln:
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cols) < 2:
            continue
        company, url = _strip_markdown_link(cols[0])
        if company and cols[1]:
            rows.append((company.strip(), cols[1].strip(), url))
    return rows


# =========================
# BuiltIn parser (Fixed)
# =========================
def _parse_builtin(html: str) -> List[str]:
    """BuiltInの記事から会社名を抽出（h3タグから）"""
    soup = BeautifulSoup(html, "html.parser")
    names = []
    
    # h3タグで会社名を探す（View Profileリンクの近くにある）
    for h3 in soup.find_all("h3"):
        # h3内のaタグを探す
        link = h3.find("a")
        if link:
            name = _clean_text(link.get_text())
            if name and len(name) > 1 and len(name) < 50:
                # ノイズ除外
                if name.lower() not in {"remote", "jobs", "companies", "articles", "more"}:
                    names.append(name)
    
    # 重複除去
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# =========================
# 日本企業判定
# =========================
JP_BLACKLIST = {
    x.lower() for x in [
        "dentsu", "dena", "mercari", "nomura", "recruit", "line", "kakaku",
        "moneyforward", "pixiv", "retty", "septeni", "m3", "interspace",
        "mediweb", "rakuten", "gmo", "gree", "dmm", "dwango", "cyberagent",
        "cookpad", "gungho", "gunosy", "i-mobile", "freakout", "finc",
        "crowdworks", "bizreach", "smartnews", "wantedly", "voyagegroup",
        "fast retailing", "softbank", "sony", "toyota", "honda", "nintendo",
        "hitachi", "panasonic", "toshiba", "fujitsu", "nec", "sharp", "canon",
        "nikon", "mitsubishi", "mitsui", "sumitomo", "mizuho",
    ]
}


def is_japanese(name: str, url: Optional[str]) -> bool:
    nlow = name.lower()
    if nlow in JP_BLACKLIST:
        return True
    if re.search(r"(株式会社|有限会社|合同会社|ホールディングス|銀行|証券)", name):
        return True
    if url and ".co.jp" in url.lower():
        return True
    return False


# =========================
# Foreign Tokyo 50
# =========================
def build_foreign_tokyo50(*, debug: bool = False, exclude_names: Optional[Set[str]] = None) -> List[CompanyRow]:
    all_candidates: List[Tuple[str, str, Optional[str], str]] = []
    
    # 1. 確実なリストを最初に追加
    print("  [1] Loading known foreign companies list...")
    for name, loc, url in KNOWN_FOREIGN_COMPANIES:
        all_candidates.append((name, loc, url, "KnownList"))
    print(f"      Added {len(KNOWN_FOREIGN_COMPANIES)} companies")
    
    # 2. GitHub README
    print("  [2] Fetching GitHub jp-software-companies...")
    md = _get(JP_SW_COMPANIES_MD, debug=debug, debug_name="github_readme.md")
    github_count = 0
    if md:
        for name, loc, url in _parse_github_md(md):
            if "Tokyo" in loc:
                all_candidates.append((name, loc, url, "GitHub"))
                github_count += 1
    print(f"      Found {github_count} Tokyo companies")
    
    time.sleep(0.5)
    
    # 3. BuiltIn
    print("  [3] Fetching BuiltIn articles...")
    builtin_count = 0
    for url in BUILTIN_URLS:
        html = _get(url, debug=debug, debug_name=f"builtin_{builtin_count}.html")
        if html and not _looks_like_block_page(html):
            names = _parse_builtin(html)
            for n in names:
                all_candidates.append((n, "Tokyo", None, "BuiltIn"))
            builtin_count += len(names)
        time.sleep(0.5)
    print(f"      Found {builtin_count} companies")
    
    # フィルタリング - KnownListは住所をそのまま使用
    def addr_query(name: str, loc: str, source: str) -> str:
        if source == "KnownList":
            # KnownListは既に実際の住所が入っている
            return loc
        elif "Tokyo" in loc:
            return f"{name} 本社 {loc} 日本"
        else:
            return f"{name} 本社 東京 日本"
    
    out = []
    seen = set()
    
    for name, loc, url, source in all_candidates:
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
            address_query=addr_query(name, loc, source),
            source=source,
            url=url,
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
    print("Japan Top200 + Foreign Tokyo 50 CSV Generator (Fixed)")
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
        write_csv("foreign_tokyo50_mymaps.csv", [])

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
