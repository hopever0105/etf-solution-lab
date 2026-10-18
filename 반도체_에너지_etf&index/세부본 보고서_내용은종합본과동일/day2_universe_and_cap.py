#%% 0. 안내 + 실행 플래그
# 먼저 아래 파일들을 보고 오세요. 이미 DB에 데이터가 있으면 여기서부터 진행하세요.
#   1) 국내 주식 데이터 수집.py                 -> kor_price, kor_ticker
#   2) 00_collect_futures_tv.py                 -> tv_futures_price (Day 4에서 사용)
#   3) day1_data_check_and_hypothesis.py        -> idx_candidate (후보군 275종목)
#
# 환경: conda activate ta_env   (Anaconda Prompt)
#   Spyder: Tools > Preferences > Python interpreter > Use the following
#           Python interpreter 에서 ta_env 의 python.exe 선택 후 Spyder 재시작
#   패키지가 없으면 ta_env 를 켠 상태에서:
#   pip install pandas numpy sqlalchemy pymysql matplotlib
#
# DB 비밀번호는 코드에 쓰지 않고 환경변수 DB_PW 에서 읽는다.
#   Windows 에서 한 번만:  setx DB_PW "비밀번호"   (설정 후 Spyder 재시작)
import os
import runpy
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

RUN_DOWNLOAD = False   # True: 수집 파일을 순서대로 실행 / False: DB에서 바로 읽기

# RUN_DOWNLOAD=True 일 때 실행할 파일 (같은 폴더에 있다고 가정, 각 파일의 단독 실행 여부는 확인 안 됨)
COLLECT_FILES = ['국내 주식 데이터 수집.py',
                 '00_collect_futures_tv.py',
                 'day1_data_check_and_hypothesis.py']

DB_USER = os.environ.get('DB_USER', 'root')   # 사용자명이 root 가 아니면 환경변수로 지정
DB_PW   = os.environ['DB_PW']
engine  = create_engine(
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PW)}@127.0.0.1:3306/stock_db")

if RUN_DOWNLOAD:
    for f in COLLECT_FILES:
        print('실행:', f)
        runpy.run_path(f)

# 플래그가 False 일 때 필요한 테이블이 DB에 있는지 확인
NEED_TABLES = ['kor_price', 'idx_candidate']
have = pd.read_sql("SHOW TABLES", engine).iloc[:, 0].tolist()
missing = [t for t in NEED_TABLES if t not in have]
if missing:
    raise RuntimeError(f"DB에 없는 테이블: {missing}\n"
                       f"RUN_DOWNLOAD = True 로 바꿔서 다시 실행하거나, "
                       f"위 안내의 수집 파일을 먼저 실행하세요.")
print('필요 테이블 확인 완료:', NEED_TABLES)


#%% 1. 파라미터 (수익률을 보기 전에 고정하는 값들)
# KEDI 방식의 편입 요건을 그대로 따른다.
MIN_CAP   = 3_000 * 1e8      # 시가총액 3,000억 원 이상
MIN_TV    = 10 * 1e8         # 3개월 평균 거래대금 10억 원 이상
TV_WIN    = 63               # 3개월 ≈ 63 거래일
CAP       = 0.25             # 단일 종목 비중 상한 25%
# 가격 데이터가 2021-10-12부터라 2021-12-30 결정일에는 63일 평균을 만들 수 없다
# (거래일 약 55일). 그래서 첫 결정일은 2022-03-31이 되도록 START를 2022-01-01로 둔다.
START     = '2022-01-01'     # 리밸런싱 이력 시작
IMPL_LAG  = 3                # 결정일(D) 다음 3영업일째에 반영 (D+3)
JUMP_TH   = 0.31             # 일 등락 한도(±30%) 바깥은 액면분할 등 가격 단절로 본다

# 산업(KSIC) -> 산업군. 산업군별 쿼터는 N=10 기준 사전 결정.
# '특수 목적용 기계 제조업'에는 반도체 장비, 로봇, 농기계가 섞여 있어서
# 산업 단위로는 쓸 수 없다. 기본은 DROP 으로 두고, 반도체 장비주만 OVERRIDE 로 CHIP 에 넣는다.
GROUP_MAP = {
    '반도체 제조업': 'CHIP',
    '통신 및 방송 장비 제조업': 'HW',
    '전자부품 제조업': 'HW',
    '전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업': 'POWER',
    '절연선 및 케이블 제조업': 'POWER',
    '전기업': 'POWER',
    '특수 목적용 기계 제조업': 'DROP',
    '자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업': 'PLAT',
    '컴퓨터 프로그래밍, 시스템 통합 및 관리업': 'PLAT',
}
# 산업 분류와 실제 사업이 어긋나는 종목은 코드로 직접 지정
# 삼성전자는 KSIC 상 '통신 및 방송 장비 제조업'이지만 사업의 중심은 메모리 반도체
OVERRIDE = {
    '005930': 'CHIP',    # 삼성전자
    '034020': 'POWER',   # 두산에너빌리티 (산업은 일반 목적용 기계 제조업)
    '042700': 'CHIP',    # 한미반도체
    '036930': 'CHIP',    # 주성엔지니어링
    '240810': 'CHIP',    # 원익IPS
    '039030': 'CHIP',    # 이오테크닉스
    '403870': 'CHIP',    # HPSP
    '319660': 'CHIP',    # 피에스케이
    '031980': 'CHIP',    # 피에스케이홀딩스
    '084370': 'CHIP',    # 유진테크
    '095610': 'CHIP',    # 테스
    '454910': 'DROP',    # 두산로보틱스
}

QUOTA_10 = {'CHIP': 4, 'POWER': 3, 'HW': 2, 'PLAT': 1}   # 합계 10
#%% 2. 데이터 적재 + 가격 단절 보정
cand = pd.read_sql("SELECT 종목코드, 종목명, 시장구분, 산업, 시가총액 FROM idx_candidate", engine)
cand['종목코드'] = cand['종목코드'].astype(str).str.zfill(6)
cand['group'] = cand['산업'].map(GROUP_MAP)
for k, v in OVERRIDE.items():
    cand.loc[cand['종목코드'] == k, 'group'] = v
if cand['group'].isna().any():
    print('산업군 미지정 종목 (ETC 처리):')
    print(cand.loc[cand['group'].isna(), ['종목코드', '종목명', '산업']])
    cand['group'] = cand['group'].fillna('ETC')
# DROP 으로 지정한 종목은 후보군에서 뺀다
cand = cand[cand['group'] != 'DROP']
cand = cand.set_index('종목코드')

codes = "','".join(cand.index)
sql = f"""
SELECT 날짜, 종목코드, 종가, 거래량
FROM kor_price
WHERE 종목코드 IN ('{codes}')
  AND 날짜 >= DATE_SUB('{START}', INTERVAL 200 DAY)
"""
raw = pd.read_sql(sql, engine, parse_dates=['날짜'])
raw['종목코드'] = raw['종목코드'].astype(str).str.zfill(6)

px  = raw.pivot(index='날짜', columns='종목코드', values='종가').sort_index()
vol = raw.pivot(index='날짜', columns='종목코드', values='거래량').sort_index()

# 거래대금은 실제 체결가격이 필요하므로 보정하지 않은 종가 × 거래량으로 근사한다
tv     = px * vol
tv_avg = tv.rolling(TV_WIN, min_periods=60).mean()

# kor_price 는 액면분할 등이 반영되지 않은 가격이다.
# 일 변동이 상하한(±30%)을 넘는 날은 가격 단절로 보고 그날 수익률을 0으로 둔다.
# (그날의 실제 등락은 버려지는 근사치이므로 한계로 보고서에 적는다)
ret   = px.pct_change(fill_method=None)
event = ret.abs() > JUMP_TH
ret_c = ret.where(~event, 0.0)
adj   = (1 + ret_c.fillna(0)).cumprod().where(px.notna())

# 과거 시총 = 현재 시총 × (보정가격 / 마지막 보정가격)
# 상장주식수를 현재 값으로 고정한 근사라서 유·무상증자 같은 주식수 변화는 반영되지 않는다.
last   = adj.ffill().iloc[-1]
mcap_df = adj.divide(last, axis=1).multiply(cand['시가총액'].reindex(adj.columns), axis=1)

print('종목 수:', px.shape[1], '/ 기간:', px.index.min().date(), '~', px.index.max().date())
print('가격 단절로 처리한 건수:', int(event.sum().sum()), '/ 종목 수:', int((event.sum() > 0).sum()))

#%% 2-2. 분류 점검: 산업군별 전체 종목 (특수 목적용 기계 중 장비주가 더 있는지 확인)
chk = cand.reset_index()[['종목코드', '종목명', '산업', 'group', '시가총액']].copy()
chk['시총(조)'] = (chk['시가총액'] / 1e12).round(1)
chk = chk.drop(columns='시가총액').sort_values('시총(조)', ascending=False)

print('--- 특수 목적용 기계 제조업 전체 ---')
print(chk[chk['산업'] == '특수 목적용 기계 제조업'].to_string(index=False))

print('--- 산업군별 종목 수 ---')
print(chk['group'].value_counts())

print('--- POWER 시총 상위 20 ---')
print(chk[chk['group'] == 'POWER'].head(20).to_string(index=False))
#%% 3. 리밸런싱 날짜 (결정일 D = 분기 마지막 영업일, 반영일 = D+3 영업일)
idx = px.index
q_last = idx.to_series().groupby(idx.to_period('Q')).max()
q_last = q_last[q_last >= pd.Timestamp(START)]
# 마지막 분기는 아직 끝나지 않았을 수 있으므로 분기말이 실제 지난 경우만 쓴다
q_last = q_last[q_last.index.end_time <= idx.max()]
    
def impl_date(D):
    pos = idx.get_loc(D)
    return idx[min(pos + IMPL_LAG, len(idx) - 1)]

REB = pd.DataFrame({'D': q_last.values})
REB['impl'] = REB['D'].map(impl_date)
print(REB)


#%% 4. get_universe(date): 결정일 기준으로 편입 가능한 종목 목록
def get_universe(date):
    date = pd.Timestamp(date)
    df = pd.DataFrame({
        'mcap'  : mcap_df.loc[date],
        'tv_avg': tv_avg.loc[date],
        'price' : px.loc[date],
        'vol'   : vol.loc[date],
    })
    # 결정일에 거래가 없는 종목은 제외 (거래정지 등)
    df = df[df['price'].notna() & (df['vol'] > 0)]
    # KEDI 요건: 시총, 거래대금
    df = df[(df['mcap'] >= MIN_CAP) & (df['tv_avg'] >= MIN_TV)]
    df = df.join(cand[['종목명', '산업', 'group']])
    return df.sort_values('mcap', ascending=False)


#%% 5. select_stocks(): 종목 선정 (쿼터 없으면 시총 순 상위 N)
def select_stocks(univ, N, quota=None):
    if quota is None:
        return univ.head(N)
    picked = []
    for g, q in quota.items():
        picked.append(univ[univ['group'] == g].head(q))
    sel = pd.concat(picked)
    # 산업군에 후보가 모자라 못 채운 자리는 남은 종목 중 시총 순으로 채운다
    short = N - len(sel)
    if short > 0:
        rest = univ.drop(sel.index)
        sel = pd.concat([sel, rest.head(short)])
    return sel.sort_values('mcap', ascending=False)


#%% 6. calculate_capped_weight(): 시총가중 + 25% 상한, 초과분은 나머지에 시총 비례 재배분
def calculate_capped_weight(mcap, cap=CAP):
    mcap = mcap.astype(float)
    if len(mcap) * cap < 1:
        raise ValueError(f'종목 수 {len(mcap)} x 상한 {cap} < 1 이라 상한을 맞출 수 없다')
    w = mcap / mcap.sum()
    capped = pd.Series(False, index=w.index)
    while True:
        over = (w > cap + 1e-12) & ~capped
        if not over.any():
            break
        capped |= over
        w[capped] = cap
        free = ~capped
        # 상한 종목에 쓰고 남은 비중을 나머지 종목에 시총 비례로 나눈다
        w[free] = mcap[free] / mcap[free].sum() * (1 - cap * capped.sum())
    return w


#%% 7. 테스트: 가장 최근 결정일 하나로 확인
D = REB['D'].iloc[-1]
univ = get_universe(D)
print(f'결정일 {D.date()} / 유니버스 {len(univ)}종목')
print(univ['group'].value_counts())

sel = select_stocks(univ, 10, QUOTA_10)
w_raw = sel['mcap'] / sel['mcap'].sum()
w_cap = calculate_capped_weight(sel['mcap'])

view = sel[['종목명', 'group', 'mcap']].copy()
view['mcap(조)'] = (view['mcap'] / 1e12).round(1)
view['raw'] = (w_raw * 100).round(1)
view['capped'] = (w_cap * 100).round(1)
print(view.drop(columns='mcap'))
print('비중 합계:', round(w_cap.sum(), 6), '/ 최대 비중:', round(w_cap.max(), 4))

#%% 7-2. POWER 후보 확인 (HD현대일렉트릭, 한국전력 등이 왜 안 보이는지)
D = REB['D'].iloc[-1]
univ = get_universe(D)

# 1) 유니버스 안의 POWER 상위 15
print(univ[univ['group'] == 'POWER'][['종목명', '산업', 'mcap']]
      .assign(**{'mcap(조)': lambda x: (x['mcap'] / 1e12).round(1)})
      .drop(columns='mcap').head(15))

# 2) 후보군 자체에 이름이 있는지
for nm in ['HD현대일렉트릭', '한국전력', '한미반도체', '한화에어로스페이스']:
    print(nm, '->', cand[cand['종목명'].str.contains(nm)][['종목명', '산업', 'group']].values.tolist())

#%% 8. 리밸런싱 이력 + 변형 비교 (구조 지표만 본다, 수익률은 Day 4)
# A: 시총 상위 15, 쿼터 없음 / B: 상위 10, 쿼터 없음 / C: 10종목 + 산업군 쿼터 / D: C에서 캡만 제거
VARIANTS = {
    'A_top15'      : dict(N=15, quota=None,     cap=True),
    'B_top10'      : dict(N=10, quota=None,     cap=True),
    'C_top10_quota': dict(N=10, quota=QUOTA_10, cap=True),
    'D_quota_nocap': dict(N=10, quota=QUOTA_10, cap=False),
}

hist = {k: {} for k in VARIANTS}
for _, r in REB.iterrows():
    univ = get_universe(r['D'])
    # 유니버스가 가장 큰 변형(N=15)에도 모자라면 그 회차는 건너뛴다
    if len(univ) < 15:
        print(f"건너뜀: {r['D'].date()} 유니버스 {len(univ)}종목")
        continue
    for k, v in VARIANTS.items():
        sel = select_stocks(univ, v['N'], v['quota'])
        w_r = sel['mcap'] / sel['mcap'].sum()
        w_c = calculate_capped_weight(sel['mcap']) if v['cap'] else w_r
        hist[k][r['D']] = dict(impl=r['impl'], raw=w_r, w=w_c)

print('리밸런싱 회차:', len(hist['A_top15']))

def summarize(h):
    dates = list(h.keys())
    maxw_raw = [h[d]['raw'].max() for d in dates]
    maxw     = [h[d]['w'].max() for d in dates]
    effN     = [1 / (h[d]['w'] ** 2).sum() for d in dates]          # 유효 종목 수 (1/HHI)
    bind     = [(h[d]['raw'] > CAP).any() for d in dates]            # 캡이 걸린 회차
    to, rep = [], []
    for a, b in zip(dates[:-1], dates[1:]):
        wa, wb = h[a]['w'], h[b]['w']
        al = pd.concat([wa, wb], axis=1).fillna(0)
        to.append(0.5 * (al.iloc[:, 0] - al.iloc[:, 1]).abs().sum())  # 편도 회전율(드리프트 무시)
        rep.append(len(set(wb.index) - set(wa.index)))                # 교체 종목 수
    return pd.Series({
        '리밸런싱 횟수'      : len(dates),
        '평균 최대비중(캡 전)': np.mean(maxw_raw),
        '평균 최대비중(캡 후)': np.mean(maxw),
        '평균 유효종목수'    : np.mean(effN),
        '캡 발동 비율'       : np.mean(bind),
        '평균 회전율'        : np.mean(to),
        '평균 교체종목수'    : np.mean(rep),
    })

summary = pd.DataFrame({k: summarize(h) for k, h in hist.items()}).round(3)
print(summary)

# 산업군 비중 평균 (변형 C)
gw = []
for d, x in hist['C_top10_quota'].items():
    s = x['w'].groupby(cand['group'].reindex(x['w'].index)).sum()
    gw.append(s.rename(d))
print((pd.concat(gw, axis=1).T.fillna(0).mean() * 100).round(1))

# 결과 저장 (Day 3 에서 읽는다)
rows = []
for k, h in hist.items():
    for d, x in h.items():
        for code, wt in x['w'].items():
            rows.append((k, d, x['impl'], code, float(wt)))
pd.DataFrame(rows, columns=['variant', 'D', 'impl', '종목코드', 'weight']) \
  .to_sql('idx_weight_hist', engine, if_exists='replace', index=False)
print('idx_weight_hist 저장 완료')

#%% 8-2. 보고서용 구조 시계열 (변형 C 기준) + 가격 단절 종목 + 편입/편출
hc = hist['C_top10_quota']

# 결정일별 산업군 비중, 캡 전 상위 2종목 비중, 유효 종목 수
rows = []
for d, x in hc.items():
    g = x['w'].groupby(cand['group'].reindex(x['w'].index)).sum()
    rows.append({
        'D'         : d.date(),
        'CHIP(%)'   : round(g.get('CHIP', 0) * 100, 1),
        'POWER(%)'  : round(g.get('POWER', 0) * 100, 1),
        'HW(%)'     : round(g.get('HW', 0) * 100, 1),
        'PLAT(%)'   : round(g.get('PLAT', 0) * 100, 1),
        '상위2(캡전%)': round(x['raw'].nlargest(2).sum() * 100, 1),
        '유효종목수' : round(1 / (x['w'] ** 2).sum(), 2),
    })
print(pd.DataFrame(rows).set_index('D').to_string())

# 가격 단절로 처리한 날짜와 종목
r_, c_ = np.where(event.values)
print('--- 가격 단절 처리 내역 ---')
for i, j in zip(r_, c_):
    code = event.columns[j]
    print(event.index[i].date(), code, cand.loc[code, '종목명'] if code in cand.index else '', round(ret.iloc[i, j], 3))

# 회차별 편입/편출
print('--- 편입/편출 (변형 C) ---')
dts = list(hc.keys())
for a, b in zip(dts[:-1], dts[1:]):
    ina = set(hc[b]['w'].index) - set(hc[a]['w'].index)
    out = set(hc[a]['w'].index) - set(hc[b]['w'].index)
    if ina or out:
        print(b.date(), '편입', [cand.loc[c, '종목명'] for c in ina],
              '/ 편출', [cand.loc[c, '종목명'] for c in out])

# 첫 회차와 마지막 회차의 구성
for d in (dts[0], dts[-1]):
    x = hc[d]
    t = pd.DataFrame({'종목명': cand['종목명'].reindex(x['w'].index),
                      'group': cand['group'].reindex(x['w'].index),
                      'raw(%)': (x['raw'] * 100).round(1),
                      'capped(%)': (x['w'] * 100).round(1)})
    print('---', d.date(), '---')
    print(t.to_string())

#%% 9. 버퍼 규칙 변형 (E): 기존 편입 종목은 산업군 내 순위에 여유를 둬서 유지

# KOSDAQ150 의 버퍼(기존 종목 유지 폭) 아이디어를 쿼터 방식에 맞게 줄여 쓴 것이다.
# 문서의 120%/80% 규칙과 동일하지는 않고, 정확한 적용 방식은 확인 안 됨.
import math
BUF = 1.5    # 기존 종목은 산업군 내 시총 순위가 쿼터 x 1.5 이내면 자리를 유지

def select_stocks_buffer(univ, quota, prev_codes, buf=BUF):
    N = sum(quota.values())
    picked = []
    for g, q in quota.items():
        gu = univ[univ['group'] == g].copy()
        gu['rank'] = np.arange(1, len(gu) + 1)       # univ 가 시총 내림차순이라 순서가 곧 순위
        keep_lim = math.ceil(q * buf)
        # 지난 회차 편입 종목 중 순위 한도 안에 있는 것을 순위 높은 순으로 q개까지 유지
        kept = gu[gu.index.isin(prev_codes) & (gu['rank'] <= keep_lim)].head(q)
        # 남는 자리는 유지 종목을 뺀 나머지에서 순위 순으로 채운다
        newc = gu.drop(kept.index).head(q - len(kept))
        picked += [kept, newc]
    sel = pd.concat(picked).drop(columns='rank')
    # 산업군에 후보가 모자라 못 채운 자리는 남은 종목 중 시총 순
    short = N - len(sel)
    if short > 0:
        sel = pd.concat([sel, univ.drop(sel.index).head(short)])
    return sel.sort_values('mcap', ascending=False)

hist['E_quota_buffer'] = {}
prev = set()
for _, r in REB.iterrows():
    univ = get_universe(r['D'])
    if len(univ) < 15:
        continue
    sel = select_stocks_buffer(univ, QUOTA_10, prev)
    w_r = sel['mcap'] / sel['mcap'].sum()
    w_c = calculate_capped_weight(sel['mcap'])
    hist['E_quota_buffer'][r['D']] = dict(impl=r['impl'], raw=w_r, w=w_c)
    prev = set(sel.index)

# C 와 E 의 구조 지표 비교
cmp_ = pd.DataFrame({k: summarize(hist[k]) for k in ['C_top10_quota', 'E_quota_buffer']}).round(3)
print(cmp_)

# idx_weight_hist 를 E 까지 포함해서 다시 저장 (Day 3 에서 읽는다)
rows = []
for k, h in hist.items():
    for d, x in h.items():
        for code, wt in x['w'].items():
            rows.append((k, d, x['impl'], code, float(wt)))
pd.DataFrame(rows, columns=['variant', 'D', 'impl', '종목코드', 'weight']) \
  .to_sql('idx_weight_hist', engine, if_exists='replace', index=False)
print('idx_weight_hist 저장 완료:', sorted(hist.keys()))