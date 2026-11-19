"""스윙 A — 급락 눌림 (12년 검증)
조건: 종가 > 60일선, 종가 < 20일선 - 2.5×표준편차, 20일 평균 거래대금 50억+
매매: 다음날 시가 매수 → 신호일로부터 5거래일째 종가 매도, 손절 -10%
모든 신호를 '모의 기록'으로 자동 저장해서 실제 성적을 계속 확인한다.
"""
import os, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import market_data as md
import info

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
LOG = f"{REC}/swing_a.csv"

HOLD_DAYS = 5      # 신호일로부터 몇 거래일째 종가에 매도
STOP = -10.0       # 손절 %
SIGMA = 2.5
MIN_VALUE = 50     # 20일 평균 거래대금(억)
SHOW_MAX = 5       # 알림에 보여줄 최대 종목 수
COST = 0.25        # 왕복 비용 %


def _check(row):
    try:
        d = md.daily(row["code"], 70)
    except Exception:
        return None
    if len(d) < 61 or d.date.iloc[-1] != md.today():
        return None
    c = d.c
    ma20, sd20, ma60 = c.iloc[-20:].mean(), c.iloc[-20:].std(), c.iloc[-60:].mean()
    value20 = (d.c * d.v).iloc[-20:].mean() / 1e8
    last = c.iloc[-1]
    lower = ma20 - SIGMA * sd20
    if last > ma60 and last < lower and value20 >= MIN_VALUE:
        return dict(date=md.today(), code=row["code"], name=row["name"], close=last,
                    ret=row["ret"], value20=round(value20), depth=round((last / lower - 1) * 100, 2),
                    ma60_gap=round((last / ma60 - 1) * 100, 1))
    return None


def scan():
    """오늘 장 마감 기준 신호 찾기 (오늘 하락한 종목만 확인해서 시간을 줄임)"""
    L = md.all_stocks()
    L = L[L.ret < 3]   # 19:00 목록 등락률은 애프터장이 섞일 수 있어 넉넉하게 거른 뒤, 일봉(KRX 종가)으로 다시 확인
    with ThreadPoolExecutor(8) as ex:
        res = [r for r in ex.map(_check, L.to_dict("records")) if r]
    return pd.DataFrame(res).sort_values("value20", ascending=False) if res else pd.DataFrame()


def _load():
    if os.path.exists(LOG):
        return pd.read_csv(LOG, dtype={"code": str, "date": str, "sell_date": str})
    return pd.DataFrame(columns=["date", "code", "name", "close", "buy", "status", "sell_date", "sell", "ret"])


def update(log):
    """진행 중인 신호의 매수가·손절·매도 결과를 일봉으로 채움"""
    reminders = []
    for i, p in log[log.status.isin(["대기", "보유"])].iterrows():
        d = md.daily(p.code, 20)
        after = d[d.date > p.date].reset_index(drop=True)
        if after.empty:
            continue
        buy = after.o.iloc[0]
        log.at[i, "buy"], log.at[i, "status"] = buy, "보유"
        stop = buy * (1 + STOP / 100)
        done = False
        for k in range(min(len(after), HOLD_DAYS)):
            bar = after.iloc[k]
            if k > 0 and bar.o <= stop:          # 시가부터 손절가 아래
                sell, why = bar.o, "손절"
            elif bar.l <= stop:
                sell, why = stop, "손절"
            elif k == HOLD_DAYS - 1:
                sell, why = bar.c, "만기"
            else:
                continue
            log.at[i, "sell"], log.at[i, "sell_date"], log.at[i, "status"] = sell, bar.date, why
            log.at[i, "ret"] = round((sell / buy - 1) * 100 - COST, 2)
            done = True
            break
        if not done and len(after) == HOLD_DAYS - 1:
            reminders.append(f"• {p['name']} — 내일 종가 매도 (손절가 {stop:,.0f}원)")
    return log, reminders


def due_today():
    """15:10 알림용: 오늘 종가에 팔 스윙 종목"""
    log = _load()
    out = []
    for _, p in log[log.status == "보유"].iterrows():
        d = md.daily(p.code, 20)
        if (d.date > p.date).sum() == HOLD_DAYS and d.date.iloc[-1] == md.today():
            out.append(f"• {p['name']} ({p.code}) — 오늘 종가 매도 예정 (매수 {p.buy:,.0f}원, 현재 {d.c.iloc[-1] / p.buy * 100 - 100:+.1f}%)")
    return out


def stats(log):
    done = log[log.status.isin(["손절", "만기"])]
    if done.empty:
        return ""
    r = done.ret.astype(float)
    return f"📒 스윙 A 모의 기록 {len(r)}건 | 승률 {(r > 0).mean() * 100:.0f}% | 평균 {r.mean():+.2f}% (비용 {COST}% 뺌)"


def evening_section():
    os.makedirs(REC, exist_ok=True)
    log = _load()
    log, reminders = update(log)
    new = scan()
    lines = ["🔵 스윙 A (급락 눌림) — 장이 나쁠 때 주로 나오는 신호"]
    if new.empty:
        lines.append("오늘 신호 없음")
    else:
        held = set(log[log.status.isin(["대기", "보유"])].code)
        new = new[~new.code.isin(held)]
        for j, r in enumerate(new.head(SHOW_MAX).itertuples(), 1):
            lines.append(f"{j}. {r.name} ({r.code}) 종가 {r.close:,.0f}원 ({r.ret:+.1f}%)\n"
                         f"   밴드 하단보다 {r.depth:+.1f}% | 60일선 대비 {r.ma60_gap:+.1f}% | 20일 평균 거래대금 {r.value20:,}억\n"
                         + info.dart_safe_line(r.code))
        if len(new) > SHOW_MAX:
            lines.append(f"(그 밖에 {len(new) - SHOW_MAX}종목 더)")
        lines.append("👉 내일 시가 매수 → 5거래일째 종가 매도, 손절 -10% (키움 자동감시주문으로 걸어 두기)\n"
                     "👉 신호가 많은 날(폭락장)도 1~2종목만, 소액으로")
        new = new.assign(buy=None, status="대기", sell_date=None, sell=None, ret=None)
        log = pd.concat([log, new[["date", "code", "name", "close", "buy", "status", "sell_date", "sell", "ret"]]])
    if reminders:
        lines.append("⏰ 내일 매도할 스윙 종목\n" + "\n".join(reminders))
    s = stats(log)
    if s:
        lines.append(s)
    log.to_csv(LOG, index=False)
    return "\n".join(lines)


if __name__ == "__main__":
    print(evening_section())
