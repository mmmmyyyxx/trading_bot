"""Fetch one symbol quickly and write it as Parquet for subprocess backfills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--prefer-eastmoney", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.provider.lower() != "akshare":
        raise SystemExit("fetch_one_symbol.py currently supports provider=akshare only.")

    frame = _fetch_akshare_symbol(
        args.symbol,
        args.start_date,
        args.end_date,
        args.adjust,
        prefer_eastmoney=args.prefer_eastmoney,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_path, index=False, engine="pyarrow")
    print(json.dumps({"symbol": args.symbol, "rows": int(len(frame)), "output": str(output_path)}, ensure_ascii=False))


def _fetch_akshare_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    prefer_eastmoney: bool,
) -> pd.DataFrame:
    import akshare as ak  # type: ignore

    start = pd.Timestamp(start_date).strftime("%Y%m%d")
    end = pd.Timestamp(end_date).strftime("%Y%m%d")
    adjust_arg = "" if adjust in {"none", "raw", ""} else adjust
    fetchers = (_fetch_eastmoney, _fetch_daily) if prefer_eastmoney else (_fetch_daily, _fetch_eastmoney)
    errors: list[str] = []
    for fetcher in fetchers:
        try:
            raw = fetcher(ak, symbol, start, end, adjust_arg)
            return _standardize_frame(raw, symbol)
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def _fetch_daily(ak, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
    return ak.stock_zh_a_daily(
        symbol=_to_ak_daily_symbol(symbol),
        start_date=start,
        end_date=end,
        adjust=adjust_arg,
    )


def _fetch_eastmoney(ak, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
    raw = ak.stock_zh_a_hist(
        symbol=symbol.split(".")[0],
        period="daily",
        start_date=start,
        end_date=end,
        adjust=adjust_arg,
    )
    return raw.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
    )


def _standardize_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = ["date", "open", "high", "low", "close", "volume", "amount"]
    missing = [col for col in required if col not in raw.columns]
    if raw.empty or missing:
        raise RuntimeError(f"empty or missing columns: {missing}")
    frame = raw[required].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = symbol
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close"])
    frame["adj_factor"] = 1.0
    frame["is_paused"] = (frame["volume"].fillna(0) <= 0) | (frame["amount"].fillna(0) <= 0)
    frame["is_st"] = False
    prev_close = frame["close"].shift(1).fillna(frame["close"])
    limit_rate = _limit_rate(symbol, is_st=False)
    frame["limit_up"] = prev_close * (1.0 + limit_rate)
    frame["limit_down"] = prev_close * (1.0 - limit_rate)
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def _to_ak_daily_symbol(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    market = market.upper()
    if market == "BJ":
        return f"bj{code}"
    prefix = "sz" if market == "SZ" else "sh"
    return f"{prefix}{code}"


def _limit_rate(symbol: str, is_st: bool) -> float:
    code = symbol.split(".")[0]
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("8", "4", "920")):
        return 0.30
    return 0.10


if __name__ == "__main__":
    main()
