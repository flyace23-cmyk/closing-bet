"""종가베팅 자동 복기

매일 19:00
  - 15:10에 알려준 후보(최대 2종목)를 샀다고 치고 모의 기록 (records/cb_mock.csv)
  - 쉰 날(시장 조건 미달)에도 장 마감 기준 1·2등을 '쉰 날 후보'로 따로 기록 → 쉰 게 맞았는지 확인
  - 어제 후보의 오늘 시가 결과를 한 줄로 알려줌
금요일 19:00 (그 주 마지막 거래일)
  - 주간 복기: 모의 후보 / 쉰 날 후보 / 실제 매매 / 체결 오차 / 15:10과 마감 순위 일치

계산 방식은 백테스트와 같다: 종가 매수 → 다음날 시가 매도, 비용 0.35% 뺌
"""
import os, datetime as dt
import pandas as pd
import market_data as md
from config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
MOCK = f"{REC}/cb_mock.csv"
TRADES = f"{REC}/trades.csv"
RANK = f"{REC}/rank_match.csv"
COST = 0.35
EXPECT = "백테스트 기대: 신호당 +0.3%, 승률 47%"


def _read(f, **kw):
    return pd.read_csv(f, dtype={"code": str, "date": str, "sell_date": str}, **kw) if os.path.exists(f) else pd.DataFrame()


def _settle(m):
    """아직 안 판 모의 기록을 다음 거래일 시가로 정산"""
    if m.empty:
        return m, []
    done = []
    for i, r in m[m.sell_date.isna() | (m.sell_date == "")].iterrows():
        if r.date >= md.today():
            continue
        try:
            d = md.daily(r.code, 10)
        except Exception:
            continue
        nxt = d[d.date > r.date]
        if nxt.empty:
            continue
        op = nxt.o.iloc[0]
        ret = round((op / r.buy - 1) * 100 - COST, 2)
        m.loc[i, ["sell_date", "sell_open", "ret"]] = [nxt.date.iloc[0], op, ret]
        done.append(m.loc[i])
    return m, done


def _today_rows(final):
    """오늘 기록할 후보: 15:10에 알려준 종목, 없으면(쉰 날) 마감 기준 1·2등"""
    f = f"{REC}/picks_{md.today()}.csv"
    if os.path.exists(f):
        p = pd.read_csv(f, dtype={"code": str})
        kind = "후보"
    else:
        if final is None or final.empty:
            return []
        p = final.head(CFG["max_picks"])
        kind = "쉰 날"
    rows = []
    for _, r in p.iterrows():
        try:
            close = md.daily(r.code, 3).c.iloc[-1]
        except Exception:
            continue
        rows.append(dict(date=md.today(), kind=kind, code=r.code, name=r["name"], buy=close,
                         sell_date="", sell_open=None, ret=None))
    return rows


def _stat(x, label):
    if x is None or len(x) == 0:
        return f"{label}: 없음"
    x = x.astype(float)
    return f"{label}: {len(x)}건, 승률 {(x > 0).mean() * 100:.0f}%, 평균 {x.mean():+.2f}%"


def daily(final=None):
    """19:00 저녁 정리에 붙일 복기 줄. final = 장 마감 기준 scan 결과(없으면 필요할 때 직접 구함)"""
    os.makedirs(REC, exist_ok=True)
    m = _read(MOCK)
    if m.empty:
        m = pd.DataFrame(columns=["date", "kind", "code", "name", "buy", "sell_date", "sell_open", "ret"])
    m, done = _settle(m)
    if final is None and not os.path.exists(f"{REC}/picks_{md.today()}.csv"):
        try:
            import scan_1510
            final = scan_1510.scan()
        except Exception:
            final = None
    new = _today_rows(final)
    new = [r for r in new if not ((m.date == r["date"]) & (m.code == r["code"])).any()]
    if new:
        m = pd.concat([m, pd.DataFrame(new)], ignore_index=True)
    m.to_csv(MOCK, index=False)

    lines = ["🔁 종가베팅 자동 복기"]
    if done:
        for r in done:
            tag = "어제 후보" if r.kind == "후보" else "어제 쉰 날 후보(참고)"
            lines.append(f"• {tag} {r['name']}: 종가 {r.buy:,.0f} → 오늘 시가 {r.sell_open:,.0f}, {r.ret:+.2f}%")
    else:
        lines.append("• 어제 기록할 후보 없음")
    if new:
        lines.append("• 오늘 " + ("후보" if new[0]["kind"] == "후보" else "쉰 날 후보(참고)") + " 기록: "
                     + ", ".join(r["name"] for r in new) + " → 내일 시가로 채점")
    c = m[(m.kind == "후보") & m.ret.notna()]
    s = m[(m.kind == "쉰 날") & m.ret.notna()]
    lines.append(_stat(c.ret, "📒 모의 누적(알려준 후보)") + f" ({EXPECT})")
    if len(s):
        lines.append(_stat(s.ret, "📒 쉰 날에 샀다면") + " → 플러스가 크면 쉬는 규칙을 다시 볼 때")
    if dt.datetime.strptime(md.today(), "%Y%m%d").weekday() == 4:
        lines.append(weekly(m))
    return "\n".join(lines)


def weekly(m=None):
    """그 주(월~금) 복기"""
    m = _read(MOCK) if m is None else m
    t = _read(TRADES)
    rk = _read(RANK)
    today = dt.datetime.strptime(md.today(), "%Y%m%d")
    mon = (today - dt.timedelta(days=today.weekday())).strftime("%Y%m%d")
    wk = lambda df, col: df[(df[col].astype(str) >= mon) & (df[col].astype(str) <= md.today())] if len(df) and col in df else pd.DataFrame()
    mw = wk(m, "sell_date")
    out = [f"📅 주간 복기 ({mon[4:6]}/{mon[6:]}~{md.today()[4:6]}/{md.today()[6:]})"]
    out.append(_stat(mw[mw.kind == "후보"].ret if len(mw) else None, "• 알려준 후보를 다 샀다면"))
    out.append(_stat(mw[mw.kind == "쉰 날"].ret if len(mw) else None, "• 쉰 날 후보를 샀다면"))
    tw = wk(t, "sell_date")
    out.append(_stat(tw.ret if len(tw) else None, "• 내 실제 매매"))
    if len(tw) and "slip" in tw:
        sl = tw.slip.astype(float).mean()
        out.append(f"• 평균 체결 오차 {sl:+.2f}% " + ("(0.2% 넘음: 주문 방법 점검)" if sl > 0.2 else "(괜찮음)"))
    rw = wk(rk, "date")
    if len(rw):
        out.append(f"• 15:10 선택과 마감 1·2등 일치 {rw.match.astype(int).sum()}/{rw.picked.astype(int).sum()}")
    if len(mw) and len(tw):
        miss = set(mw[mw.kind == "후보"].code) - set(tw.code)
        if miss:
            out.append("• 알림은 왔는데 안 산 종목: " + ", ".join(mw[mw.code.isin(miss)].name.unique()))
    return "\n".join(out)


if __name__ == "__main__":
    print(daily())
