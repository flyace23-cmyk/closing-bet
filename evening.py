"""저녁 정리 알림: 봇에게 보낸 '매수 종목 수량'을 읽어 다음날 매도 세팅을 계산"""
import os, re, sys, datetime as dt
import pandas as pd
from config import CFG, PROFILE, SPLIT, LOSS_STREAK, REDUCE_DAYS, REDUCE_TO
import market_data as md
from telegram import send, updates

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
os.makedirs(REC, exist_ok=True)
POS, TRADES = f"{REC}/positions.csv", f"{REC}/trades.csv"


def tick(p):
    """2023년 이후 코스피·코스닥 공통 호가 단위"""
    for lim, t in [(2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)]:
        if p < lim:
            return t
    return 1000


def down(p): t = tick(p); return int(p // t * t)
def up(p): t = tick(p); return int(-(-p // t) * t)


def parse(msgs, names):
    """'매수 삼성전자 25' / '매수 005930 25 191300' 형식"""
    out = []
    for m in msgs:
        d = dt.datetime.fromtimestamp(m["date"], md.KST).strftime("%Y%m%d")
        if d != md.today():
            continue
        for line in m.get("text", "").splitlines():
            g = re.match(r"\s*매수\s+(\S+)\s+(\d+)(?:\s+(\d+))?", line)
            if not g:
                continue
            key, qty, price = g.group(1), int(g.group(2)), g.group(3)
            code = key if re.match(r"^\d{6}$", key) else names.get(key)
            if code:
                out.append(dict(code=code, qty=qty, price=float(price) if price else None))
    return out


def guide(name, code, buy, qty):
    if CFG["exit_mode"] == "open":
        return (f"📌 {name} ({code}) {qty}주 @ {buy:,.0f}원\n"
                f"① 오늘 저녁 키움 예약주문: {qty}주 전부 '다음날 시장가 매도'\n"
                f"   (다음날 09:00 시가에 체결, 이익·손실 상관없이)")
    q1 = (qty + 1) // 2
    q2 = qty - q1
    stop = down(buy * (1 + SPLIT["stop"] / 100))
    vi = up(buy * (1 + SPLIT["vi"] / 100))
    return (f"📌 {name} ({code}) {qty}주 @ {buy:,.0f}원\n"
            f"① 오늘 저녁 키움 예약주문: {q1}주 '다음날 시장가 매도'\n"
            f"② 내일 08:50 키움 자동감시주문: {q2}주\n"
            f"   • 손절: {stop:,}원 이하 → 시장가 매도 ({SPLIT['stop']}%)\n"
            f"   • 1차 익절: 시가 x {1 + SPLIT['target_from_open'] / 100:.2f} 또는 {vi:,}원(VI 부근, +{SPLIT['vi']:.0f}%) 중 먼저 닿는 값에서 절반\n"
            f"     (시가가 정해지면 '시가 x 1.06'을 호가 단위로 올림해서 입력)\n"
            f"   • 나머지: 고점 대비 {SPLIT['trail']}% 하락 시 매도\n"
            f"   • {SPLIT['time_stop']}까지 안 끝나면 전량 시장가 정리")


def settle_yesterday():
    """어제 산 종목을 오늘 시가로 기록 (실제 체결과 다를 수 있음)"""
    if not os.path.exists(POS):
        return []
    pos = pd.read_csv(POS, dtype={"code": str, "date": str})
    pos = pos[pos.date < md.today()]
    done = []
    for p in pos.itertuples():
        d = md.daily(p.code, 5)
        nxt = d[d.date > p.date]
        if nxt.empty:
            continue
        op = nxt.o.iloc[0]
        r = (op / p.buy - 1) * 100 - 0.35
        done.append(dict(date=p.date, sell_date=nxt.date.iloc[0], code=p.code, name=p.name, qty=p.qty, buy=p.buy,
                         slip=getattr(p, "slip", 0.0), sell_open=op, ret=round(r, 2)))
    if done:
        old = pd.read_csv(TRADES, dtype={"code": str, "date": str}) if os.path.exists(TRADES) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(done)]).to_csv(TRADES, index=False)
        left = pd.read_csv(POS, dtype={"code": str, "date": str})
        left[~left.code.isin([x["code"] for x in done]) | (left.date >= md.today())].to_csv(POS, index=False)
    return done


def streak_note():
    if not os.path.exists(TRADES):
        return ""
    t = pd.read_csv(TRADES)
    n = 0
    for r in t.ret[::-1]:
        if r > 0: break
        n += 1
    total = f"\n📒 누적 {len(t)}건 | 승률 {(t.ret > 0).mean() * 100:.0f}% | 평균 {t.ret.mean():+.2f}% (시가 기준, 비용 0.35% 뺌)"
    if "slip" in t:
        total += f"\n   평균 매수 체결 오차 {t.slip.mean():+.2f}% (0.2% 넘으면 점검)"
    if n >= LOSS_STREAK:
        return total + f"\n⚠️ {n}연속 손실 → 다음 {REDUCE_DAYS}거래일은 투입 금액 {REDUCE_TO * 100:.0f}%로"
    return total


def rank_check():
    """15:10에 고른 종목과 장 마감 확정 기준 1~2등이 같은지 기록"""
    f = f"{REC}/picks_{md.today()}.csv"
    if not os.path.exists(f):
        return ""
    import scan_1510
    early = list(pd.read_csv(f, dtype={"code": str}).code)
    final = scan_1510.scan()
    final_top = list(final.head(CFG["max_picks"]).code) if len(final) else []
    hit = len(set(early) & set(final_top))
    log = f"{REC}/rank_match.csv"
    old = pd.read_csv(log, dtype=str) if os.path.exists(log) else pd.DataFrame()
    row = pd.DataFrame([dict(date=md.today(), at1510=",".join(early), at_close=",".join(final_top), match=hit, picked=len(early))])
    allr = pd.concat([old, row]); allr.to_csv(log, index=False)
    m = allr.match.astype(int).sum(); p = allr.picked.astype(int).sum()
    names = dict(zip(final.code, final.name)) if len(final) else {}
    return (f"🔎 마감 기준 1~2등: {', '.join(names.get(x, x) for x in final_top) or '없음'} "
            f"(15:10 선택과 {hit}/{len(early)} 일치, 누적 일치율 {m / p * 100:.0f}%)" if p else "")


def main():
    if md.daily("KOSPI", 2).date.iloc[-1] != md.today() and "--now" not in sys.argv:
        print("휴장일"); return
    done = settle_yesterday()
    picks_f = f"{REC}/picks_{md.today()}.csv"
    names = {}
    if os.path.exists(picks_f):
        p = pd.read_csv(picks_f, dtype={"code": str}); names = dict(zip(p.name, p.code))
    L = md.all_stocks()
    names = {**dict(zip(L.name, L.code)), **names}
    msgs = updates()
    buys = parse(msgs, names)
    msg = [f"🌙 저녁 정리 ({PROFILE})"]
    for d in done:
        msg.append(f"어제 {d['name']} → 오늘 시가 {d['sell_open']:,.0f}원, {d['ret']:+.2f}%")
    rows = []
    for b in buys:
        day = md.daily(b["code"], 3)
        buy = b["price"] or day.c.iloc[-1]
        name = next((k for k, v in names.items() if v == b["code"]), b["code"])
        close = day.c.iloc[-1]
        slip = (buy / close - 1) * 100
        msg.append(guide(name, b["code"], buy, b["qty"]) + f"\n   체결 오차: 종가 {close:,.0f}원 대비 {slip:+.2f}%")
        rows.append(dict(date=md.today(), code=b["code"], name=name, qty=b["qty"], buy=buy, close=close, slip=round(slip, 3)))
    if not buys:
        msg.append("오늘 받은 매수 기록 없음 (봇에게 '매수 종목명 수량 체결가'를 보내면 계산해 드려요)")
    if rows:
        old = pd.read_csv(POS, dtype={"code": str, "date": str}) if os.path.exists(POS) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(rows)]).to_csv(POS, index=False)
    try:
        msg.append(rank_check())
    except Exception as e:
        msg.append(f"(순위 비교 실패: {e})")
    msg.append(streak_note())
    try:
        import swing
        msg.append(swing.evening_section())
    except Exception as e:
        msg.append(f"(스윙 A 확인 실패: {e})")
    send("\n\n".join(x for x in msg if x))
    try:
        import lowbuy
        send(lowbuy.evening_section(msgs))
    except Exception as e:
        send(f"(저가매수 확인 실패: {e})")
    try:
        import canslim
        send(canslim.evening_section(msgs))
    except Exception as e:
        send(f"(중기 스윙 확인 실패: {e})")


if __name__ == "__main__":
    main()
