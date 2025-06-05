#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include="object").columns:
        s = df[col]
        first = s.dropna().iloc[0] if not s.dropna().empty else None
        if isinstance(first, dict):
            expanded = s.apply(lambda x: x or {}).apply(pd.Series)
            expanded.columns = [f"{col}.{c}" for c in expanded.columns]
            df = df.drop(columns=[col]).join(expanded)
    return df

def convert_parquet_to_csv(src: Path) -> Path:
    if not src.exists():
        raise FileNotFoundError(f"{src} does not exist.")
    if src.suffix.lower() != ".parquet":
        raise ValueError(f"{src} does not have a .parquet extension.")

    df = pd.read_parquet(src)
    df = _flatten(df)
    df = df.dropna(axis=1, how='all')

    # Drop consecutive rows with the same timestamp, keeping only the first occurrence
    if 'timestamp' in df.columns:
        df = df.loc[df['timestamp'].shift() != df['timestamp']]

    dest = src.with_suffix(".csv")
    df.to_csv(dest, index=False)
    return dest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert a parquet file to CSV in the same directory."
    )
    parser.add_argument(
        "parquet_file",
        type=Path,
        help="Path to the .parquet file to convert",
    )

    args = parser.parse_args(argv)
    try:
        csv_path = convert_parquet_to_csv(args.parquet_file)
        print(f"CSV written to: {csv_path}")
    except Exception as exc:
        parser.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()