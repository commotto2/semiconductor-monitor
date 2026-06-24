"""
반도체 오버나잇 리포트 - 텔레그램 메시지 포맷 및 발송

collectors/260624_collect_overnight.py 의 collect_overnight_signals() 결과를
받아 텔레그램 메시지로 포맷하고 발송한다.

포맷 원칙:
  - 이모지 없이 텍스트로만 (+1.23% / -2.45% 형태)
  - 변동폭 |3%| 이상이면 "[주의]" 라벨만 덧붙임 (market_monitor_context.md 의
    "정상/경고/위험 기준값" 사상과 동일하되, 여기서는 단일 고정 임계값만 사용)
  - 해석/분석 문장은 넣지 않음 — 숫자와 추이만 전달 (해석은 사용자가 직접)

지표 표시 순서는 TICKERS 딕셔너리 순서를 그대로 따른다
(SOX -> MU -> NVDA -> AMD -> SOXX -> SMH).
"""

import importlib.util
import os
import sys

import requests

# collectors/260624_collect_overnight.py 를 직접 로드한다.
# 파일명이 숫자로 시작해 `import 260624_collect_overnight` 문법 자체가 불가능하므로
# importlib.util.spec_from_file_location으로 경로 기반 로드를 사용한다.
_COLLECTOR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "collectors",
    "collect_overnight.py",
)
_spec = importlib.util.spec_from_file_location("overnight_collector", _COLLECTOR_PATH)
_collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_collector)

collect_overnight_signals = _collector.collect_overnight_signals
update_history = _collector.update_history

ALERT_THRESHOLD_PCT = 3.0  # 변동폭 |3%| 이상이면 [주의] 표시

TELEGRAM_API_BASE = "https://api.telegram.org"


def format_message(result):
    """
    collect_overnight_signals() 결과를 텔레그램 메시지 텍스트로 변환한다.
    """
    lines = []
    lines.append(f"[반도체 오버나잇 시그널] {result['as_of']} 기준")
    lines.append(f"(수집: {result['collected_at_kst']} KST)")
    lines.append("")

    for name, v in result["signals"].items():
        if v["status"] != "OK":
            lines.append(f"{name}: N/A ({v['status']})")
            continue

        change = v["change_pct"]
        sign = "+" if change >= 0 else ""
        line = f"{name}: {v['close']}  ({sign}{change}%)"

        if abs(change) >= ALERT_THRESHOLD_PCT:
            line += "  [주의]"

        lines.append(line)

        # 최근 N일 추이 (담백하게 종가만 나열)
        if v["trend"]:
            trend_str = " / ".join(f"{t['close']}" for t in v["trend"])
            lines.append(f"  최근 추이: {trend_str}")

    lines.append("")
    lines.append(f"(주의 기준: 전일 대비 변동폭 |{ALERT_THRESHOLD_PCT}%| 이상)")

    return "\n".join(lines)


def send_telegram_message(token, chat_id, text):
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    resp = requests.post(url, data=payload, timeout=15)

    if resp.status_code != 200:
        print(f"[ERROR] 텔레그램 발송 실패: {resp.status_code} {resp.text}")
        resp.raise_for_status()

    print("[INFO] 텔레그램 발송 완료")
    return resp.json()


def main():
    token = os.environ.get("TELEGRAM_TOKEN_SEMI")
    chat_id = os.environ.get("TELEGRAM_CHAT_SEMI")

    if not token or not chat_id:
        print("[ERROR] TELEGRAM_TOKEN_SEMI 또는 TELEGRAM_CHAT_SEMI 환경변수가 없습니다.")
        sys.exit(1)

    result = collect_overnight_signals()
    message = format_message(result)

    print("=== 발송할 메시지 ===")
    print(message)
    print("=====================")

    send_telegram_message(token, chat_id, message)

    # 발송 성공 후 history 갱신 (워크플로우에서 이어서 git commit/push)
    update_history(result)


if __name__ == "__main__":
    main()
