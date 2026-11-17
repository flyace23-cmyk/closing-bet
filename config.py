"""종가베팅 봇 설정. 숫자만 바꾸면 규칙이 바뀝니다.

PROFILE = "검증반영"  → 11년 백테스트로 확인한 설정 (기본)
PROFILE = "v2원안"    → 다른 AI가 제안한 주도주 공격형 v2.0 그대로
"""
PROFILE = "검증반영"

PROFILES = {
    "검증반영": dict(
        market_rule="v1",          # 코스피·코스닥 20일선 위 + 코스피 60일선 위
        ret_min=5.0, ret_max=25.0,  # 당일 등락률(%)
        near_high=3.0,             # 고가 대비 몇 % 이내
        value_min=300,             # 당일 거래대금(억)
        vol_mult=2.0,              # 20일 평균 거래량 대비 배수
        need_new_high=False,       # 당일 고가 >= 최근 20일 최고가 x 0.97 (2차 검증에서 하루 2종목 성적을 낮춰 끔)
        need_vwap_afternoon=False, # VWAP 위 + 13시 이후 고가 유지 (표시는 항상 함)
        sort_by="vol_mult",        # 하루 2종목 고르는 순서: vol_mult(거래량배수) / value(거래대금)
        max_picks=2,
        exit_mode="open",          # open: 100% 다음날 시가 / split: 50% 시가 + 50% 아침 감시주문
        leader_weight=0.5,         # 거래대금 1000억+ 단독 대장주 비중 (단타 자금 대비)
    ),
    "v2원안": dict(
        market_rule="v2",          # 코스피 5일선 위 OR 코스닥 5일선 위 OR 코스닥 양봉
        ret_min=7.0, ret_max=25.0,
        near_high=2.5,
        value_min=500,
        vol_mult=2.0,
        need_new_high=True,
        need_vwap_afternoon=True,
        sort_by="value",
        max_picks=2,
        exit_mode="split",
        leader_weight=0.7,
    ),
}
CFG = PROFILES[PROFILE]

# 공통: 쉬는 날 (두 설정 모두 적용)
KOSDAQ_BREAK = -1.5    # 15:10 코스닥 등락률이 이 값 이하면 휴식
NASDAQ_FUT_BREAK = -0.7  # 나스닥 선물 등락률이 이 값 이하면 휴식

# split 모드 아침 감시주문 값
SPLIT = dict(stop=-1.5, target_from_open=6.0, vi=10.0, trail=-2.0, time_stop="09:30")

# 연패 규칙
LOSS_STREAK = 3        # 연속 손실 횟수
REDUCE_DAYS = 2        # 그 뒤 며칠 동안
REDUCE_TO = 0.5        # 투입 금액 비율
