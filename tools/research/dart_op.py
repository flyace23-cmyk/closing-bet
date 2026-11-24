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
corps = sorted({cm[c] for c in L.code if c in cm})
print("종목", len(L), "corp 매핑", len(corps))
rows, log = [], []
done_years = set()
f_all = os.path.join(OUT, "dart_op.csv")
if os.path.exists(f_all):      # 이어받기: 이미 받은 연도는 건너뜀
    old = pd.read_csv(f_all, dtype=str); rows = old.to_dict("records")
    done_years = {int(y) for y in old.bsns_year.unique()} - {2026}
    print("이미 받은 연도", sorted(done_years))
for year in range(2015, 2027):
    if year in done_years:
        continue
    for rc in ["11013", "11012", "11014", "11011"]:
        for b in range(0, len(corps), 100):
            batch = corps[b:b + 100]
            for t in range(4):
                try:
                    j = md.S.get("https://opendart.fss.or.kr/api/fnlttMultiAcnt.json",
                                 params=dict(crtfc_key=info.KEY, corp_code=",".join(batch), bsns_year=str(year), reprt_code=rc),
                                 timeout=30).json()
                    break
                except Exception:
                    time.sleep(3); j = {}
            st = j.get("status"); log.append(f"{year} {rc} {b} {st}")
            if st == "020":
                print("호출 한도 초과, 중단"); break
            for r in j.get("list", []) or []:
                if r.get("account_nm", "").replace(" ", "") in ("영업이익", "영업이익(손실)", "영업손실"):
                    rows.append({k: r.get(k) for k in ["stock_code", "corp_code", "bsns_year", "reprt_code", "rcept_no", "fs_div",
                                                       "sj_div", "account_nm", "thstrm_amount", "thstrm_add_amount",
                                                       "frmtrm_amount", "frmtrm_add_amount"]})
            time.sleep(0.3)
    print(year, "누적 행", len(rows), flush=True)
    pd.DataFrame(rows).to_csv(f_all, index=False)   # 연도마다 저장
pd.DataFrame(rows).to_csv(os.path.join(OUT, "dart_op.csv"), index=False)
open(os.path.join(OUT, "dart_op_log.txt"), "w").write("\n".join(log))
print("완료", len(rows))
