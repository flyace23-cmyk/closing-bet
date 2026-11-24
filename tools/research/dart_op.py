"""연구용 (일회성): 전 종목 분기·연간 영업이익을 DART '다중회사 주요계정'으로 받아 CSV로 저장.
GitHub Actions에서만 실행 (DART_KEY 비밀값 사용). 결과: records/research/dart_op.csv
키 값은 파일·로그에 남기지 않는다.
"""
import os, sys, time, json
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import market_data as md
import info

OUT = os.path.join(ROOT, "records", "research"); os.makedirs(OUT, exist_ok=True)
L = md.all_stocks()
cm = info._corpmap()
codes = list(L.code)
cf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codes.txt")
if os.path.exists(cf):          # 신호가 나온 종목만 (속도)
    codes = [x.strip() for x in open(cf) if x.strip()]
corps = sorted({cm[c] for c in codes if c in cm})
print("종목", len(L), "corp 매핑", len(corps))
rows, log = [], []
done_years = set()
f_all = os.path.join(OUT, "dart_op.csv")
if os.path.exists(f_all):      # 이어받기: 이미 받은 연도는 건너뜀
    old = pd.read_csv(f_all, dtype=str); rows = old.to_dict("records")
    done_years = {int(y) for y in old.bsns_year.unique()} - {2026}
    print("이미 받은 연도", sorted(done_years))
from concurrent.futures import ThreadPoolExecutor, as_completed
B = 25
jobs = [(y, rc, b) for y in range(2015, 2027) if y not in done_years
        for rc in ["11013", "11012", "11014", "11011"] for b in range(0, len(corps), B)]
print("호출 수", len(jobs), flush=True)
def one(job):
    year, rc, b = job; t0 = time.time()
    for t in range(3):
        try:
            j = md.S.get("https://opendart.fss.or.kr/api/fnlttMultiAcnt.json",
                         params=dict(crtfc_key=info.KEY, corp_code=",".join(corps[b:b + B]), bsns_year=str(year), reprt_code=rc),
                         timeout=180).json()
            return job, j, time.time() - t0
        except Exception:
            time.sleep(3)
    return job, None, time.time() - t0
got = {}   # (year, rc, b) -> rows
n = 0
with ThreadPoolExecutor(8) as ex:
    for f in as_completed([ex.submit(one, jb) for jb in jobs]):
        job, j, sec = f.result(); n += 1
        st = (j or {}).get("status")
        log.append(f"{job} {st}")
        print(n, job, st, f"{sec:.0f}s", flush=True)
        if j is None or st not in ("000", "013"):
            continue
        got[job] = [{k: r.get(k) for k in ["stock_code", "corp_code", "bsns_year", "reprt_code", "rcept_no", "fs_div",
                                           "sj_div", "account_nm", "thstrm_amount", "thstrm_add_amount",
                                           "frmtrm_amount", "frmtrm_add_amount"]}
                    for r in (j.get("list") or []) if r.get("account_nm", "").replace(" ", "") in ("영업이익", "영업이익(손실)", "영업손실")]
        # 연도 단위로 다 받았으면 저장 (중간에 끊겨도 이어받기 가능)
        y = job[0]
        if all((y, rc, b) in got for rc in ["11013", "11012", "11014", "11011"] for b in range(0, len(corps), B)):
            rows += [r for (yy, _, _), rs in got.items() if yy == y for r in rs]
            for k in [k for k in got if k[0] == y]: del got[k]
            pd.DataFrame(rows).to_csv(f_all, index=False); print("저장", y, len(rows), flush=True)
pd.DataFrame(rows).to_csv(os.path.join(OUT, "dart_op.csv"), index=False)
open(os.path.join(OUT, "dart_op_log.txt"), "w").write("\n".join(log))
print("완료", len(rows))
