#%% 0. 안내 + 실행 플래그
# 먼저 day2_universe_and_cap.py 를 보고 오세요. 이미 DB에 데이터가 있으면 여기서부터 진행하세요.
# 실행 순서: 국내 주식 데이터 수집.py -> day1_data_check_and_hypothesis.py -> day2_universe_and_cap.py -> 이 파일
#
# 환경: conda activate ta_env   (Anaconda Prompt)
#   Spyder: Tools > Preferences > Python interpreter > Use the following
#           Python interpreter 에서 ta_env 의 python.exe 선택 후 Spyder 재시작
#   패키지가 없으면 ta_env 를 켠 상태에서:
#   pip install pandas numpy sqlalchemy pymysql matplotlib
#
# DB 비밀번호는 환경변수 DB_PW 에서 읽는다 (Windows: setx DB_PW "비밀번호", 설정 후 Spyder 재시작)
import os
import runpy
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine

RUN_DOWNLOAD = False   # True: day2 파일을 실행해서 idx_weight_hist 를 새로 만든다
COLLECT_FILES = ['day2_universe_and_cap.py']

DB_USER = os.environ.get('DB_USER', 'root')
DB_PW   = os.environ['DB_PW']
engine  = create_engine(
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PW)}@127.0.0.1:3306/stock_db")

if RUN_DOWNLOAD:
    for f in COLLECT_FILES:
        print('실행:', f)
        runpy.run_path(f)

NEED_TABLES = ['kor_price', 'idx_candidate', 'idx_weight_hist']
have = pd.read_sql("SHOW TABLES", engine).iloc[:, 0].tolist()
missing = [t for t in NEED_TABLES if t not in have]
if missing:
    raise RuntimeError(f"DB에 없는 테이블: {missing}\n"
                       f"RUN_DOWNLOAD = True 로 바꿔서 다시 실행하거나, "
                       f"위 안내의 파일을 먼저 실행하세요.")
print('필요 테이블 확인 완료:', NEED_TABLES)


#%% 1. 파라미터
BASE       = 1000     # 기준 지수 (첫 반영일 직전 거래일 = 1000)
CAP        = 0.25     # 단일 종목 비중 상한
TRIG       = 0.30     # 수시변경 발동 비중 (KEDI: 30% 초과가 3일 연속이면 25%로 재조정)
TRIG_DAYS  = 3
JUMP_TH    = 0.31     # Day 2 와 같은 가격 단절 기준
MAIN       = 'E_quota_buffer'           # 주 사양 (Day 3 에서 C -> E 로 변경, 구조 지표 근거)          # 주 사양
ADHOC_OFF  = ['D_quota_nocap']          # D 는 캡이 없는 비교용이라 수시변경을 끈다


#%% 2. 데이터 적재 (편입 비중 이력 + 가격)
wh = pd.read_sql("SELECT variant, D, impl, 종목코드, weight FROM idx_weight_hist",
                 engine, parse_dates=['D', 'impl'])
wh['종목코드'] = wh['종목코드'].astype(str).str.zfill(6)
print('변형:', sorted(wh['variant'].unique()))

codes = "','".join(sorted(wh['종목코드'].unique()))
sql = f"""
SELECT 날짜, 종목코드, 종가
FROM kor_price
WHERE 종목코드 IN ('{codes}')
  AND 날짜 >= '2021-10-01'
"""
raw = pd.read_sql(sql, engine, parse_dates=['날짜'])
raw['종목코드'] = raw['종목코드'].astype(str).str.zfill(6)
px_raw = raw.pivot(index='날짜', columns='종목코드', values='종가').sort_index()

# Day 2 와 같은 방식으로 가격 단절(액면분할 등)을 보정한다.
# 일 변동이 ±31% 를 넘는 날은 그날 수익률을 0 으로 두고 누적해 보정가격을 만든다.
ret   = px_raw.pct_change(fill_method=None)
event = ret.abs() > JUMP_TH
adj   = (1 + ret.where(~event, 0.0).fillna(0)).cumprod().where(px_raw.notna())
# 거래정지일처럼 가격이 비는 날은 직전 가격을 이어서 쓴다
px = adj.ffill()

print('가격 기간:', px.index.min().date(), '~', px.index.max().date(), '/ 종목 수:', px.shape[1])
print('가격 단절 처리:', int(event.sum().sum()), '건')


#%% 3. calculate_capped_weight(): Day 2 와 같은 함수 (수시변경 때 다시 쓴다)
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
        w[free] = mcap[free] / mcap[free].sum() * (1 - cap * capped.sum())
    return w


#%% 4. backtest_engine(): 기준시가총액 방식의 일별 지수
# 지수 = 지수시가총액 M_t / 기준시가총액 B_t x 기준지수
#   M_t = sum(P_i,t x Q_i)   Q 는 리밸런싱 사이에 고정된 수량
# 리밸런싱(구성 종목·수량이 바뀔 때)에는 지수가 끊기지 않도록 B 를 조정한다.
#   B_new = B_old x (새 수량의 시가총액 / 옛 수량의 시가총액)   (둘 다 직전 거래일 종가 기준)
# 수량은 직전 거래일(ref) 종가 기준으로 Q = w / P_ref 로 정한다. (w 는 결정일에 정한 목표 비중)
# 정기 리밸런싱은 반영일(D+3)에 적용하고, 수시변경은 아래 가정으로 처리한다.
#   - 최대 비중이 TRIG 를 TRIG_DAYS 일 연속 넘으면, 그날 종가의 비중으로 calculate_capped_weight()를 돌려
#     다음 거래일에 반영한다. (반영일은 문서에서 확인 안 된 부분이라 내가 정한 가정)
def backtest_engine(weights, px, base=BASE, adhoc=True, trig=TRIG, n_days=TRIG_DAYS, cap=CAP):
    dates = px.index
    sched = {s: g.set_index('종목코드')['weight'] for s, g in weights.groupby('impl')}
    pos0 = dates.get_loc(min(sched))
    level = {dates[pos0 - 1]: float(base)}      # 첫 반영일 직전 거래일이 기준일
    Qs, maxw, reb_log, events = {}, {}, [], []
    Q, B, streak, pending = None, None, 0, None

    for i in range(pos0, len(dates)):
        t, ref = dates[i], dates[i - 1]

        # 오늘 반영할 비중: 정기 리밸런싱이 우선, 없으면 어제 예약된 수시변경
        w, kind = None, None
        if t in sched:
            w, kind, pending = sched[t], '정기', None
        elif pending is not None:
            w, kind, pending = pending, '수시', None

        if w is not None:
            p_ref = px.loc[ref, w.index]
            if p_ref.isna().any():
                raise ValueError(f'{ref.date()} 가격이 없는 종목: {list(p_ref[p_ref.isna()].index)}')
            Q_new = w / p_ref
            M_new = float((p_ref * Q_new).sum())               # = 비중 합 = 1
            if Q is None:
                B = M_new / base                               # 첫 구성: 기준일 지수가 base 가 되게
            else:
                M_old = float((px.loc[ref, Q.index] * Q).sum())
                B = B * M_new / M_old                          # 연속성 유지
            err = abs(M_new / B - level[ref])                  # 리밸런싱 전후 지수 차이 (0 이어야 함)
            Q = Q_new
            streak = 0
            reb_log.append(dict(날짜=t, 구분=kind, 종목수=len(w), 연속성오차=err))

        val = px.loc[t, Q.index] * Q
        level[t] = float(val.sum() / B)
        Qs[t] = Q

        # 보유 수량이 고정이라 비중은 가격에 따라 흘러간다 (드리프트)
        wd = val / val.sum()
        maxw[t] = float(wd.max())
        if adhoc:
            streak = streak + 1 if wd.max() > trig else 0
            if streak >= n_days:
                pending = calculate_capped_weight(wd, cap)
                events.append(dict(날짜=t, 종목코드=wd.idxmax(), 비중=float(wd.max())))
                streak = 0

    return dict(level=pd.Series(level), Qs=Qs, maxw=pd.Series(maxw),
                reb=pd.DataFrame(reb_log), events=pd.DataFrame(events))


#%% 5. 검증용: 연쇄식(KEDI식)으로 다시 계산해서 기준시가총액식과 비교
# I_t = I_(t-1) x sum(P_t x Q) / sum(P_(t-1) x Q)   (Q 는 그날 유효한 수량)
# 두 방식이 같으면 B 조정으로 연속성이 제대로 유지된 것이다.
def chain_check(res, px):
    lv = res['level']
    dates = lv.index
    chain = [lv.iloc[0]]
    for i in range(1, len(dates)):
        t, prev = dates[i], dates[i - 1]
        Q = res['Qs'][t]
        chain.append(chain[-1] * (px.loc[t, Q.index] * Q).sum() / (px.loc[prev, Q.index] * Q).sum())
    chain = pd.Series(chain, index=dates)
    return float((chain - lv).abs().max())


#%% 6. 모든 변형 실행 + 저장
results = {}
for v in sorted(wh['variant'].unique()):
    g = wh[wh['variant'] == v]
    res = backtest_engine(g, px, adhoc=(v not in ADHOC_OFF))
    res['chain_err'] = chain_check(res, px)
    results[v] = res

chk = pd.DataFrame({
    v: {
        '지수 시작': r['level'].index[0].date(),
        '지수 종료': r['level'].index[-1].date(),
        '정기 리밸런싱 횟수': int((r['reb']['구분'] == '정기').sum()),
        '수시변경 횟수': int((r['reb']['구분'] == '수시').sum()),
        '연속성 오차 최대': r['reb']['연속성오차'].max(),
        '연쇄식과 최대 차이': r['chain_err'],
        '드리프트 최대비중': round(r['maxw'].max(), 3),
    } for v, r in results.items()
})
print(chk)

# 지수 시계열 저장 (Day 4 에서 읽는다)
rows = []
for v, r in results.items():
    for d, x in r['level'].items():
        rows.append((v, d, float(x)))
pd.DataFrame(rows, columns=['variant', '날짜', '지수']) \
  .to_sql('idx_level', engine, if_exists='replace', index=False)
print('idx_level 저장 완료')


#%% 7. 수시변경 발생 내역 (캡 드리프트)
names = pd.read_sql("SELECT 종목코드, 종목명 FROM idx_candidate", engine)
names['종목코드'] = names['종목코드'].astype(str).str.zfill(6)
names = names.set_index('종목코드')['종목명']

for v, r in results.items():
    ev = r['events']
    print('---', v, '수시변경', len(ev), '회 ---')
    if len(ev):
        ev = ev.copy()
        ev['종목명'] = ev['종목코드'].map(names)
        ev['비중'] = (ev['비중'] * 100).round(1)
        print(ev[['날짜', '종목명', '비중']].to_string(index=False))


#%% 8. 성과 참고표 (선택에는 쓰지 않는다. 주 사양은 Day 2 에서 이미 고정)
# 무위험수익률은 0 으로 둔 단순 샤프다. K-Sharpe(CD91 초과 로그수익률)는 Day 4 에서 맞춘다.
def perf_summary(lv, rf=0.0):
    r = lv.pct_change().dropna()
    yrs = (lv.index[-1] - lv.index[0]).days / 365.25
    vol = r.std() * np.sqrt(252)
    return pd.Series({
        '누적수익률': lv.iloc[-1] / lv.iloc[0] - 1,
        'CAGR': (lv.iloc[-1] / lv.iloc[0]) ** (1 / yrs) - 1,
        '연변동성': vol,
        'MDD': (lv / lv.cummax() - 1).min(),
        'Sharpe(rf=0)': (r.mean() * 252 - rf) / vol,
    })

perf = {v: perf_summary(r['level']) for v, r in results.items()}

# 비교용 KOSPI (Day 1 에서 tv_futures_price 에 저장한 심볼, 가격지수)
kos = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'KOSPI'",
                  engine, parse_dates=['Date']).set_index('Date')['Close'].sort_index()
base_idx = results[MAIN]['level'].index
kos = kos.reindex(base_idx).ffill()
if kos.notna().all():
    perf['KOSPI'] = perf_summary(kos / kos.iloc[0] * BASE)
else:
    print('KOSPI 데이터가 지수 기간을 덮지 못함 (비교에서 제외)')

print(pd.DataFrame(perf).T.round(3))

# 연도별 수익률 (첫 해와 마지막 해는 부분 기간)
yr = {}
for v, r in results.items():
    lv = r['level']
    ann = lv.groupby(lv.index.year).last()
    prev = ann.shift(1)
    prev.iloc[0] = lv.iloc[0]
    yr[v] = ann / prev - 1
print((pd.DataFrame(yr) * 100).round(1))


#%% 9. 차트: 지수 비교 + 주 사양 낙폭
import matplotlib.pyplot as plt
import matplotlib as mpl
mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

COLORS = {'A_top15': '#1baf7a', 'B_top10': '#eda100', 'C_top10_quota': '#2a78d6',
          'D_quota_nocap': '#e34948', 'E_quota_buffer': '#6250d6'}

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                               gridspec_kw={'height_ratios': [3, 1.6]})
for v, r in results.items():
    ax1.plot(r['level'].index, r['level'], color=COLORS.get(v, '#999999'),
             lw=2.2 if v == MAIN else 1.2, label=v)
if kos.notna().all():
    ax1.plot(kos.index, kos / kos.iloc[0] * BASE, color='#888888', lw=1.2, ls='--', label='KOSPI')
ax1.axhline(BASE, color='#bbbbbb', lw=0.8)
ax1.set_title('지수 비교 (기준일=1000, 가격지수)', loc='left', fontsize=12)
ax1.legend(loc='upper left', frameon=False, fontsize=9)

lvm = results[MAIN]['level']
ax2.fill_between(lvm.index, (lvm / lvm.cummax() - 1) * 100, 0, color='#2a78d6', alpha=0.25, lw=0)
ax2.plot(lvm.index, (lvm / lvm.cummax() - 1) * 100, color='#2a78d6', lw=1.2)
ax2.set_title(f'낙폭 (%) - {MAIN}', loc='left', fontsize=12)

for ax in (ax1, ax2):
    ax.grid(True, color='#e5e5e5', lw=0.6)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig('day3_index_chart.png', dpi=150)
plt.show()

#%% 9-2. C 와 E 비교 (성과표, 구성 차이, 차트)
cv = ['C_top10_quota', 'E_quota_buffer']
lv_c, lv_e = results[cv[0]]['level'], results[cv[1]]['level']

# 1) 성과 비교표
tbl = pd.DataFrame({'C': perf_summary(lv_c), 'E': perf_summary(lv_e)})
tbl['E-C'] = tbl['E'] - tbl['C']
print(tbl.round(3))

# 2) 연도별 수익률 (%)
def yearly(lv):
    ann = lv.groupby(lv.index.year).last()
    prev = ann.shift(1)
    prev.iloc[0] = lv.iloc[0]
    return (ann / prev - 1) * 100
yy = pd.DataFrame({'C': yearly(lv_c), 'E': yearly(lv_e)})
yy['E-C(%p)'] = yy['E'] - yy['C']
print(yy.round(1))

# 3) 편입 종목이 서로 다른 정기 리밸런싱 회차만 출력
print('--- 구성이 다른 회차 ---')
for s, g in wh[wh['variant'] == cv[0]].groupby('impl'):
    c_set = set(g['종목코드'])
    e_set = set(wh[(wh['variant'] == cv[1]) & (wh['impl'] == s)]['종목코드'])
    if c_set != e_set:
        print(s.date(), '| C만:', [names.get(c, c) for c in sorted(c_set - e_set)],
              '| E만:', [names.get(c, c) for c in sorted(e_set - c_set)])

# 4) 마지막 날 구성 나란히 (드리프트 반영 비중 %)
def cur_w(v):
    r = results[v]
    last = r['level'].index[-1]
    Q = r['Qs'][last]
    val = px.loc[last, Q.index] * Q
    return (val / val.sum() * 100).round(1)
side = pd.concat([cur_w(cv[0]).rename('C'), cur_w(cv[1]).rename('E')], axis=1).fillna(0)
side.index = [names.get(c, c) for c in side.index]
print(side.sort_values('E', ascending=False))

# 5) 차트: 지수, E/C 비율, 낙폭
import matplotlib.pyplot as plt
import matplotlib as mpl
mpl.rcParams['font.family'] = 'Malgun Gothic'
mpl.rcParams['axes.unicode_minus'] = False

fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(11, 10), sharex=True,
                                 gridspec_kw={'height_ratios': [3, 1.3, 1.6]})
a1.plot(lv_c.index, lv_c, color='#2a78d6', lw=1.8, label='C (버퍼 없음)')
a1.plot(lv_e.index, lv_e, color='#eb6834', lw=1.8, label='E (버퍼 1.5, 주 사양)')
a1.set_title('지수 (기준일=1000)', loc='left', fontsize=12)
a1.legend(loc='upper left', frameon=False, fontsize=9)

a2.plot(lv_e.index, lv_e / lv_c, color='#6250d6', lw=1.5)
a2.axhline(1, color='#999999', lw=0.8)
a2.set_title('E ÷ C  (1보다 크면 E가 앞섬)', loc='left', fontsize=12)

a3.plot(lv_c.index, (lv_c / lv_c.cummax() - 1) * 100, color='#2a78d6', lw=1.3, label='C')
a3.plot(lv_e.index, (lv_e / lv_e.cummax() - 1) * 100, color='#eb6834', lw=1.3, label='E')
a3.set_title('낙폭 (%)', loc='left', fontsize=12)
a3.legend(loc='lower left', frameon=False, fontsize=9)

for ax in (a1, a2, a3):
    ax.grid(True, color='#e5e5e5', lw=0.6)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig('day3_C_vs_E.png', dpi=150)
plt.show()

#%% 10. 주 사양 현재 구성 (드리프트 반영 비중)
r = results[MAIN]
last = r['level'].index[-1]
Q = r['Qs'][last]
val = px.loc[last, Q.index] * Q
cur = pd.DataFrame({'종목명': names.reindex(Q.index), '현재비중(%)': (val / val.sum() * 100).round(1)})
print(last.date(), '기준')
print(cur.sort_values('현재비중(%)', ascending=False))