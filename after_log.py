"""애프터장 기록 (19:00 저녁 정리 때 실행)

어제 애프터장(~20:00)에서 크게 움직인 종목과 어제 종가베팅 후보를 모아서,
오늘 시가·종가와 함께 records/after_log.csv에 쌓는다. 2~3개월 뒤 다시 검증하기 위한 데이터.
검증 근거: 프로젝트 문서 '영상검증-애프터장-장세판단-2026-11' (43거래일이라 판단 보류)
- 영상 사례: 정규장 하락 + 애프터장 +3% 이상 → 다음날 시가 매수·종가 매도
- 종가베팅 후보: 애프터장 20:00 가격에 팔았다면 vs 다음날 시가에 팔았다면
네이버 일봉 종가(애프터장 포함)와 야후 일봉 종가(KRX 정규장)의 차이로 애프터장 움직임을 계산한다.
"""
import os, re, glob
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
LOG = f"{REC}/after_log.csv"
COST = 0.35


def _naver_raw(code, n=6):
    t = md.S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={n}&requestType=0", timeout=15).text
    d = pd.DataFrame(md._items(t), columns=["date", "o", "h", "l", "c", "v"])
    d[["o", "h", "l", "c", "v"]] = d[["o", "h", "l", "c", "v"]].astype(float)
    return d


def _one(row, picks):
    code = row["code"]
    try:
        raw = _naver_raw(code)
        krx = md.daily(code, 6)       # 고친 일봉 = KRX 정규장 값
    except Exception:
        return None
    if len(raw) < 3 or raw.date.iloc[-1] != md.today() or krx.date.iloc[-1] != md.today():
        return None
    y, t = raw.iloc[-2], krx.iloc[-1]                  # 어제(애프터장 포함), 오늘(KRX)
    yk, pk = krx.iloc[-2], krx.iloc[-3]                # 어제·그제 KRX
    if yk.date != y.date or yk.c <= 0 or pk.c <= 0:
        return None
    after = (y.c / yk.c - 1) * 100
    ret_k = (yk.c / pk.c - 1) * 100
    is_pick = code in picks
    case = ret_k < 0 and after >= 3
    if not (is_pick or abs(after) >= 3):
        return None
    return dict(date=y.date, code=code, name=row["name"], kind="종가베팅후보" if is_pick else ("영상사례" if case else "애프터3%"),
                ret_k=round(ret_k, 2), after=round(after, 2), close_k=yk.c, after_px=y.c,
                next_open=t.o, next_close=t.c,
                gap=round((t.o / yk.c - 1) * 100, 2),                       # KRX 종가 → 오늘 시가
                buy_after_to_open=round((t.o / y.c - 1) * 100 - COST, 2),   # 애프터장 가격 매수 → 시가
                open_to_close=round((t.c / t.o - 1) * 100 - COST, 2))       # 오늘 시가 매수 → 종가


def run():
    """오늘 19:00 실행: 어제 날짜 기록을 만들고, 누적 요약 한 줄을 돌려줌"""
    os.makedirs(REC, exist_ok=True)
    old = pd.read_csv(LOG, dtype={"code": str, "date": str}) if os.path.exists(LOG) else pd.DataFrame()
    L = md.all_stocks()
    L = L[(L.value >= 30) & (L.price >= 1000)]
    prev = sorted(f for f in glob.glob(f"{REC}/picks_*.csv") if not f.endswith(f"_{md.today()}.csv"))
    picks = set(pd.read_csv(prev[-1], dtype={"code": str}).code) if prev else set()
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(lambda r: _one(r, picks), L.to_dict("records")) if r]
    new = pd.DataFrame(rows)
    if len(new):
        if len(old):
            new = new[~new.date.isin(old.date.unique())]   # 같은 날 두 번 저장 안 함
        allr = pd.concat([old, new], ignore_index=True)
        allr.to_csv(LOG, index=False)
    else:
        allr = old
    if allr.empty:
        return "📝 애프터장 기록: 아직 없음"
    c = allr[allr.kind == "영상사례"]
    up = allr[allr.after >= 3]
    pk = allr[allr.kind == "종가베팅후보"].copy()
    txt = (f"📝 애프터장 기록 ({allr.date.nunique()}일 누적, 어제 {len(new)}건 저장)\n"
           f"   영상 사례 {len(c)}건: 다음날 시가→종가 평균 {c.open_to_close.mean():+.2f}%" if len(c) else
           f"📝 애프터장 기록 ({allr.date.nunique()}일 누적, 어제 {len(new)}건 저장)\n   영상 사례 아직 없음")
    if len(up):
        txt += f"\n   애프터 +3%↑ {len(up)}건: 애프터장 가격 매수→시가 {up.buy_after_to_open.mean():+.2f}% (따라 사지 않기)"
    if len(pk):
        pk["sell_after"] = pk.after - COST
        pk["sell_open"] = pk.gap - COST
        txt += f"\n   종가베팅 후보 {len(pk)}건: 애프터장 매도 {pk.sell_after.mean():+.2f}% vs 다음날 시가 매도 {pk.sell_open.mean():+.2f}%"
    return txt


if __name__ == "__main__":
    print(run())
