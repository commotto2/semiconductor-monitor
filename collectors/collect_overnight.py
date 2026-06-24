"""
반도체 오버나잇 시그널 수집기 (1단계: 확정 지표 6개)

수집 대상:
  - SOX  (필라델피아 반도체 지수, ^SOX)
  - MU   (마이크론)
  - NVDA (엔비디아)
  - AMD  (AMD)
  - SOXX (반도체 ETF)
  - SMH  (반도체 ETF)

데이터 소스: yfinance
출력: data/overnight_history.json 에 최근 N일치 종가를 누적 저장
      (market-monitor의 credit_history.json과 동일한 "누적 JSON" 패턴)

주의:
  - data['Close']가 단일 티커도 DataFrame으로 반환되는 yfinance 이슈가 있어
    market-monitor의 _get_close() 헬퍼를 그대로 재사용한다.
    새 지표를 추가할 때도 반드시 이 헬퍼를 통해 종가를 받아올 것.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

# ----------------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------------

TICKERS = {
    "SOX": "^SOX",
    "MU": "MU",
    "NVDA": "NVDA",
    "AMD": "AMD",
    "SOXX": "SOXX",
    "SMH": "SMH",
}

# 화면에 함께 보여줄 추이 기간 (전일 대비 동률률 외에, 최근 N일 추이 출력용)
TREND_DAYS = 5

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_PATH = os.path.join(DATA_DIR, "overnight_history.json")

KST = timezone(timedelta(hours=9))


# ----------------------------------------------------------------------------
# market-monitor collect_*.py 와 동일한 패턴의 헬퍼
# ----------------------------------------------------------------------------

def _get_close(ticker, period="1mo", timeout=20):
    """
    yfinance에서 단일 티커의 종가(Close)를 Series로 안전하게 받아오는 헬퍼.

    최신 yfinance 버전에서는 단일 티커를 요청해도 data['Close']가
    DataFrame으로 반환되는 경우가 있어 .squeeze()로 Series 변환이 필요하다.
    (market-monitor 프로젝트의 동일 헬퍼와 같은 로직 — 새 지표 추가 시 반드시 사용할 것)

    timeout: yfinance 호출이 응답 없이 무한 대기하는 것을 막기 위한 명시적 타임아웃(초).
             GitHub Actions에서 네트워크 응답이 느릴 때 워크플로우 전체가
             멈춰있는 현상이 있어 추가함 (yf.download 자체에는 기본 타임아웃이 없음).
    """
    print(f"[INFO] {ticker} 데이터 요청 중... (period={period}, timeout={timeout}s)")
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True, timeout=timeout)
    except Exception as e:
        print(f"[ERROR] {ticker} yfinance 호출 실패: {e}")
        return pd.Series(dtype=float)

    if data.empty:
        print(f"[WARN] {ticker} 응답이 비어있음 (data.empty=True)")
        return pd.Series(dtype=float)

    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.squeeze()

    result = close.dropna()
    print(f"[INFO] {ticker} 수신 완료: {len(result)}개 데이터포인트")
    return result


def collect_overnight_signals():
    """
    6개 확정 지표의 종가를 수집하고, 전일 대비 변동률 + 최근 N일 추이를 계산한다.

    Returns:
        dict: {
            "as_of": "YYYY-MM-DD",   # 가장 최근 거래일 (조회 기준)
            "collected_at_kst": "YYYY-MM-DD HH:MM:SS",
            "signals": {
                "SOX": {
                    "close": float,
                    "prev_close": float,
                    "change_pct": float,
                    "trend": [{"date": "YYYY-MM-DD", "close": float}, ...]  # 최근 N일
                },
                ...
            }
        }
    """
    signals = {}
    as_of_dates = []

    # 추이까지 안전하게 확보하려면 TREND_DAYS보다 여유 있게 받아둔다
    # (주말/공휴일 등으로 거래일이 빠지는 경우를 대비)
    fetch_period = "1mo"

    for name, ticker in TICKERS.items():
        close_series = _get_close(ticker, period=fetch_period)

        if close_series.empty:
            print(f"[WARN] {name} ({ticker}): 데이터 없음, N/A로 처리")
            signals[name] = {
                "close": None,
                "prev_close": None,
                "change_pct": None,
                "trend": [],
                "status": "N/A",
            }
            continue

        if len(close_series) < 2:
            print(f"[WARN] {name} ({ticker}): 비교할 전일 데이터 부족")
            signals[name] = {
                "close": float(close_series.iloc[-1]),
                "prev_close": None,
                "change_pct": None,
                "trend": [],
                "status": "INSUFFICIENT_HISTORY",
            }
            continue

        latest_close = float(close_series.iloc[-1])
        prev_close = float(close_series.iloc[-2])
        change_pct = round((latest_close - prev_close) / prev_close * 100, 2)

        # 최근 TREND_DAYS 영업일 추이 (가장 최근일 포함)
        trend_slice = close_series.tail(TREND_DAYS)
        trend = [
            {"date": idx.strftime("%Y-%m-%d"), "close": round(float(val), 2)}
            for idx, val in trend_slice.items()
        ]

        signals[name] = {
            "close": round(latest_close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "trend": trend,
            "status": "OK",
        }

        as_of_dates.append(close_series.index[-1])

    as_of = max(as_of_dates).strftime("%Y-%m-%d") if as_of_dates else None

    result = {
        "as_of": as_of,
        "collected_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "signals": signals,
    }

    return result


# ----------------------------------------------------------------------------
# data/overnight_history.json 누적 저장
#   (market-monitor의 credit_history.json과 동일한 패턴:
#    날짜를 key로 하여 계속 누적하고, 너무 오래된 항목은 정리)
# ----------------------------------------------------------------------------

HISTORY_RETENTION_DAYS = 30  # 누적 JSON에 보관할 최대 일수


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] 기존 history 파일을 읽지 못했습니다 ({e}). 새로 시작합니다.")
        return {}


def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def prune_old_entries(history, retention_days=HISTORY_RETENTION_DAYS):
    if not history:
        return history
    cutoff = datetime.now(KST).date() - timedelta(days=retention_days)
    pruned = {}
    for date_str, payload in history.items():
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= cutoff:
            pruned[date_str] = payload
    return pruned


def update_history(result):
    """
    오늘 수집 결과를 data/overnight_history.json에 누적 저장한다.
    as_of 날짜를 key로 사용하므로, 같은 날 재실행하면 덮어쓴다.
    """
    if not result["as_of"]:
        print("[WARN] as_of 날짜를 확정할 수 없어 history 저장을 건너뜁니다.")
        return

    history = load_history()
    history[result["as_of"]] = {
        "collected_at_kst": result["collected_at_kst"],
        "signals": {
            name: {
                "close": v["close"],
                "change_pct": v["change_pct"],
                "status": v["status"],
            }
            for name, v in result["signals"].items()
        },
    }
    history = prune_old_entries(history)
    save_history(history)
    print(f"[INFO] history 저장 완료: {HISTORY_PATH} (총 {len(history)}일치 보관)")


# ----------------------------------------------------------------------------
# 콘솔 확인용 출력 (실제 텔레그램 리포트 포맷은 reports/ 단계에서 별도 처리)
# ----------------------------------------------------------------------------

def print_summary(result):
    print(f"\n=== 반도체 오버나잇 시그널 ({result['as_of']} 기준) ===")
    for name, v in result["signals"].items():
        if v["status"] != "OK":
            print(f"  {name}: N/A ({v['status']})")
            continue
        sign = "+" if v["change_pct"] >= 0 else ""
        trend_str = " -> ".join(f"{t['close']}" for t in v["trend"])
        print(f"  {name}: {v['close']} ({sign}{v['change_pct']}%)  [최근 {TREND_DAYS}일: {trend_str}]")


if __name__ == "__main__":
    result = collect_overnight_signals()
    print_summary(result)
    update_history(result)
