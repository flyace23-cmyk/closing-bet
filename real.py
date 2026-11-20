"""실제 계좌 기록 (19:00 저녁 정리에 붙음)

어디서 오나
  - 키움: 노트북 예약 작업(평일 16:13)이 키움 연결로 잔고를 읽어 records/real/kiwoom_holdings.csv 로 올림
          → 어제 있던 종목이 사라지면 '매도'로 기록 (매도가는 그날 종가 기준)
  - 미래에셋 등 다른 계좌: 텔레그램으로 봇에게 한 줄
        실제 종목명 평단 [계좌]          예) 실제 지투지바이오 79852 미래에셋   (새로 샀거나 평단이 바뀌면)
        실제매도 종목명 매도가 [계좌]     예) 실제매도 지투지바이오 38000          (전부 판 경우)
        실제일부매도 종목명 매도가         (일부만 판 경우, 보유는 그대로)
        실제계획 종목명 내용...           예) 실제계획 금호건설 12000 매도 / 종가 8200 아래 손절
기록 (수량·금액은 저장하지 않음: 저장소가 공개라서)
  records/real/positions.csv  보유 중: 계좌, 종목, 코드, 시작일, 평단, 계획
  records/real/trades.csv     매도 기록: 날짜, 계좌, 종목, 구분(전부/일부), 평단, 매도가, 수익률(비용 0.25% 뺌)
"""
import os, re, html, datetime as dt
import pandas as pd
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "records", "real")
POS, TRD, KW = (os.path.join(D, f) for f in ("positions.csv", "trades.csv", "kiwoom_holdings.csv"))
PCOLS = ["계좌", "종목", "코드", "시작일", "평단", "계획"]
TCOLS = ["날짜", "계좌", "종목", "코드", "구분", "평단", "매도가", "수익률(%)"]
COST = 0.25


def _read(f, cols):
    if os.path.exists(f) and os.path.getsize(f):
        return pd.read_csv(f, dtype={"코드": str, "code": str})
    return pd.DataFrame(columns=cols)


def _ret(avg, sell):
    return round((sell / avg - 1) * 100 - COST, 2)


def parse(msgs, names):
    """텔레그램 명령 → 할 일 목록"""
    out = []
    for m in msgs:
        if dt.datetime.fromtimestamp(m["date"], md.KST).strftime("%Y%m%d") != md.today():
            continue
        for line in m.get("text", "").splitlines():
            g = re.match(r"\s*실제계획\s+(\S+)\s+(.+)", line)
            if g:
                out.append(("plan", g.group(1), g.group(2).strip(), None)); continue
            g = re.match(r"\s*실제(일부)?매도\s+(\S+)\s+([\d,]+)(?:\s+(\S+))?", line)
            if g:
                out.append(("sell_part" if g.group(1) else "sell", g.group(2), float(g.group(3).replace(",", "")), g.group(4))); continue
            g = re.match(r"\s*실제\s+(\S+)\s+([\d,]+)(?:\s+(\S+))?", line)
            if g:
                out.append(("buy", g.group(1), float(g.group(2).replace(",", "")), g.group(3)))
    res = []
    for kind, key, val, acct in out:
        code = key if re.match(r"^\d{6}$", key) else names.get(key)
        res.append((kind, key, code, val, acct))
    return res


def apply(cmds, pos, trd, code2name):
    notes = []
    for kind, key, code, val, acct in cmds:
        if not code:
            notes.append(f"⚠️ '{key}' 종목을 못 찾았어요 (이름을 정확히 쓰거나 6자리 코드로)"); continue
        name = code2name.get(code, key)
        hit = pos.index[pos.코드 == code]
        if kind == "buy":
            if len(hit):
                pos.loc[hit, "평단"] = val
                if acct:
                    pos.loc[hit, "계좌"] = acct
                notes.append(f"✏️ {name} 평단 {val:,.0f}원으로 고침")
            else:
                pos.loc[len(pos)] = [acct or "미래에셋", name, code, md.today(), val, ""]
                notes.append(f"➕ {name} 보유 추가 (평단 {val:,.0f}원, {acct or '미래에셋'})")
        elif kind == "plan":
            if len(hit):
                pos.loc[hit, "계획"] = val
                notes.append(f"📝 {name} 계획: {val}")
        elif kind in ("sell", "sell_part"):
            if not len(hit):
                notes.append(f"⚠️ {name}는 보유 기록에 없어요"); continue
            r = pos.loc[hit[0]]
            trd.loc[len(trd)] = [md.today(), r.계좌, name, code, "일부" if kind == "sell_part" else "전부", r.평단, val, _ret(float(r.평단), val)]
            notes.append(f"{'✂️' if kind == 'sell_part' else '✅'} {name} {'일부 ' if kind == 'sell_part' else ''}매도 {val:,.0f}원 → {_ret(float(r.평단), val):+.2f}%")
            if kind == "sell":
                pos = pos.drop(hit).reset_index(drop=True)
    return pos, trd, notes


def sync_kiwoom(pos, trd):
    """노트북이 올린 키움 잔고와 맞춤: 새 종목 추가, 평단 갱신, 사라진 종목은 '전부 매도'로 기록"""
    if not os.path.exists(KW):
        return pos, trd, []
    kw = pd.read_csv(KW, dtype={"코드": str})
    notes = []
    now = set(kw.코드)
    for r in kw.itertuples():
        hit = pos.index[(pos.코드 == r.코드) & (pos.계좌 == "키움")]
        if len(hit):
            pos.loc[hit, "평단"] = r.평단
        else:
            pos.loc[len(pos)] = ["키움", r.종목, r.코드, md.today(), r.평단, ""]
            notes.append(f"➕ 키움 {r.종목} 보유 추가 (평단 {r.평단:,.0f}원)")
    gone = pos[(pos.계좌 == "키움") & ~pos.코드.isin(now)]
    for r in gone.itertuples():
        try:
            sell = float(md.daily(r.코드, 2).c.iloc[-1])
        except Exception:
            continue
        trd.loc[len(trd)] = [md.today(), "키움", r.종목, r.코드, "전부", r.평단, sell, _ret(float(r.평단), sell)]
        notes.append(f"✅ 키움 {r.종목} 매도 확인 (오늘 종가 {sell:,.0f}원 기준 {_ret(float(r.평단), sell):+.2f}%)")
    pos = pos[~pos.index.isin(gone.index)].reset_index(drop=True)
    return pos, trd, notes


def section(msgs, L):
    os.makedirs(D, exist_ok=True)
    names = dict(zip(L.name, L.code)); code2name = dict(zip(L.code, L.name)); price = dict(zip(L.code, L.price))
    pos, trd = _read(POS, PCOLS), _read(TRD, TCOLS)
    pos, trd, n1 = sync_kiwoom(pos, trd)
    pos, trd, n2 = apply(parse(msgs, names), pos, trd, code2name)
    pos.to_csv(POS, index=False); trd.to_csv(TRD, index=False)
    lines = ["<b>💼 실제 계좌</b>"] + n1 + n2
    if len(pos):
        rows = []
        for r in pos.itertuples():
            c = price.get(r.코드)
            ret = (c / float(r.평단) - 1) * 100 if c else None
            rows.append(f"{(f'{ret:+6.1f}%' if ret is not None else '   –  ')}  {html.escape(r.종목)} ({html.escape(str(r.계좌))})")
            if isinstance(r.계획, str) and r.계획:
                rows.append(f"         계획: {html.escape(r.계획)}")
        lines.append("<pre>" + "\n".join(rows) + "</pre>")
    else:
        lines.append("보유 기록 없음")
    lines.append("미래에셋 등은 '실제 종목 평단', '실제매도 종목 매도가'로 알려 주세요.")
    return "\n".join(lines)
