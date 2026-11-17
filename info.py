"""공시·일정·테마 정보 (DART 공시 필터 / 일정 캘린더 / 테마·대장주)

검증 근거: 프로젝트 문서 'DART-공시-일정-테마-검증-2026-11'
- 중기(CAN SLIM): CB·BW·EB 발행(또는 자기CB 매도) 1년 이내 종목은 제외 → 앞뒤 기간 모두 확인됨
- 그 밖의 공시는 '경고' 표시만 (유상증자, 전환청구, 조회공시, 최대주주 변경, 대주주 매도, 횡령·불성실·관리)
- 자사주 매입은 '좋음' 표시
- 일정(FOMC·CPI·옵션만기)은 성적 차이가 확실하지 않아 표시만
- 종가베팅: 같은 테마 대장이 상한가인 2등주를 먼저 고름 (11년 신호당 +1.65%, 일반 +0.2%)

DART 키는 GitHub Secrets의 DART_KEY에서만 읽습니다.
"""
import os, io, re, json, html, zipfile, datetime as dt
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
KEY = os.environ.get("DART_KEY")
S = md.S

# ---------- 일정 ----------
FOMC = ["20261209", "20270127", "20270317", "20270428", "20270609", "20270728", "20270915", "20271027", "20271117"]  # 발표일(미국 날짜) = 그날 종가베팅이 밤사이 맞는 날
CPI = ["20261210", "20270113", "20270211", "20270310", "20270413", "20270512", "20270610", "20270714", "20270811",
       "20270914", "20271014", "20271110", "20271210"]  # 한국 시간 그날 밤 21:30~22:30 발표


def option_expiry(y, m):
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(3 - d.weekday()) % 7 + 7)   # 둘째 목요일 (휴장이면 전 거래일: 직접 확인)
    return d.strftime("%Y%m%d")


def calendar_note(day=None):
    day = day or md.today()
    y, m = int(day[:4]), int(day[4:6])
    out = []
    if day in FOMC:
        out.append("🏦 오늘 밤(새벽 3~4시) FOMC 금리 발표")
    if day in CPI:
        out.append("📈 오늘 밤 미국 소비자물가(CPI) 발표")
    ox = option_expiry(y, m)
    if day == ox:
        out.append("📅 오늘 옵션 만기일" + (" (분기 동시만기)" if m in (3, 6, 9, 12) else ""))
    # 다가오는 일정 (7일 안)
    soon = []
    d0 = dt.datetime.strptime(day, "%Y%m%d")
    for nm, L in [("FOMC", FOMC), ("CPI", CPI), ("옵션만기", [option_expiry(y, m), option_expiry(y + (m == 12), m % 12 + 1)])]:
        for x in L:
            gap = (dt.datetime.strptime(x, "%Y%m%d") - d0).days
            if 0 < gap <= 7:
                soon.append(f"{nm} {x[4:6]}/{x[6:]}")
    if soon:
        out.append("🗓 이번 주 일정: " + ", ".join(soon))
    if out:
        out.append("   (과거 검증상 이런 날도 종가베팅 성적 차이는 뚜렷하지 않음 → 참고만)")
    return "\n".join(out)


# ---------- 저장해 두고 일주일 쓰는 목록 ----------
# GitHub 실행은 매번 파일을 새로 받아 '수정 시각'을 믿을 수 없어서, 저장한 날짜를 파일 안에 적어 둠
def _cache_get(name, days=7):
    f = f"{REC}/{name}"
    try:
        j = json.load(open(f))
        if (dt.datetime.strptime(md.today(), "%Y%m%d") - dt.datetime.strptime(j["saved"], "%Y%m%d")).days < days:
            return j["data"]
    except Exception:
        pass
    return None


def _cache_put(name, data):
    os.makedirs(REC, exist_ok=True)
    json.dump(dict(saved=md.today(), data=data), open(f"{REC}/{name}", "w"), ensure_ascii=False)


_MEMO = {}


# ---------- DART ----------
def _corpmap():
    if "corp" in _MEMO:
        return _MEMO["corp"]
    m = _cache_get("corpmap.json", 30)
    if m is None:
        z = zipfile.ZipFile(io.BytesIO(S.get(f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={KEY}", timeout=120).content))
        xml = z.read(z.namelist()[0]).decode("utf-8")
        m = {s: c for c, s in re.findall(r"<corp_code>(\d+)</corp_code>\s*<corp_name>[^<]*</corp_name>\s*(?:<corp_eng_name>[^<]*</corp_eng_name>\s*)?<stock_code>(\d{6})</stock_code>", xml)}
        _cache_put("corpmap.json", m)
    _MEMO["corp"] = m
    return m


def _days_ago(d8, day):
    return (dt.datetime.strptime(day, "%Y%m%d") - dt.datetime.strptime(d8, "%Y%m%d")).days


def dart_check(code, day=None):
    """종목의 최근 400일 공시를 보고 판정.
    반환: dict(block=중기 제외 여부, warn=[경고], good=[좋음])"""
    day = day or md.today()
    res = dict(block=False, warn=[], good=[])
    if not KEY:
        res["warn"].append("DART 키 없음(공시 확인 안 함)")
        return res
    try:
        corp = _corpmap().get(code)
        if not corp:
            return res
        bg = (dt.datetime.strptime(day, "%Y%m%d") - dt.timedelta(days=400)).strftime("%Y%m%d")
        items, page = [], 1
        while page <= 5:
            r = S.get("https://opendart.fss.or.kr/api/list.json", params=dict(
                crtfc_key=KEY, corp_code=corp, bgn_de=bg, end_de=day, page_count=100, page_no=page), timeout=30).json()
            items += r.get("list", [])
            if page >= (r.get("total_page") or 1):
                break
            page += 1
        el = S.get("https://opendart.fss.or.kr/api/elestock.json", params=dict(crtfc_key=KEY, corp_code=corp), timeout=30).json().get("list", [])
    except Exception as e:
        res["warn"].append(f"공시 확인 실패({e.__class__.__name__})")
        return res

    seen = set()
    for x in items:
        nm = x["report_nm"]
        if nm.startswith("["):          # 정정·첨부는 건너뜀
            continue
        ago = _days_ago(x["rcept_dt"], day)
        def add(lst, text, limit):
            if ago <= limit and text not in seen:
                seen.add(text); lst.append(f"{text} ({x['rcept_dt'][4:6]}/{x['rcept_dt'][6:]})")
        if re.search("전환사채권발행결정|신주인수권부사채권발행결정|교환사채권발행결정|자기전환사채매도결정", nm) and ago <= 365:
            res["block"] = True
            add(res["warn"], "CB·BW·EB 발행(1년 내)", 365)
        elif "유상증자결정" in nm:
            add(res["warn"], "유상증자", 90)
        elif "전환청구권행사" in nm:
            add(res["warn"], "전환청구(물량 출회)", 90)
        elif "조회공시요구" in nm:
            add(res["warn"], "조회공시 요구", 90)
        elif nm.startswith("최대주주변경"):
            add(res["warn"], "최대주주 변경", 90)
        elif re.search("횡령|배임|불성실공시법인지정|관리종목|상장적격성|감사의견|회생절차", nm):
            add(res["warn"], "⛔ " + re.sub(r"\(.*", "", nm), 365)
        elif re.search("자기주식취득결정|자기주식취득신탁계약체결", nm):
            add(res["good"], "자사주 매입", 90)
    # 대주주·등기임원 매도 (지분 0.5%p 이상 감소)
    for x in el:
        try:
            rate = float(str(x.get("sp_stock_lmp_irds_rate", "0")).replace(",", ""))
        except ValueError:
            continue
        big = re.search("주요주주|최대", x.get("isu_main_shrholdr", "")) or x.get("isu_exctv_rgist_at") == "등기임원"
        d8 = x["rcept_dt"].replace("-", "")
        if big and rate <= -0.5 and _days_ago(d8, day) <= 90 and "대주주 매도" not in seen:
            seen.add("대주주 매도"); res["warn"].append(f"대주주·임원 매도 {rate:.1f}%p ({d8[4:6]}/{d8[6:]})")
    return res


def dart_line(r):
    """dart_check() 결과를 한 줄로"""
    t = []
    if r["warn"]:
        t.append("⚠️ 공시: " + ", ".join(r["warn"]))
    if r["good"]:
        t.append("👍 " + ", ".join(r["good"]))
    return "   " + " | ".join(t) if t else "   공시: 특이사항 없음"


def dart_safe_line(code):
    """실패해도 알림이 멈추지 않게 감싼 한 줄"""
    try:
        return dart_line(dart_check(code))
    except Exception as e:
        return f"   공시: 확인 실패({e.__class__.__name__})"


# ---------- 테마 ----------
def _themes():
    if "themes" in _MEMO:
        return _MEMO["themes"]
    out = _cache_get("themes.json", 7)
    if out is None:
        groups = []
        for p in range(1, 5):
            g = S.get(f"https://m.stock.naver.com/api/stocks/theme?page={p}&pageSize=100", timeout=20).json().get("groups", [])
            groups += g
            if len(g) < 100:
                break
        out = []
        for t in groups:
            codes, p = [], 1
            while True:
                st = S.get(f"https://m.stock.naver.com/api/stocks/theme/{t['no']}?page={p}&pageSize=100", timeout=20).json().get("stocks", [])
                codes += [s["itemCode"] for s in st]
                if len(st) < 100:
                    break
                p += 1
            out.append(dict(no=t["no"], name=t["name"], codes=codes))
        _cache_put("themes.json", out)
    _MEMO["themes"] = out
    return out


def theme_info(code, all_df):
    """all_df: md.all_stocks() 결과 (오늘 등락률·거래대금).
    반환: dict(second_to_limit=대장 상한가 테마의 2등주 여부, text=표시 문구)"""
    try:
        T = _themes()
    except Exception:
        return dict(second_to_limit=False, text="   테마: 못 받음")
    now = all_df.drop_duplicates("code").set_index("code")
    best, second = None, False
    for t in T:
        if code not in t["codes"]:
            continue
        x = now.reindex([c for c in t["codes"] if c in now.index]).dropna(subset=["ret"])
        if len(x) < 3 or code not in x.index:
            continue
        x = x.sort_values("ret", ascending=False)
        rank = list(x.index).index(code) + 1
        lead = x.iloc[0]
        up = int((x.ret >= 5).sum())
        if rank > 1 and lead.ret >= 29:
            second = True
        cand = (rank, -up, t["name"], lead["name"], lead.ret, len(x), up)
        if best is None or cand < best:
            best = cand
    if best is None:
        return dict(second_to_limit=False, text="   테마: 해당 없음")
    rank, _, nm, lname, lret, n, up = best
    txt = f"   테마 '{nm}' {rank}등/{n} (5%↑ {up}종목)"
    if rank > 1:
        txt += f" | 대장 {lname} {lret:+.1f}%"
    if second:
        txt += " ★대장 상한가 테마 2등주"
    return dict(second_to_limit=second, text=txt)


def news_line(code, n=2):
    try:
        r = S.get(f"https://m.stock.naver.com/api/news/stock/{code}?pageSize={n}&page=1", timeout=15).json()
        items = [it for g in r for it in g.get("items", [])][:n]
        return "\n".join(f"   📰 {it['datetime'][8:10]}:{it['datetime'][10:12]} {html.unescape(it['title'])[:40]}" for it in items) or "   📰 오늘 뉴스 없음"
    except Exception:
        return "   📰 뉴스 못 받음"
