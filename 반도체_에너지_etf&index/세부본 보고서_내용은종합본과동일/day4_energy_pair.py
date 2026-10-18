#%% 0. 안내 + 실행 플래그
# 먼저 day3_index_engine.py 를 보고 오세요. 이미 DB에 데이터가 있으면 여기서부터 진행하세요.
# 실행 순서: 국내 주식 데이터 수집.py -> 00_collect_futures_tv.py -> day1_data_check_and_hypothesis.py
#            -> day2_universe_and_cap.py -> day3_index_engine.py -> 이 파일
#
# 환경: conda activate ta_env   (Anaconda Prompt)
#   Spyder: Tools > Preferences > Python interpreter > Use the following
#           Python interpreter 에서 ta_env 의 python.exe 선택 후 Spyder 재시작
#   패키지가 없으면 ta_env 를 켠 상태에서:
#   pip install pandas numpy sqlalchemy pymysql matplotlib requests
#
# 비밀번호와 API 키는 코드에 쓰지 않고 환경변수에서 읽는다.
#   setx DB_PW "DB비밀번호"      setx ECOS_KEY "ECOS인증키"     (설정 후 Spyder 재시작)
import os
import numpy as np
import pandas as pd
import requests
from urllib.parse import quote_plus
from sqlalchemy import create_engine

RUN_DOWNLOAD = True     # True: CD91 금리를 ECOS 에서 받아 cd91_rate 테이블에 저장
CD_CSV       = None     # API 키가 없을 때: ECOS 에서 받은 CSV 경로 (열: 날짜, 금리)
ECOS_STAT    = None     # None 이면 통계표 목록에서 '시장금리 ... 일별' 을 찾는다. 알면 코드를 직접 적는다

DB_USER = os.environ.get('DB_USER', 'root')
DB_PW   = os.environ['DB_PW']
engine  = create_engine(
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PW)}@127.0.0.1:3306/stock_db")

ECOS_BASE = 'https://ecos.bok.or.kr/api'

def ecos_get(path):
    # 에러 메시지에 키가 섞여 나오지 않도록 요청 실패는 URL 없이 알린다
    try:
        return requests.get(f"{ECOS_BASE}/{path}", timeout=60).json()
    except Exception as e:
        raise RuntimeError(f'ECOS 요청 실패: {type(e).__name__}')

def find_stat_code(key):
    # 통계표 목록에서 '시장금리' 가 들어간 표를 찾는다
    j = ecos_get(f"StatisticTableList/{key}/json/kr/1/2000/")
    if 'StatisticTableList' not in j:
        raise RuntimeError(f'통계표 목록 조회 실패: {j}')
    tb = pd.DataFrame(j['StatisticTableList']['row'])
    print('통계표 목록 컬럼:', tb.columns.tolist())
    hit = tb[tb['STAT_NAME'].str.contains('시장금리')]
    print(hit.to_string())
    day = hit[hit['STAT_NAME'].str.contains('일별')]
    if len(day) != 1:
        raise RuntimeError('시장금리(일별) 통계표가 하나로 정해지지 않음: 위 출력을 보고 '
                           'ECOS_STAT 에 STAT_CODE 를 직접 적으세요')
    return day['STAT_CODE'].iloc[0]

def fetch_cd91(start='20211001', end=None):
    key = os.environ['ECOS_KEY']
    end = end or pd.Timestamp.today().strftime('%Y%m%d')
    stat = ECOS_STAT or find_stat_code(key)
    print('사용할 통계표 코드:', stat)
    # 항목 목록에서 CD(91일) 코드를 이름으로 찾는다
    j = ecos_get(f"StatisticItemList/{key}/json/kr/1/200/{stat}")
    if 'StatisticItemList' not in j:
        raise RuntimeError(f'항목 목록 조회 실패: {j}')
    items = pd.DataFrame(j['StatisticItemList']['row'])
    print('항목 컬럼:', items.columns.tolist())
    hit = items[items['ITEM_NAME'].str.contains('CD') & items['ITEM_NAME'].str.contains('91')]
    print(hit[['ITEM_CODE', 'ITEM_NAME']])
    if len(hit) != 1:
        print(items[['ITEM_CODE', 'ITEM_NAME']].to_string())
        raise RuntimeError('CD(91일) 항목이 하나로 정해지지 않음: 위 출력을 보고 ITEM_CODE 를 직접 지정하세요')
    code = hit['ITEM_CODE'].iloc[0]
    cycle = 'D'
    if 'CYCLE' in items.columns:
        cycle = items['CYCLE'].iloc[0]
    print('주기:', cycle, '/ 항목코드:', code)
    j = ecos_get(f"StatisticSearch/{key}/json/kr/1/10000/{stat}/{cycle}/{start}/{end}/{code}")
    if 'StatisticSearch' not in j:
        raise RuntimeError(f'시계열 조회 실패: {j}')
    df = pd.DataFrame(j['StatisticSearch']['row'])
    out = pd.DataFrame({'날짜': pd.to_datetime(df['TIME'], format='%Y%m%d'),
                        '금리': df['DATA_VALUE'].astype(float)})
    return out.sort_values('날짜')

if RUN_DOWNLOAD:
    cd = fetch_cd91()
    cd.to_sql('cd91_rate', engine, if_exists='replace', index=False)
    print('cd91_rate 저장:', len(cd), '행', cd['날짜'].min().date(), '~', cd['날짜'].max().date())
elif CD_CSV:
    cd = pd.read_csv(CD_CSV, parse_dates=['날짜'])[['날짜', '금리']]
    cd.to_sql('cd91_rate', engine, if_exists='replace', index=False)
    print('cd91_rate 저장(CSV):', len(cd), '행')

NEED_TABLES = ['idx_level', 'tv_futures_price', 'cd91_rate']
have = pd.read_sql("SHOW TABLES", engine).iloc[:, 0].tolist()
missing = [t for t in NEED_TABLES if t not in have]
if missing:
    raise RuntimeError(f"DB에 없는 테이블: {missing}\n"
                       f"idx_level 은 day3 파일, tv_futures_price 는 00_collect_futures_tv.py 를 먼저 실행하고, "
                       f"cd91_rate 는 RUN_DOWNLOAD = True (또는 CD_CSV) 로 만드세요.")
print('필요 테이블 확인 완료:', NEED_TABLES)

#%% 1. 파라미터 (결과를 보기 전에 고정하는 값들)
BASE_VARIANT  = 'E_quota_buffer'          # Day 3 에서 정한 주 사양
ENERGY_W      = [0.0, 0.1, 0.2, 0.3]      # 에너지 선물 바스켓 목표 비중
SLEEVES       = {'CL': {'CL': 1.0},                 # 원유만
                 'NG': {'NG': 1.0},                 # 천연가스만
                 'CLNG': {'CL': 0.5, 'NG': 0.5}}    # 원유 + 천연가스 (일 단위 50:50)
ROLL_RULES    = ['R0', 'R1', 'R2', 'R3']
#   R0 롤 보정 없음 (1! 가격을 그대로 이어붙임, 롤 점프가 수익률에 섞이는 비교용)
#   R1 근월물 보유, 만기 전 차월물로 롤
#   R2 차월물 보유
#   R3 어제 곡선이 백워데이션이면 근월물, 콘탱고면 차월물
MAIN_SLEEVE   = 'CLNG'
MAIN_ROLL     = 'R1'
COLLATERAL    = True      # 선물을 전액 현금 담보로 보유한다고 보고 CD91 이자를 에너지 쪽에 더한다
FX_UNHEDGED   = True      # 선물(달러) 수익률에 원달러 환율 변동을 그대로 반영
SPREAD_TH     = 0.003     # 근월·차월 가격 차이가 이보다 작으면 롤 여부를 가리지 않는다
POLICY_TEST_W = [0.1, 0.2, 0.3]           # 월 리밸런싱 vs 방치 비교에 쓸 비중


#%% 2. 데이터 적재
lv = pd.read_sql(f"SELECT 날짜, 지수 FROM idx_level WHERE variant = '{BASE_VARIANT}'",
                 engine, parse_dates=['날짜']).set_index('날짜')['지수'].sort_index()
kr_idx = lv.index
r_eq = lv.pct_change().dropna()           # 주식 지수 일수익률 (가격지수)

fut = pd.read_sql("""
SELECT Date, Symbol, Close FROM tv_futures_price
WHERE Symbol IN ('CL1!', 'CL2!', 'NG1!', 'NG2!', 'USDKRW')
""", engine, parse_dates=['Date'])
fut = fut.pivot(index='Date', columns='Symbol', values='Close').sort_index()

cd = pd.read_sql("SELECT 날짜, 금리 FROM cd91_rate", engine, parse_dates=['날짜']).set_index('날짜')['금리'].sort_index()
cd_k = cd.reindex(kr_idx.union(cd.index)).ffill().reindex(kr_idx)      # 휴장일은 직전 금리
days = pd.Series(kr_idx, index=kr_idx).diff().dt.days.fillna(0)
cd_daily = cd_k / 100 * days / 365                                      # 달력일 기준 일 이자율

print('지수 기간:', kr_idx[0].date(), '~', kr_idx[-1].date())
print('선물 기간:', fut.index.min().date(), '~', fut.index.max().date(), '/ 열:', fut.columns.tolist())
print('CD91 기간:', cd.index.min().date(), '~', cd.index.max().date(), '/ 최근 값:', cd.iloc[-1])

#%% 2-2. 선물/환율 날짜 보정 (+1일)
# TradingView 선물, 환율 일봉은 세션 시작일(전날 저녁) 날짜로 찍혀 있어서
# 일~목으로 들어온다. 실제 마감일(월~금)로 하루 뒤로 민다.
# 이미 보정한 상태면(금요일 봉이 있으면) 다시 밀지 않는다.
dow = pd.Series(fut.index.dayofweek)
n_sun = int((dow == 6).sum())
n_fri = int((dow == 4).sum())

if n_sun > 0 and n_fri == 0:
    fut = fut.copy()
    fut.index = fut.index + pd.Timedelta(days=1)
    print("날짜 +1일 보정 완료")
else:
    print("보정 안 함 (이미 보정했거나 패턴이 다름): 일요일", n_sun, "금요일", n_fri)

# 확인: 요일별 봉 수 (월~금만 있어야 함)
print(pd.Series(fut.index.dayofweek).value_counts().sort_index())

#%% 3. 롤 감지 (만기 달력 창 방식) + 진단
# 이전 방식: 달마다 '수익률 차이가 가장 큰 날' 하나를 롤로 봄 -> 만기와 무관한 노이즈 날도 잡힘
# 바꾼 방식: 계약 만기일 주변 창 안에서만 롤 후보를 찾는다.
#   CL: 만기 = (월 25일, 영업일 아니면 그 직전 영업일) 기준 3영업일 전
#   NG: 만기 = 인도월 1일 기준 3영업일 전
# 휴일은 미국 연방공휴일로 근사 (NYMEX 휴일과 완전히 같지는 않음, 확인 안 됨)
from pandas.tseries.offsets import CustomBusinessDay
from pandas.tseries.holiday import USFederalHolidayCalendar

bday = CustomBusinessDay(calendar=USFederalHolidayCalendar())
WIN_BEFORE, WIN_AFTER = 3, 6   # 만기일 기준 창 (달력일)

def expiry_dates(kind, start, end):
    # kind: 'CL' 또는 'NG', 각 달에 만기를 맞는 계약의 만기일을 만든다
    out = []
    for p in pd.period_range(start, end, freq='M'):
        if kind == 'CL':
            d25  = pd.Timestamp(p.year, p.month, 25)
            base = bday.rollback(d25)                       # 25일이 휴일이면 직전 영업일
            e    = bday.rollback(base - pd.Timedelta(days=1)) - 2 * bday
        else:
            nxt  = (p + 1).to_timestamp()                   # 다음 달 1일 = 인도월 1일
            e    = bday.rollback(nxt - pd.Timedelta(days=1)) - 2 * bday
        out.append(e)
    return out

def infer_kind(f1, kind=None):
    if kind is not None:
        return kind
    nm = str(getattr(f1, 'name', ''))
    if 'NG' in nm: return 'NG'
    if 'CL' in nm: return 'CL'
    return 'NG' if f1.median() < 20 else 'CL'   # 이름이 없으면 가격대로 추정 (NG 약 2~9, CL 약 40~120)

def roll_adjusted_returns(f1, f2, spread_th=SPREAD_TH, kind=None):
    kind = infer_kind(f1, kind)
    p1, p2 = f1.shift(1), f2.shift(1)
    d_same = f1 / p1 - 1            # 전일 근월물 -> 오늘 근월물 (롤 안 한 수익률)
    d_roll = f1 / p2 - 1            # 전일 차월물 -> 오늘 근월물 (롤 한 수익률)
    gap    = (p2 / p1 - 1).abs()    # 전일 두 계약 가격 차이
    score  = d_same.abs() - d_roll.abs()
    cand   = score.where(gap > spread_th)

    is_roll = pd.Series(False, index=f1.index)
    for e in expiry_dates(kind, f1.index[0], f1.index[-1]):
        lo, hi = e - pd.Timedelta(days=WIN_BEFORE), e + pd.Timedelta(days=WIN_AFTER)
        w = cand[(cand.index >= lo) & (cand.index <= hi)].dropna()
        w = w[w > 0]
        if len(w) > 0:
            is_roll.loc[w.idxmax()] = True     # 창 안에서 한 번만

    r0 = d_same
    r1 = d_same.where(~is_roll, d_roll)
    r2 = (f2 / p2 - 1).where(~is_roll, d_roll)
    r3 = r1.where(p1 > p2, r2)
    out = pd.DataFrame({'R0': r0, 'R1': r1, 'R2': r2, 'R3': r3}).fillna(0.0)
    return out, is_roll

# ---- 진단 ----
# (a) 토/일 날짜로 찍힌 봉이 있는지: 있으면 날짜 라벨이 하루 밀렸을 수 있음
for nm in ['CL1!', 'NG1!']:
    s = fut[nm].dropna()
    print(f"{nm} 토/일 봉 수:", int((s.index.dayofweek >= 5).sum()), "/ 전체", len(s))

# (b) 만기별 표: 만기일, 감지일, 요일, 롤 안 한 수익률, 롤 한 수익률, 부호 있는 가격차
for nm1, nm2, kind in [('CL1!', 'CL2!', 'CL'), ('NG1!', 'NG2!', 'NG')]:
    f1, f2 = fut[nm1].dropna(), fut[nm2].dropna()
    f2 = f2.reindex(f1.index)
    rr, isr = roll_adjusted_returns(f1, f2, kind=kind)
    p1, p2 = f1.shift(1), f2.shift(1)
    rows = []
    for e in expiry_dates(kind, f1.index[0], f1.index[-1])[-14:]:
        lo, hi = e - pd.Timedelta(days=WIN_BEFORE), e + pd.Timedelta(days=WIN_AFTER)
        d = isr[(isr.index >= lo) & (isr.index <= hi) & isr].index
        if len(d) == 0:
            rows.append([e.date(), None, None, None, None, None]); continue
        t = d[0]
        rows.append([e.date(), t.date(), t.day_name()[:3],
                     round(f1[t] / p1[t] - 1, 4), round(f1[t] / p2[t] - 1, 4),
                     round(p2[t] / p1[t] - 1, 4)])
    print(f"\n[{kind}] 최근 만기별 롤 진단")
    print(pd.DataFrame(rows, columns=['만기','감지일','요일','d_same','d_roll','gap(부호)']).to_string(index=False))
    print(f"{kind} 감지 횟수(연도별):", isr.groupby(isr.index.year).sum().to_dict())
    # 롤 안 한 수익률이 평소 일변동 대비 얼마나 튀는지 (보정 안 된 시리즈면 롤일에 크게 튐)
    print(f"{kind} 롤일 |d_same| 평균 {rr.loc[isr,'R0'].abs().mean():.4f} / 비롤일 {rr.loc[~isr,'R0'].abs().mean():.4f}")


#%% 4. 에너지 바스켓 수익률 (원화 환산, 담보 이자 포함) + 결합 함수 + 지표
def to_krw_return(r_usd):
    # 선물 수익률을 지수화한 뒤 한국 거래일에 맞추고, 환율을 곱해 원화 가치로 바꾼다
    lvl = (1 + r_usd).cumprod()
    lvl_k = lvl.reindex(lvl.index.union(kr_idx)).ffill().reindex(kr_idx)
    if FX_UNHEDGED:
        fx = fut['USDKRW'].reindex(fut.index.union(kr_idx)).ffill().reindex(kr_idx)
        lvl_k = lvl_k * fx
    return lvl_k.pct_change()

def sleeve_returns(sleeve, rule):
    parts = {sym: to_krw_return(ROLLS[sym][0][rule]) for sym in ('CL', 'NG')}
    r = sum(wt * parts[s] for s, wt in SLEEVES[sleeve].items())
    if COLLATERAL:
        r = r + cd_daily
    return r.reindex(r_eq.index).fillna(0.0)

# 주식 지수 + 에너지 바스켓을 목표 비중 w 로 섞는다.
#   monthly: 매월 마지막 거래일 종가에 목표 비중으로 되돌린다
#   hold   : 처음에 한 번 정하고 이후 방치 (비중이 가격에 따라 흘러간다)
def combine(r_eq, r_en, w, policy):
    idx = r_eq.index
    month = idx.to_period('M')
    v_eq, v_en = 1.0 - w, w
    lvl, wen = [], []
    for i in range(len(idx)):
        v_eq *= 1 + r_eq.iloc[i]
        v_en *= 1 + r_en.iloc[i]
        tot = v_eq + v_en
        lvl.append(tot)
        wen.append(v_en / tot)
        last_of_month = (i == len(idx) - 1) or (month[i + 1] != month[i])
        if policy == 'monthly' and last_of_month:
            v_eq, v_en = tot * (1 - w), tot * w
    level = pd.concat([pd.Series([1.0], index=[kr_idx[0]]), pd.Series(lvl, index=idx)])
    return level, pd.Series(wen, index=idx)

# K-Sharpe 근사: CD91 을 뺀 로그 초과수익률의 평균 / 표준편차 (연율화는 252일).
# FnGuide 문서의 정확한 연율화 방식은 확인 안 됨.
def metrics(level, r_ref=None):
    r = level.pct_change().dropna()
    yrs = (level.index[-1] - level.index[0]).days / 365.25
    ex = np.log1p(r) - np.log1p(cd_daily.reindex(r.index).fillna(0))
    out = {
        'CAGR': (level.iloc[-1] / level.iloc[0]) ** (1 / yrs) - 1,
        '연변동성': r.std() * np.sqrt(252),
        'MDD': (level / level.cummax() - 1).min(),
        'K-Sharpe': ex.mean() * 252 / (ex.std() * np.sqrt(252)),
    }
    if r_ref is not None:
        out['추적오차'] = (r - r_ref.reindex(r.index)).std() * np.sqrt(252)
    return pd.Series(out)

# 상관 확인: 에너지 바스켓이 주식 지수와 얼마나 같이 움직였나 (일수익률)
for sl in SLEEVES:
    print(sl, '주식 지수와의 일수익률 상관:', round(r_eq.corr(sleeve_returns(sl, MAIN_ROLL)), 3))


#%% 5. 월 리밸런싱 vs 방치 비교 (판정 규칙은 결과를 보기 전에 정해 둔 것)
# 각 비중 w 에서 K-Sharpe 가 더 높고 MDD 가 더 얕은 쪽이 1승.
# 3번 중 2번 이상 이긴 정책을 쓰고, 아니면 monthly (목표 비중 유지가 상품 정의에 맞음).
r_main = sleeve_returns(MAIN_SLEEVE, MAIN_ROLL)
rows = {}
for w in POLICY_TEST_W:
    for pol in ('monthly', 'hold'):
        lvl, wen = combine(r_eq, r_main, w, pol)
        m = metrics(lvl, r_eq)
        m['에너지비중 평균'] = wen.mean()
        m['에너지비중 최대'] = wen.max()
        rows[(w, pol)] = m
pol_tbl = pd.DataFrame(rows).T
print(pol_tbl.round(3))

wins = {'monthly': 0, 'hold': 0}
for w in POLICY_TEST_W:
    a, b = pol_tbl.loc[(w, 'monthly')], pol_tbl.loc[(w, 'hold')]
    if a['K-Sharpe'] > b['K-Sharpe'] and a['MDD'] >= b['MDD']:
        wins['monthly'] += 1
    elif b['K-Sharpe'] > a['K-Sharpe'] and b['MDD'] >= a['MDD']:
        wins['hold'] += 1
print('승수:', wins)
POLICY = 'hold' if wins['hold'] >= 2 else 'monthly'
print('채택한 정책:', POLICY)


#%% 6. 전체 시나리오 (롤 규칙 x 바스켓 x 에너지 비중), 채택한 정책으로
rows, levels = {}, {}
for rule in ROLL_RULES:
    for sl in SLEEVES:
        r_en = sleeve_returns(sl, rule)
        for w in ENERGY_W:
            lvl, wen = combine(r_eq, r_en, w, POLICY)
            levels[(rule, sl, w)] = lvl
            rows[(rule, sl, w)] = metrics(lvl, r_eq)
grid = pd.DataFrame(rows).T
grid.index.names = ['롤규칙', '바스켓', '에너지비중']

for c in ['K-Sharpe', '연변동성', 'MDD', 'CAGR', '추적오차']:
    print('---', c, '---')
    print(grid[c].unstack(level=2).round(3))

# 에너지 0% (주식 지수만) 대비 변화: 주 사양 롤 규칙, 바스켓별
ref = grid.loc[(MAIN_ROLL, MAIN_SLEEVE, 0.0)]
print('--- 에너지 0% 대비 변화 (', MAIN_ROLL, ') ---')
d = grid.xs(MAIN_ROLL, level=0).copy()
for c in ['CAGR', '연변동성', 'MDD', 'K-Sharpe']:
    d[c] = d[c] - ref[c]
print(d.round(3))

# 저장 (보고서 표와 차트에 쓴다)
out = []
for (rule, sl, w), lvl in levels.items():
    for dt, x in lvl.items():
        out.append((f'{rule}|{sl}|{w}', dt, float(x)))
pd.DataFrame(out, columns=['scenario', '날짜', '지수']).to_sql('idx_mix_level', engine, if_exists='replace', index=False)
print('idx_mix_level 저장 완료')


#%% 7. 차트: 지수 비교 + 에너지 비중 추이 (월 리밸런싱 vs 방치) + 낙폭
import matplotlib.pyplot as plt
import matplotlib as mpl
mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

W_COLORS = {0.0: '#2a78d6', 0.1: '#1baf7a', 0.2: '#eda100', 0.3: '#eb6834'}
fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 10), sharex=True,
                                 gridspec_kw={'height_ratios': [3, 1.4, 1.6]})
for w in ENERGY_W:
    lvl = levels[(MAIN_ROLL, MAIN_SLEEVE, w)]
    a1.plot(lvl.index, lvl * BASE_LEVEL if 'BASE_LEVEL' in globals() else lvl,
            color=W_COLORS[w], lw=1.8, label=f'에너지 {int(w * 100)}%')
a1.set_title(f'주식 지수 + 에너지 선물 결합 (시작=1, {MAIN_SLEEVE}, {MAIN_ROLL}, {POLICY})', loc='left', fontsize=12)
a1.legend(loc='upper left', frameon=False, fontsize=9)

# 에너지 목표 비중 20% 에서 두 정책의 실제 에너지 비중
_, wen_m = combine(r_eq, r_main, 0.2, 'monthly')
_, wen_h = combine(r_eq, r_main, 0.2, 'hold')
a2.plot(wen_m.index, wen_m * 100, color='#2a78d6', lw=1.3, label='월 리밸런싱')
a2.plot(wen_h.index, wen_h * 100, color='#e34948', lw=1.3, label='방치')
a2.axhline(20, color='#999999', lw=0.8, ls='--')
a2.set_title('에너지 실제 비중 (목표 20%, %)', loc='left', fontsize=12)
a2.legend(loc='upper left', frameon=False, fontsize=9)

for w in (0.0, 0.2, 0.3):
    lvl = levels[(MAIN_ROLL, MAIN_SLEEVE, w)]
    a3.plot(lvl.index, (lvl / lvl.cummax() - 1) * 100, color=W_COLORS[w], lw=1.3, label=f'에너지 {int(w * 100)}%')
a3.set_title('낙폭 (%)', loc='left', fontsize=12)
a3.legend(loc='lower left', frameon=False, fontsize=9)

for ax in (a1, a2, a3):
    ax.grid(True, color='#e5e5e5', lw=0.6)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig('day4_energy_mix.png', dpi=150)
plt.show()

#%% 8. 에너지 종목 후보 탐색 (업종 값 확인)
# 선물 대신 한국 에너지 종목으로 에너지 바스켓을 만들기 위한 첫 단계
# fdr_kr_ticker 에서 업종 컬럼을 찾고, 에너지 관련 업종에 어떤 종목이 있는지 본다
tk = pd.read_sql("""
select * from fdr_kr_ticker
where 기준일 = (select max(기준일) from fdr_kr_ticker)
  and 종목구분 = '보통주'
""", con=engine)
print("fdr_kr_ticker 컬럼:", list(tk.columns))

# 업종으로 보이는 컬럼 후보를 찾는다 (이름에 '업종', '산업', 'Sector', 'Industry' 포함)
ind_cols = [c for c in tk.columns
            if any(k in c for k in ['업종', '산업', 'Sector', 'Industry', 'sector', 'industry'])]
print("업종 후보 컬럼:", ind_cols)

for c in ind_cols:
    print(f"\n[{c}] 값 종류 수:", tk[c].nunique())
    # 에너지 관련 키워드가 들어간 업종 값만 본다
    kw = '석유|가스|에너지|전력|발전|정유|화학|전기|연료'
    hit = tk[tk[c].astype(str).str.contains(kw, na=False)]
    print(hit.groupby(c).size().sort_values(ascending=False).head(30))
    #%% 8-2. 에너지 후보 업종의 종목 목록 확인
# 업종 정의만으로 후보를 정한다 (수익률은 아직 보지 않는다)
EN_INDUSTRY = ['석유 정제품 제조업', '연료용 가스 제조 및 배관공급업', '연료 소매업']

en = tk[tk['산업'].isin(EN_INDUSTRY)].copy()
en['시총(억)'] = (en['시가총액'] / 1e8).round(0)
en = en.sort_values(['산업', '시가총액'], ascending=[True, False])
print(en[['종목코드', '종목명', '시장구분', '산업', '시총(억)']].to_string(index=False))

# 기존 규칙(시총 3,000억 이상)으로 걸렀을 때 남는 종목 수
MIN_CAP_EN = 3000
print("\n전체 후보:", len(en), "/ 시총 3,000억 이상:", int((en['시총(억)'] >= MIN_CAP_EN).sum()))

# Day 3 주식 지수에 이미 들어 있는 종목과 겹치는지 (현재 구성 기준)
cur = pd.read_sql("""
select 종목코드 from idx_weight_hist
where variant = 'E_quota_buffer'
  and impl = (select max(impl) from idx_weight_hist where variant = 'E_quota_buffer')
""", con=engine)
print("주식 지수와 겹치는 종목:", sorted(set(en['종목코드']) & set(cur['종목코드'])))

#%% 9. 에너지 종목 바스켓: 리밸런싱 시점별 종목 선정과 비중
# 업종으로 후보를 정하고, 주식 지수와 같은 규칙(시총, 거래대금, 캡)으로 비중을 만든다.
# 리밸런싱 일정은 주식 지수(E_quota_buffer)의 판정일/편입일을 그대로 가져온다.
EN_INDUSTRY = ['석유 정제품 제조업', '연료용 가스 제조 및 배관공급업', '연료 소매업']
EN_SPECS    = {'EN_base': 3000, 'EN_wide': 1000}     # 시총 기준(억 원): 기본 / 민감도
EN_MIN_TV   = 10          # 63일 평균 거래대금 기준(억 원)
EN_TV_WIN   = 63
EN_CAP      = 0.25
EN_JUMP     = 0.31        # 하루 변동이 이보다 크면 가격 불연속으로 보고 수익률 0 처리 (Day 2와 동일)

# 후보 종목 (현재 시총 포함)
tk = pd.read_sql("""
select * from fdr_kr_ticker
where 기준일 = (select max(기준일) from fdr_kr_ticker)
  and 종목구분 = '보통주'
""", con=engine)
en_tk = tk[tk['산업'].isin(EN_INDUSTRY)].copy()
en_codes = list(en_tk['종목코드'])
cur_mcap = en_tk.set_index('종목코드')['시가총액']          # 원

# 주가, 거래량 (후보 종목만)
codes_sql = ",".join(f"'{c}'" for c in en_codes)
raw_en = pd.read_sql(f"""
select 날짜, 종목코드, 종가, 거래량 from kor_price
where 종목코드 in ({codes_sql}) and 날짜 >= '2021-09-01'
""", con=engine)
raw_en['날짜'] = pd.to_datetime(raw_en['날짜'])
px_en  = raw_en.pivot(index='날짜', columns='종목코드', values='종가').sort_index()
vol_en = raw_en.pivot(index='날짜', columns='종목코드', values='거래량').sort_index()

# 가격 불연속 보정: 일수익률 절대값이 EN_JUMP 초과면 0으로 두고 누적해 보정 가격을 만든다
ret_en = px_en.pct_change()
ret_en = ret_en.mask(ret_en.abs() > EN_JUMP, 0.0)
adj_en = (1 + ret_en.fillna(0)).cumprod()
adj_en = adj_en.where(px_en.notna())

# 시총 = 현재 시총 x (해당일 보정가격 / 마지막 보정가격)  (주식 수 고정 가정, Day 2와 동일)
last_adj = adj_en.ffill().iloc[-1]
mcap_en  = adj_en.div(last_adj, axis=1).mul(cur_mcap.reindex(adj_en.columns), axis=1) / 1e8   # 억 원

# 거래대금 63일 평균 (최소 60일 관측)
tv_en = (px_en * vol_en / 1e8).rolling(EN_TV_WIN, min_periods=60).mean()

# 캡 비중 계산: 상한을 넘는 종목은 캡에 고정하고, 남는 비중은 나머지에 시총 비례로 다시 나눈다
def cap_weight_en(m, cap):
    n = len(m)
    cap = max(cap, 1.0 / n)                 # 종목 수가 적어 캡을 못 지키는 경우 균등배분
    w = m / m.sum()
    fixed = pd.Series(False, index=w.index)
    while True:
        over = (w > cap + 1e-12)
        if not over.any():
            break
        fixed |= over
        w[fixed] = cap
        rest = ~fixed
        if rest.sum() == 0:
            break
        w[rest] = w[rest] / w[rest].sum() * (1 - cap * fixed.sum())
    return w

# 주식 지수의 리밸런싱 일정
sched = pd.read_sql("""
select distinct D, impl from idx_weight_hist
where variant = 'E_quota_buffer'
order by impl
""", con=engine)
sched['D']    = pd.to_datetime(sched['D'])
sched['impl'] = pd.to_datetime(sched['impl'])

en_weights = {}          # {spec: {impl: 비중 Series}}
rows = []
for spec, min_cap in EN_SPECS.items():
    en_weights[spec] = {}
    for _, r in sched.iterrows():
        D = r['D']
        d_use = px_en.index[px_en.index <= D][-1]       # 판정일 이하 마지막 거래일
        m  = mcap_en.loc[d_use]
        tv = tv_en.loc[d_use]
        ok = (m >= min_cap) & (tv >= EN_MIN_TV)
        sel = m[ok].dropna()
        if len(sel) == 0:
            rows.append([spec, D.date(), r['impl'].date(), 0, ''])
            continue
        w = cap_weight_en(sel, EN_CAP)
        en_weights[spec][r['impl']] = w
        names = ", ".join(f"{en_tk.set_index('종목코드').loc[c, '종목명']} {v*100:.0f}%"
                          for c, v in w.sort_values(ascending=False).items())
        rows.append([spec, D.date(), r['impl'].date(), len(sel), names])

chk = pd.DataFrame(rows, columns=['규칙', '판정일', '편입일', '종목수', '구성'])
pd.set_option('display.max_colwidth', 120)
print(chk.to_string(index=False))
print("\n종목 수 요약")
print(chk.groupby('규칙')['종목수'].describe()[['min', 'mean', 'max']])

#%% 10. 에너지 종목 바스켓 일수익률 + 주식 지수 / 선물 결합 / 종목 결합 비교
# 편입일 비중으로 들고 가다가 다음 편입일에 재설정한다 (가격지수, 비용 없음).
def basket_returns(weights, ret, index_dates):
    keys = sorted(weights.keys())
    out = pd.Series(0.0, index=index_dates)
    for i, k in enumerate(keys):
        end = keys[i + 1] if i + 1 < len(keys) else None
        seg = ret.loc[(ret.index >= k) & ((ret.index < end) if end is not None else True)]
        seg = seg.reindex(columns=weights[k].index).fillna(0.0)
        V   = ((1 + seg).cumprod() * weights[k]).sum(axis=1)
        r   = V.pct_change()
        r.iloc[0] = V.iloc[0] - 1.0
        out.loc[r.index.intersection(out.index)] = r.reindex(out.index).dropna()
    return out

# 주식 지수 일수익률과 날짜
lv_all = pd.read_sql("""
select 날짜, 지수 from idx_level where variant = 'E_quota_buffer' order by 날짜
""", con=engine)
lv_all['날짜'] = pd.to_datetime(lv_all['날짜'])
lv_e = lv_all.set_index('날짜')['지수']
r_eq = lv_e.pct_change().dropna()

en_r = {}
for spec in EN_SPECS:
    en_r[spec] = basket_returns(en_weights[spec], ret_en, r_eq.index)
    print(spec, "바스켓 기간:", en_r[spec].index[0].date(), "~", en_r[spec].index[-1].date(),
          "/ 주식 지수와 일수익률 상관:", round(en_r[spec].corr(r_eq), 3))

# 비교 표: 주식 지수 단독 / + 에너지 선물(CLNG, R1, 월) / + 에너지 종목(월 리밸런싱)
# 선물 결합은 셀 6에서 저장한 idx_mix_level 을 그대로 읽는다
mix = pd.read_sql("select scenario, 날짜, 지수 from idx_mix_level", con=engine)
mix['날짜'] = pd.to_datetime(mix['날짜'])

def fut_level(w):
    for s in mix['scenario'].unique():
        p = s.split('|')
        if len(p) == 3 and p[0] == 'R1' and p[1] == 'CLNG' and abs(float(p[2]) - w) < 1e-9:
            return mix[mix['scenario'] == s].set_index('날짜')['지수'].sort_index()
    raise KeyError(f"idx_mix_level 에 R1|CLNG|{w} 없음: {list(mix['scenario'].unique())[:6]}")

rows = []
for w in [0.1, 0.2, 0.3]:
    # (a) 주식 지수 + 에너지 선물
    lv_f = fut_level(w)
    m = metrics(lv_f, r_eq);  rows.append([w, '지수+에너지 선물(CLNG, R1)'] + list(pd.Series(m).values))
    # (b) 주식 지수 + 에너지 종목 (월 말 비중 복원)
    for spec in EN_SPECS:
        lv_s, ew = combine(r_eq, en_r[spec], w, 'monthly')
        m = metrics(lv_s, r_eq);  rows.append([w, f'지수+에너지 종목({spec})'] + list(pd.Series(m).values))
cols = ['에너지 비중', '구성'] + list(pd.Series(metrics(lv_e, r_eq)).index)
base = pd.Series(metrics(lv_e, r_eq))
print("\n주식 지수 단독")
print(base.round(4).to_string())
print("\n비교")
print(pd.DataFrame(rows, columns=cols).round(4).to_string(index=False))

# 에너지 바스켓 자체 성과 (참고)
for spec in EN_SPECS:
    lv_b = (1 + en_r[spec]).cumprod()
    print(f"\n{spec} 바스켓 단독 누적수익률: {(lv_b.iloc[-1]-1)*100:.1f}%  "
          f"연변동성: {en_r[spec].std()*252**0.5*100:.1f}%")
    #%% 11. K-Sharpe (KRX 방법론서 방식) 로 지표 다시 계산
# 일별 초과수익률 = ln(X_t / X_t-1) - CD91_t / 365 x D   (D = 직전 거래일부터의 달력일수)
# K-Sharpe = 평균(초과) / 표준편차(초과) x sqrt(252)
# 표준편차의 자유도는 방법론서에 없어 표본표준편차(ddof=1)로 둔다
cd_raw = pd.read_sql("select 날짜, 금리 from cd91_rate order by 날짜", con=engine)
cd_raw['날짜'] = pd.to_datetime(cd_raw['날짜'])
cd_s = cd_raw.set_index('날짜')['금리'] / 100.0           # % -> 소수

def ksharpe(level, window=None):
    lv = level.dropna()
    r  = np.log(lv / lv.shift(1))
    d  = lv.index.to_series().diff().dt.days
    cd = cd_s.reindex(lv.index, method='ffill')
    ex = (r - cd / 365.0 * d).dropna()
    if window is not None:
        ex = ex.iloc[-window:]
    return ex.mean() / ex.std(ddof=1) * np.sqrt(252)

def perf(level):
    lv  = level.dropna()
    n   = (lv.index[-1] - lv.index[0]).days / 365.25
    r   = lv.pct_change().dropna()
    mdd = (lv / lv.cummax() - 1).min()
    return pd.Series({'CAGR': (lv.iloc[-1] / lv.iloc[0]) ** (1 / n) - 1,
                      '연변동성': r.std() * np.sqrt(252),
                      'MDD': mdd,
                      'K-Sharpe': ksharpe(lv),
                      'K-Sharpe(최근252일)': ksharpe(lv, 252),
                      'K-Sharpe(최근756일)': ksharpe(lv, 756)})

lv_base = lv_e / lv_e.iloc[0]
rows = {'주식 지수 단독': perf(lv_base)}
for w in [0.1, 0.2, 0.3]:
    rows[f'+선물(CLNG,R1) {int(w*100)}%'] = perf(fut_level(w))
    lv_s, _ = combine(r_eq, en_r['EN_base'], w, 'monthly')
    rows[f'+종목(EN_base) {int(w*100)}%'] = perf(lv_s)
print(pd.DataFrame(rows).T.round(3).to_string())

#%% 12. 거래비용 민감도 (주식 지수의 분기 리밸런싱 비용)
# 편입일마다 직전 목표비중 대비 편도 회전율 x 비용(bp) 만큼 지수 수익률에서 뺀다.
# 직전 편입 비중은 가격에 따른 드리프트를 반영하지 못한 근사다.
wh = pd.read_sql("""
select impl, 종목코드, weight from idx_weight_hist
where variant = 'E_quota_buffer' order by impl
""", con=engine)
wh['impl'] = pd.to_datetime(wh['impl'])
wide = wh.pivot(index='impl', columns='종목코드', values='weight').fillna(0.0)
turn = (wide.diff().abs().sum(axis=1) / 2).iloc[1:]        # 편도 회전율
print("분기 평균 편도 회전율: %.1f%%  / 연 환산: %.1f%%" % (turn.mean()*100, turn.mean()*400))

rows = {}
for bp in [0, 10, 20, 30, 50]:
    r = r_eq.copy()
    for d, t in turn.items():
        if d in r.index:
            r.loc[d] -= t * bp / 1e4 * 2                    # 매도+매수 양쪽에 비용
    lv = (1 + r).cumprod()
    lv = pd.concat([pd.Series([1.0], index=[lv_e.index[0]]), lv])
    rows[f'편도 {bp}bp'] = perf(lv)
print(pd.DataFrame(rows).T.round(3).to_string())   
#%% 13. 연도별, 부분기간 강건성
# 2025~2026 급등이 결과를 지배하는지 확인한다 (표본 전체 vs 앞뒤 구간)
cands = {'주식 지수 단독': lv_base,
         '+선물 20%': fut_level(0.2),
         '+종목(EN_base) 20%': combine(r_eq, en_r['EN_base'], 0.2, 'monthly')[0]}
yr = pd.DataFrame({k: v.resample('YE').last().pct_change() for k, v in cands.items()})
yr.iloc[0] = [v.resample('YE').last().iloc[0] / v.iloc[0] - 1 for v in cands.values()]
yr.index = yr.index.year
print((yr * 100).round(1).to_string())

for name, (a, b) in {'2022-04~2024-12': ('2022-04-01', '2024-12-31'),
                     '2025-01~2026-10': ('2025-01-01', '2026-12-31')}.items():
    rows = {}
    for k, v in cands.items():
        seg = v.loc[a:b]
        rows[k] = perf(seg / seg.iloc[0])
    print(f"\n[{name}]")
    print(pd.DataFrame(rows).T.iloc[:, :4].round(3).to_string()) 

#%% 14. 상품 구성안 A / B / C 비교
# A: 주식 지수 단독
# B: 주식 지수 + 에너지 종목(EN_base) 을 한 지수 안에서 정해진 비중으로 유지
# C: 주식 지수 + 에너지 선물(CLNG, R1)
# 비중 복원: 분기(주식 지수 편입일, ETF 리밸런싱 주기) 가 주 사양, 월말은 민감도

# --- 선물 바스켓 일수익률 복원 ---
# 월 리밸런싱 결합 지수(idx_mix_level)는 월말에 비중을 되돌리므로 월 안에서는
#   L_t / L_p = (1-w) x E_t / E_p + w x F_t / F_p     (p = 직전 월말)
# 이 식에서 F(에너지 바스켓)의 월 내 누적을 거꾸로 풀면 일수익률이 나온다.
E  = lv_e / lv_e.iloc[0]
w0 = 0.3
L  = fut_level(w0)
idx = L.index.intersection(E.index)
L, E = L.loc[idx], E.loc[idx]

mkey = idx.to_period('M')
last_dates = pd.Series(idx, index=idx).groupby(mkey).last()
prev_end = pd.Series([last_dates.get(m - 1, idx[0]) for m in mkey], index=idx)

ratio_L = L / L.loc[prev_end].values
ratio_E = E / E.loc[prev_end].values
ratio_F = (ratio_L - (1 - w0) * ratio_E) / w0

first_day = pd.Series([(idx[i - 1] == prev_end.iloc[i]) if i > 0 else True
                       for i in range(len(idx))], index=idx)
ratio_prev = ratio_F.shift(1).where(~first_day, 1.0)
r_fut = (ratio_F / ratio_prev - 1).iloc[1:]
print("복원한 선물 바스켓 일수익률:", r_fut.index[0].date(), "~", r_fut.index[-1].date(),
      "/ 연변동성 %.1f%%" % (r_fut.std() * 252 ** 0.5 * 100))

# --- 비중 복원 함수 ---
start_date = lv_e.index[0]
def mix_reset(r_a, r_b, w, reset_dates):
    resets = set(pd.to_datetime(list(reset_dates)))
    va, vb = 1.0 - w, w
    out = []
    for d in r_a.index:
        va *= 1.0 + r_a[d]
        vb *= 1.0 + r_b[d]
        tot = va + vb
        out.append(tot)
        if d in resets:                       # 해당일 종가에서 목표 비중으로 되돌림
            va, vb = tot * (1.0 - w), tot * w
    s = pd.Series(out, index=r_a.index)
    return pd.concat([pd.Series([1.0], index=[start_date]), s])

common = r_eq.index.intersection(r_fut.index).intersection(en_r['EN_base'].index)
ra  = r_eq.loc[common]
rb  = en_r['EN_base'].loc[common]
rc  = r_fut.loc[common]

reset_Q = list(sched['impl'])
reset_M = list(pd.Series(common, index=common).groupby(common.to_period('M')).last())

# 검증: 월말 복원으로 다시 합성한 결과가 DB에 저장한 20% 결합 지수와 맞는지
chk = mix_reset(ra, rc, 0.2, reset_M)
ref = fut_level(0.2).reindex(chk.index)
print("복원 검증 (w=20%%): 최대 상대오차 %.5f" % ((chk / ref - 1).abs().max()))

# --- 비교 ---
def te(level, base):
    d = level.pct_change().dropna() - base.pct_change().dropna()
    return d.std() * 252 ** 0.5

result = {}
for rname, rd in [('분기(주 사양)', reset_Q), ('월(민감도)', reset_M)]:
    base_lv = mix_reset(ra, rb, 0.0, rd)               # w=0 이면 주식 단독
    base_p  = perf(base_lv)
    result[(rname, 'A 주식 단독', 0.0)] = pd.concat([base_p, pd.Series({'추적오차': 0.0})])
    for w in [0.1, 0.2, 0.3]:
        for pname, rs in [('B 주식+에너지 종목', rb), ('C 주식+에너지 선물', rc)]:
            lv = mix_reset(ra, rs, w, rd)
            p  = perf(lv)
            result[(rname, pname, w)] = pd.concat([p, pd.Series({'추적오차': te(lv, base_lv)})])

res = pd.DataFrame(result).T
print(res.round(3).to_string())

# --- 판정: 같은 주기, 같은 비중에서 A 대비 5개 항목 중 개선 개수 ---
rows = []
for (rname, pname, w), r in res.iterrows():
    if w == 0.0:
        continue
    a = res.loc[(rname, 'A 주식 단독', 0.0)]
    flags = [r['K-Sharpe'] > a['K-Sharpe'],
             r['K-Sharpe(최근756일)'] > a['K-Sharpe(최근756일)'],
             r['K-Sharpe(최근252일)'] > a['K-Sharpe(최근252일)'],
             r['MDD'] > a['MDD'],
             r['연변동성'] < a['연변동성']]
    rows.append([rname, pname, w, sum(flags), '후보' if sum(flags) >= 4 else '-'])
print("\n판정 (5개 중 개선 개수, 4개 이상이면 채택 후보)")
print(pd.DataFrame(rows, columns=['주기', '구성', '에너지 비중', '개선 개수', '판정']).to_string(index=False))

#%% 15. 선물 시차 민감도 (C안)
# 선물 수익률을 주식 지수보다 하루 앞/뒤로 밀어 본다.
# 시차 +1: 선물 수익률을 하루 늦춰 적용 / -1: 하루 앞당겨 적용
rows = {}
rows['A 주식 단독'] = pd.concat([perf(mix_reset(ra, rc, 0.0, reset_Q)), pd.Series({'상관': np.nan})])
for k in [-1, 0, 1]:
    r_k = rc.shift(k).fillna(0.0)
    lv  = mix_reset(ra, r_k, 0.2, reset_Q)
    rows[f'C 20% 시차 {k:+d}일'] = pd.concat([perf(lv), pd.Series({'상관': ra.corr(r_k)})])
print(pd.DataFrame(rows).T.round(3).to_string())

#%% 16. 에너지 종목 바스켓 수시변경 반영
# 정기 편입일 사이에 한 종목 비중이 기준(30%)을 3일 연속 넘으면
# 다음 거래일에 캡 25%로 다시 맞춘다 (Day 3 지수와 같은 규칙).
# 종목 수가 적어 균등배분이 기준을 넘는 경우(3개면 33%)는
# 기준을 (캡 + 5%p) 와 30% 중 큰 값으로 올려 매일 발동하지 않게 한다.
AH_TRIG = 0.30
AH_DAYS = 3

def basket_returns_adhoc(weights, ret, index_dates):
    keys = sorted(weights.keys())
    out = pd.Series(0.0, index=index_dates)
    events = []
    for i, k in enumerate(keys):
        end = keys[i + 1] if i + 1 < len(keys) else None
        seg = ret.loc[(ret.index >= k) & ((ret.index < end) if end is not None else True)]
        w0  = weights[k]
        seg = seg.reindex(columns=w0.index).fillna(0.0)
        n      = len(w0)
        cap_k  = max(EN_CAP, 1.0 / n)
        trig_k = max(AH_TRIG, cap_k + 0.05)
        w = w0.copy()
        streak, pending = 0, False
        for d, r in seg.iterrows():
            if pending:                                   # 발동 다음 거래일 시작에 비중 재조정
                w = cap_weight_en(w, cap_k)
                pending, streak = False, 0
            pr = float((w * r).sum())
            if d in out.index:
                out.loc[d] = pr
            w = w * (1.0 + r) / (1.0 + pr)               # 드리프트
            if w.max() > trig_k:
                streak += 1
            else:
                streak = 0
            if streak >= AH_DAYS:
                pending = True
                events.append((d.date(), w.idxmax(), round(float(w.max()), 3)))
    return out, events

rb_ad, ev = basket_returns_adhoc(en_weights['EN_base'], ret_en, r_eq.index)
rb_ad = rb_ad.loc[common]
print("수시변경 발동 횟수:", len(ev))
for e in ev[:15]:
    print("  ", e)
print("정기만 vs 수시 포함 일수익률 상관: %.4f" % rb.corr(rb_ad))

rows = {}
rows['A 주식 단독']         = perf(mix_reset(ra, rb, 0.0, reset_Q))
rows['B 20% (정기만)']      = perf(mix_reset(ra, rb, 0.2, reset_Q))
rows['B 20% (수시변경 포함)'] = perf(mix_reset(ra, rb_ad, 0.2, reset_Q))
print(pd.DataFrame(rows).T.round(3).to_string())
#%% 17. 용량 분석: ETF 규모별 종목 거래대금 대비 보유 비중
# 보유금액 = ETF 규모 x 종목 비중, 거래대금 = 최근 63일 평균 (억 원).
# 참여율 = 보유금액 / 거래대금 -> 하루 거래대금의 몇 %를 들고 있는지
# 20%를 하루 거래대금의 20%만 쓴다고 가정했을 때 전량 정리에 걸리는 일수를 같이 본다.
# 현재 구성: A 종목 비중 x 0.8 + 에너지 종목(EN_base) 비중 x 0.2
wa = pd.read_sql("""
select 종목코드, weight from idx_weight_hist
where variant = 'E_quota_buffer'
  and impl = (select max(impl) from idx_weight_hist where variant = 'E_quota_buffer')
""", con=engine).set_index('종목코드')['weight']
last_k = max(en_weights['EN_base'].keys())
wb = en_weights['EN_base'][last_k]

wcomb = pd.concat([wa * 0.8, wb * 0.2])
codes = list(wcomb.index)
codes_sql = ",".join(f"'{c}'" for c in codes)
pp = pd.read_sql(f"""
select 날짜, 종목코드, 종가, 거래량 from kor_price
where 종목코드 in ({codes_sql}) and 날짜 >= date_sub(curdate(), interval 120 day)
""", con=engine)
pp['날짜'] = pd.to_datetime(pp['날짜'])
tvp = (pp.assign(tv=pp['종가'] * pp['거래량'] / 1e8)
         .sort_values('날짜').groupby('종목코드')['tv']
         .apply(lambda s: s.tail(63).mean()))

names = pd.concat([
    pd.read_sql("select 종목코드, 종목명 from fdr_kr_ticker where 기준일 = (select max(기준일) from fdr_kr_ticker)",
                con=engine).set_index('종목코드')['종목명']])
cap_tbl = pd.DataFrame({'종목명': names.reindex(codes).values,
                        '비중': wcomb.values,
                        '평균 거래대금(억)': tvp.reindex(codes).values}, index=codes)
cap_tbl['구분'] = ['A(주식)'] * len(wa) + ['에너지'] * len(wb)

rows = []
for aum in [100, 300, 500, 1000]:                           # ETF 규모 (억 원)
    part = aum * cap_tbl['비중'] / cap_tbl['평균 거래대금(억)']
    top  = part.idxmax()
    rows.append([aum, round(part.max() * 100, 1), cap_tbl.loc[top, '종목명'],
                 round(part.max() / 0.2, 2)])
print(pd.DataFrame(rows, columns=['ETF 규모(억)', '최대 참여율(%)', '가장 빡빡한 종목', '정리 일수(20% 참여)']).to_string(index=False))
print()
print(cap_tbl.sort_values('평균 거래대금(억)').head(8).round(4).to_string())