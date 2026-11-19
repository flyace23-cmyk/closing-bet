"""대시보드용 기록 모으기

봇 기록(records 폴더)과 노트북 VI 알림봇 기록(review.csv, trades.csv)을 모아
대시보드가 읽는 CSV 3개를 만든다.

  trades.csv    끝난 매매 한 줄씩 (매매법, 구분, 종목, 산 날, 판 날, 수익률)
  summary.csv   매매법·구분별 건수·승률·평균 + 백테스트 기대치
  holdings.csv  지금 진행 중인 것 (저가매수 5칸, 스윙 A, 중기 스윙)

사용: python tools/build_dashboard.py <출력폴더> [VI알림봇 폴더]
"""
import csv, json, os, sys
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(HERE, "records")

# 백테스트 기대치 (근거: 프로젝트 검증 문서들)
EXPECT = {
    ("종가베팅", "실제"): (47, 0.32), ("종가베팅", "모의(알려준 후보)"): (47, 0.32),
    ("저가매수", "내 5칸"): (75, 5.5), ("저가매수", "전체 신호"): (75, 5.5),
    ("스윙 A", "모의"): (55, 2.4),
    ("중기 스윙", "모의"): (28, 4.0), ("중기 스윙", "실제"): (28, 4.0),
}
ORDER = ["종가베팅", "저가매수", "스윙 A", "중기 스윙", "VI 단타"]


def _read(name, **kw):
    f = os.path.join(REC, name)
    if not os.path.exists(f) or os.path.getsize(f) == 0:
        return pd.DataFrame()
    return pd.read_csv(f, dtype=str, **kw)


def _d(s):
    s = str(s or "").replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def _f(x):
    try:
        v = float(x)
        return None if v != v else v
    except Exception:
        return None


def collect(vi_dir=None):
    rows, hold = [], []

    def add(strat, kind, name, start, end, ret, note=""):
        r = _f(ret)
        if r is None:
            return
        rows.append({"매매법": strat, "구분": kind, "종목": name, "산 날": _d(start), "판 날": _d(end),
                     "수익률(%)": round(r, 2), "메모": note})

    # 종가베팅
    for r in _read("trades.csv").to_dict("records"):
        add("종가베팅", "실제", r.get("name"), r.get("date"), r.get("sell_date"), r.get("ret"),
            f"체결 오차 {float(r['slip']):+.2f}%" if _f(r.get("slip")) is not None else "")
    for r in _read("cb_mock.csv").to_dict("records"):
        kind = "모의(알려준 후보)" if r.get("kind") == "후보" else "쉰 날 후보(참고)"
        add("종가베팅", kind, r.get("name"), r.get("date"), r.get("sell_date"), r.get("ret"))
    # 저가매수
    for r in _read("lowbuy_trades.csv").to_dict("records"):
        slot = str(r.get("slot")).lower() == "true"
        add("저가매수", "내 5칸" if slot else "전체 신호", r.get("name"), r.get("entry"), r.get("exit"), r.get("ret"),
            f"{r.get('buys')}차까지, {r.get('why', '')}")
    try:
        st = json.load(open(os.path.join(REC, "lowbuy_state.json")))
        for c in st.get("slots", []):
            p = st["pos"].get(c)
            if not p:
                continue
            b = [(e[2], e[3]) for e in p["ev"] if e[1] == "B"]
            avg = sum(x * f for x, f in b) / sum(f for _, f in b)
            hold.append({"매매법": "저가매수", "종목": p["name"], "시작일": _d(p["ev"][0][0]),
                         "상태": f"{p['buys']}차까지 매수" + (", 절반 매도함" if p.get("half") else ""),
                         "평단": round(avg), "최근 기록일": _d(st["upto"].get(c, ""))})
    except Exception:
        pass
    # 스윙 A (모의)
    sw = _read("swing_a.csv")
    for r in sw.to_dict("records"):
        if r.get("status") in ("손절", "만기"):
            add("스윙 A", "모의", r.get("name"), r.get("date"), r.get("sell_date"), r.get("ret"), r.get("status"))
        elif r.get("status") in ("대기", "보유"):
            hold.append({"매매법": "스윙 A", "종목": r.get("name"), "시작일": _d(r.get("date")),
                         "상태": r.get("status"), "평단": round(_f(r.get("buy")) or _f(r.get("close")) or 0), "최근 기록일": ""})
    # 중기 스윙
    for fname, kind in (("canslim_mock.csv", "모의"), ("canslim_mine.csv", "실제")):
        for r in _read(fname).to_dict("records"):
            if r.get("status") == "종료":
                add("중기 스윙", kind, r.get("name"), r.get("date"), r.get("end_date"), r.get("ret"), r.get("why", ""))
            elif r.get("status") == "보유":
                hold.append({"매매법": f"중기 스윙({kind})", "종목": r.get("name"), "시작일": _d(r.get("date")),
                             "상태": "보유", "평단": round(_f(r.get("buy")) or 0), "최근 기록일": ""})
    # VI 단타 (노트북)
    if vi_dir:
        f = os.path.join(vi_dir, "review.csv")
        if os.path.exists(f):
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                kind = "자동 복기(정식 시간)" if r.get("구분") == "정식" else "자동 복기(시간 밖·참고)"
                add("VI 단타", kind, r.get("종목명"), r.get("날짜"), r.get("날짜"), r.get("수익률(%)"),
                    f"{r.get('VI시각', '')[:5]} VI → {r.get('결과', '')}")
        f = os.path.join(vi_dir, "trades.csv")
        if os.path.exists(f):
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                add("VI 단타", "봇 신호", r.get("종목명"), r.get("날짜"), r.get("날짜"), r.get("수익률(%)"),
                    r.get("종료이유", ""))

    t = pd.DataFrame(rows, columns=["매매법", "구분", "종목", "산 날", "판 날", "수익률(%)", "메모"])
    t = t.sort_values(["판 날", "매매법"], ascending=[False, True])

    # 요약: 저가매수 '전체 신호'는 5칸 매매도 포함
    groups = []
    for (s, k), g in t.groupby(["매매법", "구분"]):
        groups.append((s, k, g))
    lb = t[t.매매법 == "저가매수"]
    groups = [x for x in groups if not (x[0] == "저가매수" and x[1] == "전체 신호")]
    groups.append(("저가매수", "전체 신호", lb))
    summ = []
    for s, k, g in groups:
        r = g["수익률(%)"].astype(float)
        e = EXPECT.get((s, k), (None, None))
        summ.append({"매매법": s, "구분": k, "건수": len(r),
                     "승률(%)": round((r > 0).mean() * 100, 1) if len(r) else None,
                     "평균(%)": round(r.mean(), 2) if len(r) else None,
                     "기대 승률(%)": e[0], "기대 평균(%)": e[1]})
    # 아직 기록이 없는 매매법도 줄을 남겨 둠
    have = {(x["매매법"], x["구분"]) for x in summ}
    for key in EXPECT:
        if key not in have:
            summ.append({"매매법": key[0], "구분": key[1], "건수": 0, "승률(%)": None, "평균(%)": None,
                         "기대 승률(%)": EXPECT[key][0], "기대 평균(%)": EXPECT[key][1]})
    for k in ("자동 복기(정식 시간)", "봇 신호"):
        if ("VI 단타", k) not in have:
            summ.append({"매매법": "VI 단타", "구분": k, "건수": 0, "승률(%)": None, "평균(%)": None,
                         "기대 승률(%)": None, "기대 평균(%)": None})
    s = pd.DataFrame(summ)
    s["순서"] = s.매매법.map({k: i for i, k in enumerate(ORDER)})
    s = s.sort_values(["순서", "구분"]).drop(columns="순서")
    h = pd.DataFrame(hold, columns=["매매법", "종목", "시작일", "상태", "평단", "최근 기록일"])
    return t, s, h


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    vi = sys.argv[2] if len(sys.argv) > 2 else None
    os.makedirs(out, exist_ok=True)
    t, s, h = collect(vi)
    t.to_csv(os.path.join(out, "trades.csv"), index=False)
    s.to_csv(os.path.join(out, "summary.csv"), index=False)
    h.to_csv(os.path.join(out, "holdings.csv"), index=False)
    print(f"매매 {len(t)}건, 요약 {len(s)}줄, 진행 중 {len(h)}건 → {out}")
