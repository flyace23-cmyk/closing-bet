"""알림 모아보기 웹페이지 만들기 (GitHub Pages: docs 폴더)

봇이 15:10·19:00에 알림을 보낸 뒤 이 파일을 실행하면 docs/ 아래에
  index.html          첫 화면: 최근 알림, 매매법별 누적 성적, 진행 중 종목, 날짜·주 목록
  d/YYYYMMDD.html     하루치: 그날 보낸 알림 원문 + 대장주 + 아버지 방식 모의 + 그날 끝난 매매
  w/YYYYMMDD.html     한 주(월요일 날짜): 매매법별 그 주 성적, 대장주 다음날 성적, 아버지 방식 모의 집계
를 새로 만든다. 사용: python tools/build_site.py
"""
import os, sys, json, glob, html, datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REC = os.path.join(ROOT, "records")
OUT = os.path.join(ROOT, "docs")
E = lambda x: html.escape("" if x is None or (isinstance(x, float) and x != x) else str(x), quote=False)
WD = "월화수목금토일"


def fmt_d(d):
    x = dt.datetime.strptime(d, "%Y%m%d")
    return f"{x.month}월 {x.day}일({WD[x.weekday()]})"


def monday(d):
    x = dt.datetime.strptime(d, "%Y%m%d")
    return (x - dt.timedelta(days=x.weekday())).strftime("%Y%m%d")


def read(name):
    f = os.path.join(REC, name)
    return pd.read_csv(f, dtype={"code": str, "date": str}) if os.path.exists(f) and os.path.getsize(f) else pd.DataFrame()


def num(v, nd=2, sign=True, unit="%"):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    if v != v:
        return "–"
    cls = "up" if v > 0 else "dn" if v < 0 else ""
    return f'<span class="{cls}">{v:+.{nd}f}{unit}</span>' if sign else f"{v:,.{nd}f}{unit}"


def table(head, rows, cls="", right=()):
    th = "".join(f'<th class="{"r" if i in right else ""}">{h}</th>' for i, h in enumerate(head))
    tb = "".join("<tr>" + "".join(f'<td class="{"r" if i in right else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>' if rows else '<p class="empty">기록 없음</p>'


def messages(d):
    f = os.path.join(REC, "messages", f"{d}.jsonl")
    out = []
    if os.path.exists(f):
        for line in open(f, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def msg_html(m):
    body = m["text"] if m.get("html") else E(m["text"])
    body = body.replace("\n<pre>", "<pre>").replace("</pre>\n", "</pre>").replace("\n\n", "\n")
    return f'<article class="msg"><time>{E(m["t"])}</time><div class="bubble">{body}</div></article>'


def stat(r):
    r = pd.to_numeric(r, errors="coerce").dropna()
    if not len(r):
        return 0, None, None
    return len(r), (r > 0).mean() * 100, r.mean()


# ---------- 데이터 ----------
def load():
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_dashboard as bd
        t, s, h = bd.collect()
    except Exception as e:
        print("성적 모으기 실패:", e)
        t = s = h = pd.DataFrame()
    fm = read("father_mock.csv")
    if len(fm):
        fm["ret"] = pd.to_numeric(fm.ret)
        add = pd.DataFrame(dict(매매법="아버지 방식", 구분="모의(15분봉 단타)", 종목=fm.name,
                                **{"산 날": fm.date.map(lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"), "판 날": fm.date.map(lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"),
                                   "수익률(%)": fm.ret.round(2), "메모": fm.why}))
        t = pd.concat([t, add], ignore_index=True) if len(t) else add
    lead = read("leaders.csv")
    return t, s, h, fm, lead


def all_dates(t, fm, lead):
    ds = {os.path.basename(f)[:8] for f in glob.glob(os.path.join(REC, "messages", "*.jsonl"))}
    ds |= set(fm.date) if len(fm) else set()
    ds |= set(lead.date) if len(lead) else set()
    if len(t):
        ds |= {x.replace("-", "") for x in t["판 날"].dropna() if x}
    return sorted((d for d in ds if len(d) == 8 and d.isdigit()), reverse=True)


# ---------- 조각 ----------
def leaders_block(lead, d):
    x = lead[lead.date == d] if len(lead) else lead
    if not len(x):
        return '<p class="empty">대장주 기록 없음</p>'
    rows = []
    for r in x.itertuples():
        no, nc = getattr(r, "next_open", None), getattr(r, "next_close", None)
        rows.append([E(r.name), num(r.ret, 1), f"{float(r.value):,.0f}억", num(no, 1), num(nc, 1), E(r.reason)])
    return table(["종목", "오늘", "거래대금", "다음날 시가", "다음날 종가", "오른 이유 후보"], rows, "stack", right=(1, 2, 3, 4))


def father_block(fm, ds):
    x = fm[fm.date.isin(ds)] if len(fm) else fm
    if not len(x):
        return '<p class="empty">아버지 방식 모의매매 기록 없음</p>'
    rows = [[fmt_d(r.date)[:-3] if len(ds) > 1 else "", f"{int(r.t_in) // 100:02d}:{int(r.t_in) % 100:02d}→{int(r.t_out) // 100:02d}:{int(r.t_out) % 100:02d}",
             E(r.name), f"{float(r.buy):,.0f}", f"{float(r.sell):,.0f}", num(r.ret), E(r.why)] for r in x.itertuples()]
    n, w, a = stat(x.ret)
    head = f'<p class="kpi">{n}건 · 승률 {w:.0f}% · 평균 {num(a)} <small>(비용 0.35% 뺌, 1년 검증 기대 -0.4%)</small></p>'
    cols = ["날짜", "시간", "종목", "매수가", "매도가", "수익률", "매도 이유"]
    if len(ds) == 1:
        cols, rows = cols[1:], [r[1:] for r in rows]
        return head + table(cols, rows, "stack", right=(2, 3, 4))
    return head + table(cols, rows, "stack", right=(3, 4, 5))


def strat_table(t, title_kind="누적"):
    if not len(t):
        return '<p class="empty">끝난 매매 없음</p>'
    rows = []
    for (s, k), g in t.groupby(["매매법", "구분"], sort=False):
        n, w, a = stat(g["수익률(%)"])
        rows.append([E(s), E(k), str(n), f"{w:.0f}%" if w is not None else "–", num(a)])
    return table(["매매법", "구분", "건수", "승률", "평균"], rows, "stack", right=(2, 3, 4))


def trades_table(t):
    if not len(t):
        return '<p class="empty">끝난 매매 없음</p>'
    rows = [[E(r["판 날"]), E(r["매매법"]), E(r["구분"]), E(r["종목"]), num(r["수익률(%)"]), E(r["메모"])] for r in t.to_dict("records")]
    return table(["판 날", "매매법", "구분", "종목", "수익률", "메모"], rows, "stack", right=(4,))


# ---------- 페이지 ----------
CSS = """
/* VOICE 차분한 신문 경제면 / IDEA 주간 리더 페이지 / PICTURE 알림 말풍선 타임라인
   COLOUR 흰 바탕·먹색·빨간 탭·슬레이트 / TYPE Noto Serif KR 제목 + Noto Sans KR 본문 / LAYOUT 한 단, 휴대폰 우선 */
:root{color-scheme:light dark;--bg:light-dark(#fff,#10191e);--ink:light-dark(#121212,#e9eef0);--mute:light-dark(#5b6670,#9aa8b1);
--red:#e3120b;--slate:light-dark(#2e6f8e,#7fb6cf);--panel:light-dark(#e3ecf0,#18252c);--line:light-dark(#d5dde2,#2a3a43);
--up:light-dark(#c4161c,#ff6b66);--dn:light-dark(#1f5fbf,#6aa4ff)}
:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
*{box-sizing:border-box;min-width:0}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "Noto Sans KR",system-ui,sans-serif;overflow-x:clip}
a{color:var(--slate)}
header{border-top:6px solid var(--red);padding:20px max(5vw,16px) 8px;max-width:980px;margin:auto}
header .tab{display:inline-block;background:var(--red);color:#fff;font-weight:700;font-size:13px;padding:2px 10px;margin-bottom:10px}
h1{font:700 clamp(28px,5vw,42px)/1.15 "Noto Serif KR",serif;margin:0 0 6px;text-wrap:balance}
h2{font:700 22px/1.3 "Noto Serif KR",serif;margin:36px 0 10px;padding-top:10px;border-top:1px solid var(--line)}
main{max-width:980px;margin:auto;padding:0 max(5vw,16px) 60px}
.sub{color:var(--mute);margin:0}
nav.scroll{display:flex;gap:8px;overflow-x:auto;padding:12px 0}
nav.scroll a{flex:none;padding:8px 14px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--ink);font-size:14px}
nav.scroll a.on{background:var(--ink);color:var(--bg)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:14px 0}
.kpis div{background:var(--bg);padding:12px 14px}.kpis b{display:block;font:700 26px/1.2 "Noto Serif KR",serif}.kpis div>span{color:var(--mute);font-size:13px}
.kpi{margin:4px 0 10px}
.msg{display:grid;grid-template-columns:52px 1fr;gap:10px;margin:14px 0}
.msg time{font-weight:700;color:var(--slate);padding-top:10px;font-size:14px}
.bubble{background:var(--panel);border-radius:4px 14px 14px 14px;padding:12px 14px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px}
.bubble pre{margin:4px 0 8px;white-space:pre;overflow-x:auto;font:13.5px/1.55 ui-monospace,"D2Coding",monospace;background:var(--bg);padding:8px 10px;border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:13px;color:var(--mute);font-weight:500}.r{text-align:right;white-space:nowrap}
.up{color:var(--up);font-weight:600}.dn{color:var(--dn);font-weight:600}
.empty{color:var(--mute)}small{color:var(--mute)}
.list{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;padding:0;list-style:none}
.list a{display:block;padding:10px 12px;background:var(--panel);text-decoration:none;color:var(--ink);border-radius:6px}
footer{color:var(--mute);font-size:13px;margin-top:40px}
.scroll{overflow-x:auto}
@media(max-width:600px){table{font-size:14px}.stack thead{display:none}.stack tr{display:grid;padding-block:10px;border-bottom:1px solid var(--line)}.stack td{display:flow-root;border:0;padding:3px 0;padding-inline-start:7.5em;text-align:start}.stack td::before{content:attr(data-l);float:inline-start;width:7em;margin-inline-start:-7.5em;color:var(--mute);font-size:13px}.stack td:empty{display:none}}
"""
JS = """<script>{const lab=()=>{for(const c of document.querySelectorAll('.stack td:not([data-l])')){let i=0,p=c;while(p=p.previousElementSibling)i+=p.colSpan;c.dataset.l=c.closest('table').rows[0].cells[i]?.textContent||''}};lab();const mo=new MutationObserver(lab);mo.observe(document.body,{childList:true,subtree:true})}</script>"""


def page(title, sub, body, up=""):
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><header><span class="tab">종가베팅 봇 알림장</span><h1>{E(title)}</h1><p class="sub">{sub}</p>
{f'<nav class="scroll">{up}</nav>' if up else ''}</header><main>{body}
<footer>매일 15:10·19:00 알림 뒤 자동으로 새로 만들어집니다. 수익률은 비용 0.35%를 뺀 값, 모의 기록은 실제 매매가 아닙니다.</footer></main>{JS}</body></html>"""


def day_page(d, t, fm, lead, prev_d, next_d):
    ms = messages(d)
    td = t[t["판 날"].str.replace("-", "") == d] if len(t) else t
    nav = '<a href="../index.html">처음</a>' + f'<a href="../w/{monday(d)}.html">이번 주</a>'
    nav += (f'<a href="{prev_d}.html">← {fmt_d(prev_d)}</a>' if prev_d else "") + (f'<a href="{next_d}.html">{fmt_d(next_d)} →</a>' if next_d else "")
    body = "<h2>보낸 알림</h2>" + ("".join(msg_html(m) for m in ms) if ms else '<p class="empty">이날 저장된 알림 원문 없음 (11/23부터 저장)</p>')
    body += "<h2>오늘의 대장주</h2>" + leaders_block(lead, d)
    body += "<h2>아버지 방식 모의매매</h2>" + father_block(fm, [d])
    body += "<h2>이날 끝난 매매</h2>" + trades_table(td)
    return page(fmt_d(d) + " 알림", f"{len(ms)}개 알림", body, nav)


def week_page(mon, days, t, fm, lead):
    wk = [d for d in days if monday(d) == mon]
    end = (dt.datetime.strptime(mon, "%Y%m%d") + dt.timedelta(days=4)).strftime("%Y%m%d")
    tw = t[(t["판 날"].str.replace("-", "") >= mon) & (t["판 날"].str.replace("-", "") <= end)] if len(t) else t
    body = "<h2>매매법별 이번 주 성적</h2>" + strat_table(tw)
    lw = lead[(lead.date >= mon) & (lead.date <= end)] if len(lead) else lead
    body += "<h2>대장주는 다음날도 올랐나</h2>"
    if len(lw):
        nc = pd.to_numeric(lw.get("next_close"), errors="coerce").dropna() if "next_close" in lw else pd.Series(dtype=float)
        if len(nc):
            body += f'<p class="kpi">다음날 결과가 나온 {len(nc)}종목 중 {int((nc > 0).sum())}종목 상승 · 다음날 종가 평균 {num(nc.mean(), 1)}</p>'
        rows = [[fmt_d(r.date)[:-3], E(r.name), num(r.ret, 1), num(getattr(r, "next_open", None), 1), num(getattr(r, "next_close", None), 1), E(r.reason)]
                for r in lw.sort_values("date").itertuples()]
        body += table(["날짜", "종목", "그날", "다음날 시가", "다음날 종가", "오른 이유 후보"], rows, "stack", right=(2, 3, 4))
    else:
        body += '<p class="empty">기록 없음</p>'
    body += "<h2>아버지 방식 모의매매</h2>" + father_block(fm, [d for d in wk])
    body += "<h2>이번 주 끝난 매매</h2>" + trades_table(tw)
    body += "<h2>날짜별 알림</h2><ul class=\"list\">" + "".join(f'<li><a href="../d/{d}.html">{fmt_d(d)}</a></li>' for d in sorted(wk)) + "</ul>"
    x = dt.datetime.strptime(mon, "%Y%m%d")
    return page(f"{x.month}월 {x.day}일 주간 복기", f"{fmt_d(mon)} ~ {fmt_d(end)}", body, '<a href="../index.html">처음</a>')


def index_page(days, t, s, h, fm, lead):
    latest = days[0] if days else None
    k = []
    if len(fm):
        n, w, a = stat(fm.ret); k.append((num(a), f"아버지 방식 모의 평균 ({n}건, 승률 {w:.0f}%)"))
    cb = t[(t.매매법 == "종가베팅") & (t.구분 != "쉰 날 후보(참고)")] if len(t) else t
    if len(cb):
        n, w, a = stat(cb["수익률(%)"]); k.append((num(a), f"종가베팅 기록 평균 ({n}건)"))
    if len(lead) and latest:
        top = lead[lead.date == lead.date.max()].head(1)
        if len(top):
            k.append((E(top.name.iloc[0]), f"최근 대장주 1등 ({fmt_d(top.date.iloc[0])[:-3]}, {float(top.ret.iloc[0]):+.1f}%)"))
    body = '<div class="kpis">' + "".join(f"<div><b>{a}</b><span>{b}</span></div>" for a, b in k) + "</div>" if k else ""
    if latest:
        ms = messages(latest)
        body += f'<h2>최근 알림 · {fmt_d(latest)}</h2>' + ("".join(msg_html(m) for m in ms[-6:]) if ms else '<p class="empty">저장된 알림 원문 없음 (11/23부터 저장)</p>')
        body += f'<p><a href="d/{latest}.html">이날 전체 보기 →</a></p>'
    body += "<h2>매매법별 누적 성적</h2>" + strat_table(t)
    if len(h):
        rows = [[E(r["매매법"]), E(r["종목"]), E(r["시작일"]), E(r["상태"]), f'{float(r["평단"]):,.0f}' if r["평단"] == r["평단"] else "–",
                 num(r.get("수익률(%)"))] for r in h.to_dict("records")]
        body += "<h2>지금 진행 중</h2>" + table(["매매법", "종목", "시작일", "상태", "평단", "수익률"], rows, "stack", right=(4, 5))
    weeks = sorted({monday(d) for d in days}, reverse=True)
    body += "<h2>주별 복기</h2><ul class=\"list\">" + "".join(f'<li><a href="w/{m}.html">{fmt_d(m)[:-3]} 주</a></li>' for m in weeks) + "</ul>"
    body += "<h2>일별 알림</h2><ul class=\"list\">" + "".join(f'<li><a href="d/{d}.html">{fmt_d(d)}</a></li>' for d in days) + "</ul>"
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%m/%d %H:%M")
    return page("오늘의 알림장", f"마지막 갱신 {now}", body)


def main():
    t, s, h, fm, lead = load()
    days = all_dates(t, fm, lead)
    for sub in ("d", "w"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    for i, d in enumerate(days):
        nxt = days[i - 1] if i > 0 else None
        prv = days[i + 1] if i + 1 < len(days) else None
        open(os.path.join(OUT, "d", f"{d}.html"), "w", encoding="utf-8").write(day_page(d, t, fm, lead, prv, nxt))
    for m in sorted({monday(d) for d in days}):
        open(os.path.join(OUT, "w", f"{m}.html"), "w", encoding="utf-8").write(week_page(m, days, t, fm, lead))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(index_page(days, t, s, h, fm, lead))
    print(f"페이지 만듦: 일별 {len(days)}, 주별 {len({monday(d) for d in days})} → {OUT}")


if __name__ == "__main__":
    main()
