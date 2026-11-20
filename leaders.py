"""오늘의 대장주 복기 (재료 읽는 눈 기르기용) — 19:00 저녁 정리에 붙음

매일 저녁
  ① 오늘 돈이 몰린 테마 TOP 3: 상승률 상위 30종목(거래대금 30억+) 중 몇 종목이 같은 테마인지
     테마마다 대장(가장 많이 오른 종목)과 2등주
  ② 오늘의 대장주 5종목: 10% 이상 오른 종목 중 거래대금 순 (상한가는 따로 표시)
     종목마다 '오른 이유' 후보 = 오늘 뉴스 제목 + 오늘 공시 제목 + 소속 테마
  ③ 어제 대장주의 오늘 성적: 재료가 하루 더 갔는지(시가·종가) → 어떤 재료가 이어지는지 감 잡기
  ④ 스스로 답해 볼 질문 하나 (정답을 맞히는 게 아니라 '왜'를 적어 보는 연습)

기록: records/leaders.csv (날짜, 종목, 오늘 등락률·거래대금·종가, 테마, 이유 한 줄)
매매 신호가 아니라 공부용 표시입니다.
"""
import os, re, html
import pandas as pd
import market_data as md
import info

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
LOG = f"{REC}/leaders.csv"
S = md.S
N_LEAD = 5          # 대장주 몇 종목
MIN_RET = 10.0      # 대장주 최소 등락률(%)
MIN_VALUE = 100     # 대장주 최소 거래대금(억)


def _news_today(code, name, n=3):
    """오늘 나온 뉴스 중 종목 이름이 들어간 제목 (특징주 기사 먼저, 최대 n개)"""
    try:
        r = S.get(f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=20&page=1", timeout=15).json()
        items = [it for g in r for it in g.get("items", [])]
        key = re.sub(r"\s", "", name)[:4]
        out = []
        for it in items:
            if not str(it.get("datetime", "")).startswith(md.today()):
                continue
            t = html.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip()
            if t and key in re.sub(r"\s", "", t) and t not in out:
                out.append(t)
        out.sort(key=lambda t: 0 if "특징주" in t else 1)
        return out[:n]
    except Exception:
        return []


def _market_line():
    try:
        p = []
        for k in ["KOSPI", "KOSDAQ"]:
            d = md.daily(k, 3)
            p.append(f"{'코스피' if k == 'KOSPI' else '코스닥'} {(d.c.iloc[-1] / d.c.iloc[-2] - 1) * 100:+.1f}%")
        return "   시장: " + ", ".join(p)
    except Exception:
        return ""


def _dart_today(code):
    """오늘 낸 공시 제목 (정정·첨부 제외). DART 키 없으면 빈 목록"""
    if not info.KEY:
        return []
    try:
        corp = info._corpmap().get(code)
        if not corp:
            return []
        r = S.get("https://opendart.fss.or.kr/api/list.json", params=dict(
            crtfc_key=info.KEY, corp_code=corp, bgn_de=md.today(), end_de=md.today(), page_count=20), timeout=20).json()
        names = []
        for x in r.get("list", []):
            nm = re.sub(r"\s+", " ", x["report_nm"]).strip()
            if nm.startswith("[") or nm in names:
                continue
            names.append(nm)
        return names[:2]
    except Exception:
        return []


def _themes_of(code, T):
    return [t["name"] for t in T if code in t["codes"]]


def top_themes(all_df, T, k=3):
    """상승률 상위 30 중 같은 테마로 묶이는 종목이 많은 순 TOP k"""
    x = all_df[(all_df.value >= 30) & (all_df.ret > 0) & (all_df.price >= 1000)].drop_duplicates("code")
    top = x.sort_values("ret", ascending=False).head(30)
    R = set(top.code)
    now = x.set_index("code")
    res, used = [], set()
    for t in sorted(T, key=lambda t: -len(R & set(t["codes"]))):
        hit = R & set(t["codes"])
        if len(hit) < 3:
            break
        if len(hit & used) >= len(hit) * 0.7:      # 거의 같은 종목으로 겹치는 테마는 건너뜀
            continue
        m = now.reindex([c for c in t["codes"] if c in now.index]).sort_values("ret", ascending=False)
        res.append(dict(name=t["name"], n=len(hit), lead=m.iloc[0]["name"], lead_ret=m.iloc[0].ret,
                        second=m.iloc[1]["name"] if len(m) > 1 else "", second_ret=m.iloc[1].ret if len(m) > 1 else 0))
        used |= hit
        if len(res) >= k:
            break
    return res


def leaders(all_df, n=N_LEAD):
    x = all_df[(all_df.ret >= MIN_RET) & (all_df.value >= MIN_VALUE)].drop_duplicates("code")
    return x.sort_values("value", ascending=False).head(n)


def _yesterday_check():
    """어제 기록한 대장주의 오늘 시가·종가"""
    if not os.path.exists(LOG):
        return []
    lg = pd.read_csv(LOG, dtype={"code": str, "date": str})
    prev = lg[lg.date < md.today()]
    if prev.empty:
        return []
    last = prev.date.max()
    out = []
    for r in prev[prev.date == last].itertuples():
        try:
            d = md.daily(r.code, 5)
            nxt = d[d.date > last]
            if nxt.empty:
                continue
            o, c = nxt.o.iloc[0], nxt.c.iloc[0]
            out.append((r.name, (o / r.close - 1) * 100, (c / r.close - 1) * 100))
        except Exception:
            continue
    return out


def _one_reason(news, dart, themes):
    if dart:
        return "공시: " + dart[0]
    if news:
        return "뉴스: " + news[0]
    if themes:
        return "테마: " + themes[0]
    return "뚜렷한 재료 못 찾음"


def evening_section(all_df=None):
    all_df = md.all_stocks() if all_df is None else all_df
    try:
        T = info._themes()
    except Exception:
        T = []
    lines = ["🧠 오늘의 대장주 복기 (공부용, 매매 신호 아님)", _market_line()]

    # ③ 어제 대장주 → 오늘 (먼저 보여 줌: 어제 적은 생각과 비교)
    y = _yesterday_check()
    if y:
        lines.append("↩️ 어제 대장주의 오늘")
        for nm, o, c in y:
            lines.append(f"   {nm}: 시가 {o:+.1f}% → 종가 {c:+.1f}%")
        keep = sum(1 for _, _, c in y if c > 0)
        lines.append(f"   → {len(y)}종목 중 {keep}종목이 하루 더 올랐음")

    # ① 테마
    tt = top_themes(all_df, T) if T else []
    if tt:
        lines.append("🔥 돈이 몰린 테마 (상승률 상위 30 중)")
        for i, t in enumerate(tt, 1):
            s = f" / 2등 {t['second']} {t['second_ret']:+.1f}%" if t["second"] else ""
            lines.append(f"   {i}. {t['name']} {t['n']}종목 — 대장 {t['lead']} {t['lead_ret']:+.1f}%{s}")
    else:
        lines.append("🔥 테마: 3종목 이상 묶인 테마 없음 (개별주 장세)")

    # ② 대장주와 오른 이유
    L = leaders(all_df)
    rows = []
    if L.empty:
        lines.append(f"👑 대장주: 오늘 {MIN_RET:.0f}% 이상 + 거래대금 {MIN_VALUE}억 이상 종목 없음")
    else:
        lines.append(f"👑 오늘의 대장주 (+{MIN_RET:.0f}%↑ 거래대금 순)")
        for i, r in enumerate(L.itertuples(), 1):
            news, dart = _news_today(r.code, r.name), _dart_today(r.code)
            th = _themes_of(r.code, T)
            tag = " 🔺상한가" if r.ret >= 29.5 else ""
            lines.append(f"{i}) {r.name} {r.ret:+.1f}% | {r.value:,.0f}억{tag}")
            if th:
                lines.append("   🏷 " + ", ".join(th[:3]))
            for d in dart:
                lines.append("   📄 " + d[:45])
            for nws in news[:2]:
                lines.append("   📰 " + nws[:45])
            if not (news or dart):
                lines.append("   (오늘 뉴스·공시 없음 → 테마 순환매나 수급일 수 있음)")
            rows.append(dict(date=md.today(), code=r.code, name=r.name, ret=r.ret, value=round(r.value),
                             close=r.price, themes="|".join(th[:3]), reason=_one_reason(news, dart, th)))

    if rows:
        old = pd.read_csv(LOG, dtype={"code": str, "date": str}) if os.path.exists(LOG) else pd.DataFrame()
        if len(old):
            old = old[old.date != md.today()]
        pd.concat([old, pd.DataFrame(rows)]).to_csv(LOG, index=False)

    lines.append("✍️ 오늘의 질문: 1등 대장주의 재료가 '하루짜리'(뉴스 한 건)인가, "
                 "'며칠 가는'(실적·정책·수주) 것인가? 한 줄로 답해 보고 내일 ↩️ 결과와 비교해 보세요.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(evening_section())
