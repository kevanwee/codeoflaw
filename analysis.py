"""Run basic analytics and chart generation for scraped eLitigation cases."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import matplotlib
import pandas as pd

# Use a non-interactive backend so charts can be generated in headless environments.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


REQUIRED_COLUMNS = {
    "CaseIdentifier",
    "Catchwords",
    "Year",
    "URL",
    "WordCount",
    "ParagraphCount",
    "Author",
    "LegalParties",
}
DASH_SPLIT_PATTERN = re.compile(r"\s*(?:\u2014|\u00e2\u20ac\u201d|-)\s*")


def resolve_default_input() -> Path:
    candidates = [
        Path("elitigation_cases_2020_to_2025.csv"),
        Path("sample/elitigation_cases_2020_to_2025.csv"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def load_dataset(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path)
    missing_columns = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing_columns:
        raise ValueError(
            "Input CSV is missing required columns: " + ", ".join(missing_columns)
        )

    df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
    df["WordCount"] = pd.to_numeric(df["WordCount"], errors="coerce")
    df["ParagraphCount"] = pd.to_numeric(df["ParagraphCount"], errors="coerce")
    df["Author"] = df["Author"].fillna("Unknown")
    df["Catchwords"] = df["Catchwords"].fillna("")
    return df


def extract_authors(author_series: pd.Series) -> Counter:
    counter: Counter[str] = Counter()
    for author_text in author_series.dropna().astype(str):
        chunks = re.split(r",|\band\b", author_text)
        for chunk in chunks:
            cleaned = chunk.strip()
            if cleaned and cleaned.lower() != "unknown":
                counter[cleaned] += 1
    return counter


def extract_catchword_terms(catchwords: Iterable[str]) -> Counter:
    counter: Counter[str] = Counter()
    for raw_text in catchwords:
        if not isinstance(raw_text, str) or not raw_text.strip():
            continue
        lines = [line.strip() for line in raw_text.replace("\r", "\n").split("\n")]
        for line in lines:
            if not line:
                continue
            parts = [part.strip() for part in DASH_SPLIT_PATTERN.split(line) if part.strip()]
            if parts:
                counter[parts[0]] += 1
    return counter


def save_year_breakdown_plot(df: pd.DataFrame, output_dir: Path) -> Path:
    yearly_counts = df.dropna(subset=["Year"])["Year"].astype(int).value_counts().sort_index()
    output_path = output_dir / "yearbreakdown.png"

    fig, ax = plt.subplots(figsize=(10, 5))
    yearly_counts.plot(kind="bar", color="skyblue", ax=ax)
    ax.set_title("Case Volume by Year")
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of Cases")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def save_judge_count_plot(df: pd.DataFrame, output_dir: Path, top_n: int) -> Path:
    output_path = output_dir / "judgecount.png"
    author_counts = extract_authors(df["Author"])
    top_authors = author_counts.most_common(top_n)

    fig, ax = plt.subplots(figsize=(12, 6))
    if top_authors:
        names = [name for name, _ in top_authors][::-1]
        counts = [count for _, count in top_authors][::-1]
        ax.barh(names, counts, color="lightgreen")
    else:
        ax.text(0.5, 0.5, "No author data available", ha="center", va="center")
    ax.set_title(f"Top {top_n} Most Active Authors")
    ax.set_xlabel("Number of Cases")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def save_catchword_plot(df: pd.DataFrame, output_dir: Path, top_n: int) -> Path:
    output_path = output_dir / "catchword.png"
    term_counts = extract_catchword_terms(df["Catchwords"]).most_common(top_n)

    fig, ax = plt.subplots(figsize=(12, 8))
    if term_counts:
        terms = [term for term, _ in term_counts][::-1]
        counts = [count for _, count in term_counts][::-1]
        ax.barh(terms, counts, color="salmon")
    else:
        ax.text(0.5, 0.5, "No catchword data available", ha="center", va="center")
    ax.set_title(f"Top {top_n} Legal Terms in Catchwords")
    ax.set_xlabel("Frequency")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def print_summary(df: pd.DataFrame) -> None:
    years = sorted(df["Year"].dropna().astype(int).unique().tolist())
    print(f"Total cases: {len(df):,}")
    print(f"Years covered: {years}")
    print("\nMissing values:")
    print(df.isnull().sum())
    print("\nDocument complexity:")
    print(f"- Average word count: {df['WordCount'].mean():.0f}")
    print(f"- Median word count: {df['WordCount'].median():.0f}")
    print(f"- Longest document: {df['WordCount'].max():,.0f} words")
    print(f"- Average paragraphs: {df['ParagraphCount'].mean():.0f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze scraped eLitigation case data and generate charts."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=resolve_default_input(),
        help="Path to the input CSV file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tables"),
        help="Directory for generated charts.",
    )
    parser.add_argument(
        "--top-authors",
        type=int,
        default=10,
        help="How many authors to include in judge activity chart.",
    )
    parser.add_argument(
        "--top-terms",
        type=int,
        default=15,
        help="How many catchword terms to include in catchword chart.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_authors < 1 or args.top_terms < 1:
        raise ValueError("--top-authors and --top-terms must be positive integers")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(args.input)
    print_summary(df)

    year_plot = save_year_breakdown_plot(df, output_dir)
    judge_plot = save_judge_count_plot(df, output_dir, args.top_authors)
    catchword_plot = save_catchword_plot(df, output_dir, args.top_terms)

    print("\nGenerated charts:")
    print(f"- {year_plot}")
    print(f"- {judge_plot}")
    print(f"- {catchword_plot}")


if __name__ == "__main__":
    main()
