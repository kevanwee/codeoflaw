"""Scrape SG Supreme Court judgments from eLitigation and export to CSV."""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup
from ftfy import fix_text
from tqdm import tqdm


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def normalize_text(value: str) -> str:
    cleaned = fix_text(value or "")
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


class SingaporeLawScraper:
    def __init__(
        self,
        *,
        delay: float = 0.5,
        timeout: int = 20,
        retries: int = 3,
        user_agent: str | None = None,
    ) -> None:
        self.base_list_url = "https://www.elitigation.sg/gd/Home/Index"
        self.base_case_url = "https://www.elitigation.sg/gd/s/"
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _request(self, url: str) -> requests.Response | None:
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    return response

                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return response

                if attempt < self.retries:
                    time.sleep(min(0.5 * attempt, 2.0))
            except requests.RequestException:
                if attempt < self.retries:
                    time.sleep(min(0.5 * attempt, 2.0))
                else:
                    return None
        return None

    @staticmethod
    def build_case_url(case_identifier: str) -> str:
        slug = case_identifier
        slug = slug.replace("[", "").replace("]", "")
        slug = slug.replace("(", "").replace(")", "")
        slug = re.sub(r"\s+", "_", slug)
        return f"https://www.elitigation.sg/gd/s/{slug}"

    def scrape_elitigation_cases(
        self,
        start_year: int,
        end_year: int,
        output_path: Path,
        *,
        max_pages: int | None = None,
        max_cases: int | None = None,
    ) -> Path:
        all_cases: list[dict[str, Any]] = []
        stop_scraping = False

        with tqdm(desc="Scraping cases", unit="case") as progress:
            for year in range(start_year, end_year + 1):
                if stop_scraping:
                    break

                page_num = 1
                while True:
                    if max_pages is not None and page_num > max_pages:
                        break

                    list_url = (
                        f"{self.base_list_url}?Filter=SUPCT&YearOfDecision={year}"
                        f"&SortBy=Score&CurrentPage={page_num}"
                    )
                    response = self._request(list_url)
                    if response is None or response.status_code != 200:
                        break

                    soup = BeautifulSoup(response.text, "html.parser")
                    cards = soup.find_all("div", class_="card col-12")
                    if not cards:
                        break

                    for card in cards:
                        if max_cases is not None and len(all_cases) >= max_cases:
                            stop_scraping = True
                            break

                        case_identifier_span = card.find("span", class_="gd-addinfo-text")
                        if case_identifier_span is None:
                            continue

                        case_identifier = normalize_text(
                            case_identifier_span.get_text(" ", strip=True).replace(" |", "")
                        )
                        catchwords_links = card.find_all("a", class_="gd-cw")
                        catchwords_texts = []
                        for link in catchwords_links:
                            catchword = normalize_text(
                                link.get_text(" ", strip=True).replace("[", "").replace("]", "")
                            )
                            if catchword:
                                catchwords_texts.append(catchword)

                        case_url = self.build_case_url(case_identifier)
                        case_details = self.scrape_case_details(case_url)
                        if case_details is None:
                            continue

                        all_cases.append(
                            {
                                "CaseIdentifier": case_identifier,
                                "Catchwords": "\n".join(catchwords_texts) if catchwords_texts else None,
                                "Year": year,
                                "URL": case_url,
                                **case_details,
                            }
                        )
                        progress.update(1)
                        progress.set_postfix_str(
                            f"Year: {year}, Page: {page_num}", refresh=False
                        )

                    if stop_scraping:
                        break

                    page_num += 1
                    time.sleep(self.delay)

        df = pd.DataFrame(all_cases)
        if not df.empty:
            df = df.drop_duplicates(subset=["CaseIdentifier", "URL"])
            df = df.sort_values(["Year", "CaseIdentifier"]).reset_index(drop=True)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)

        print(f"\nSaved {len(df):,} cases to {output_path}")
        if not df.empty:
            year_summary = df["Year"].value_counts().sort_index()
            print("Cases scraped by year:")
            for year, count in year_summary.items():
                print(f"- {year}: {count}")

        return output_path

    def scrape_case_details(self, url: str) -> dict[str, Any] | None:
        response = self._request(url)
        if response is None or response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        judgment_divs = soup.find_all("div", class_="Judg-1")

        paragraph_count = self._extract_paragraph_count(judgment_divs)
        full_text = " ".join(normalize_text(div.get_text(" ", strip=True)) for div in judgment_divs)
        word_count = len(re.findall(r"\b\w+\b", full_text))

        judge_div = soup.find("div", class_="Judg-Author") or soup.find("div", class_="Judg-Sign")
        judge_raw = normalize_text(judge_div.get_text(" ", strip=True)) if judge_div else "Unknown"
        judge_cleaned = self._clean_judge_name(judge_raw)

        legal_parties_cleaned = self._extract_legal_parties(soup)

        return {
            "WordCount": word_count,
            "ParagraphCount": paragraph_count,
            "Author": judge_cleaned,
            "LegalParties": legal_parties_cleaned,
        }

    @staticmethod
    def _extract_paragraph_count(judgment_divs: list[Any]) -> int:
        paragraph_count = 0
        for div in judgment_divs:
            text = normalize_text(div.get_text(" ", strip=True))
            match = re.match(r"^(\d+)\b", text)
            if match:
                paragraph_count = max(paragraph_count, int(match.group(1)))
        return paragraph_count

    @staticmethod
    def _clean_judge_name(judge_raw: str) -> str:
        judge = judge_raw.replace(":", "").strip()
        lowered = judge.lower()
        for marker in ["(delivering", "(with whom", "(for the court"]:
            marker_index = lowered.find(marker)
            if marker_index != -1:
                judge = judge[:marker_index].strip()
                lowered = judge.lower()
        return judge or "Unknown"

    @staticmethod
    def _extract_legal_parties(soup: BeautifulSoup) -> str:
        lawyers_divs = soup.find_all("div", class_="Judg-Lawyers")
        legal_parts: list[str] = []

        for div in lawyers_divs:
            text = normalize_text(div.get_text(" ", strip=True))
            if text:
                legal_parts.append(text)

        if lawyers_divs:
            current_element = lawyers_divs[-1].find_next_sibling()
            while current_element is not None:
                classes = current_element.get("class", [])
                if "Judg-EOF" in classes:
                    break
                if "txt-body" in classes:
                    text = normalize_text(current_element.get_text(" ", strip=True))
                    if text:
                        legal_parts.append(text)
                current_element = current_element.find_next_sibling()

        if not legal_parts:
            return "Not found"

        return " ".join(legal_parts).replace(";", "").strip()


def parse_args() -> argparse.Namespace:
    current_year = datetime.now().year
    parser = argparse.ArgumentParser(
        description="Scrape reported SG Supreme Court judgments from eLitigation."
    )
    parser.add_argument("--start-year", type=int, default=2020, help="First year to scrape.")
    parser.add_argument("--end-year", type=int, default=current_year, help="Last year to scrape.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. If omitted, writes to sample/elitigation_cases_<start>_to_<end>.csv",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Delay in seconds between list page requests.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Number of retries per request.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional cap on pages scraped per year (useful for quick validation).",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Optional cap on total cases scraped (useful for quick validation).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year < 1900 or args.end_year < 1900:
        raise ValueError("Years must be >= 1900")
    if args.start_year > args.end_year:
        raise ValueError("--start-year cannot be greater than --end-year")
    if args.delay < 0:
        raise ValueError("--delay cannot be negative")
    if args.timeout <= 0:
        raise ValueError("--timeout must be a positive integer")
    if args.retries < 1:
        raise ValueError("--retries must be at least 1")
    if args.max_pages is not None and args.max_pages < 1:
        raise ValueError("--max-pages must be at least 1 when provided")
    if args.max_cases is not None and args.max_cases < 1:
        raise ValueError("--max-cases must be at least 1 when provided")

    output_path = args.output
    if output_path is None:
        output_path = Path("sample") / f"elitigation_cases_{args.start_year}_to_{args.end_year}.csv"

    scraper = SingaporeLawScraper(delay=args.delay, timeout=args.timeout, retries=args.retries)
    scraper.scrape_elitigation_cases(
        start_year=args.start_year,
        end_year=args.end_year,
        output_path=output_path,
        max_pages=args.max_pages,
        max_cases=args.max_cases,
    )


if __name__ == "__main__":
    main()
