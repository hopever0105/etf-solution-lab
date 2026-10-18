#%%
import pandas as pd
from sqlalchemy import create_engine
# 비밀번호는 코드에 직접 쓰지 말고 환경변수로 받는 것을 권합니다
import os
engine = create_engine(f"mysql+pymysql://root:{os.environ['DB_PW']}@127.0.0.1/stock_db")
tables = pd.read_sql("SHOW TABLES", engine)
print(tables)
for t in tables.iloc[:, 0]:
    print(t)
    print(pd.read_sql(f"SHOW COLUMNS FROM `{t}`", engine)[['Field', 'Type']])
    
    #%%
import os
import pandas as pd
from sqlalchemy import create_engine

# 비밀번호는 코드에 직접 쓰지 말고 환경변수로 받습니다
engine = create_engine(f"mysql+pymysql://root:{os.environ['DB_PW']}@127.0.0.1/stock_db")

# 1) kor_ticker가 시점별 이력인지, 한 시점뿐인지
q1 = """
SELECT COUNT(DISTINCT 기준일) AS n_dates, MIN(기준일) AS first_d, MAX(기준일) AS last_d
FROM kor_ticker
"""
print(pd.read_sql(q1, engine))

# 2) kor_price 기간과 종목 수
q2 = """
SELECT MIN(날짜) AS first_d, MAX(날짜) AS last_d, COUNT(DISTINCT 종목코드) AS n_tickers
FROM kor_price
"""
print(pd.read_sql(q2, engine))

# 3) kor_value 지표 종류와 kor_sector 업종 종류
print(pd.read_sql("SELECT DISTINCT 지표 FROM kor_value", engine))
print(pd.read_sql("SELECT DISTINCT IDX_CD, SEC_NM_KOR FROM kor_sector", engine))

# 4) 에너지·나스닥·환율 후보가 있는지 (fdr_us_price, global_price, tv_us_price)
syms = "('USO','UNG','CL=F','NG=F','QQQ','SOXX','SMH','^IXIC','KRW=X','XLE')"
for t, col in [('fdr_us_price', 'Symbol'), ('global_price', 'ticker'), ('tv_us_price', 'Symbol')]:
    q = f"SELECT {col} AS sym, MIN(Date) AS first_d, MAX(Date) AS last_d FROM {t} WHERE {col} IN {syms} GROUP BY {col}"
    print(t)
    print(pd.read_sql(q, engine))

# 5) 이름으로 찾기 (% 문자는 %%로 씁니다)
q5 = """
SELECT Symbol, Name FROM global_ticker
WHERE Name LIKE '%%Oil%%' OR Name LIKE '%%Natural Gas%%' OR Name LIKE '%%Nasdaq%%'
"""
print(pd.read_sql(q5, engine))

#%% 지수 규칙 초안 (가칭: AI·반도체 에너지 페어 지수)
"""
[출처 표기] KEDI = KEDI 한국AI소프트웨어 방법론, WISE = WISE 삼성그룹밸류, 자체 = 우리가 직접 정한 규칙

1. 기준일/기준값   : 자체 (예: 2022-06-30 = 1,000. 시작일은 데이터 기간 보고 확정)
2. 유니버스        : 자체 (kor_sector의 IT, 산업재, 유틸리티 중 AI·반도체·전력기기 후보)
3. 선정 필터       : KEDI (시총 3,000억 이상, 3개월 일평균 거래대금 10억 이상)
4. 편입 종목 수    : KEDI (최대 15개) - 자체로 10개로 바꿀지 결정
5. 비중            : KEDI (시총 가중, 단일 종목 25% 상한, 초과분은 나머지에 비례 재분배)
6. 정기변경        : KEDI (분기 마지막 영업일 D에 선정, D+3에 시행)
7. 수시변경(선택)  : KEDI (3영업일 연속 30% 초과 시 25%로 조정)
8. 지수 연속성     : WISE (기준시가총액 B 조정) / KEDI (보유수량 Q 고정 방식)
9. 에너지 바스켓   : 자체 (CL, NG 선물. 롤 규칙 A 근월물 / B 차월물 / C 분산 롤을 비교)
10. 결합 비중      : 자체 (주식 : 에너지 = 고정 비중 vs 변동성 기준, 실험)
"""

#%% 셀 A. DB 점검 (수정주가, 주식수 계정, 업종, 후보군)
import os
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(f"mysql+pymysql://root:{os.environ['DB_PW']}@127.0.0.1/stock_db")

# A-1) kor_fs에 주식수·자본금 관련 계정이 있는지 (% 문자는 %%로 씁니다)
q1 = """
SELECT DISTINCT 계정 FROM kor_fs
WHERE 계정 LIKE '%%주식%%' OR 계정 LIKE '%%자본금%%'
"""
print(pd.read_sql(q1, engine))

# A-2) fdr_kr_ticker 업종/산업 중 반도체·전기 관련
q2 = """
SELECT 업종, 산업, COUNT(*) AS n FROM fdr_kr_ticker
WHERE 업종 LIKE '%%반도체%%' OR 산업 LIKE '%%반도체%%'
   OR 업종 LIKE '%%전기%%' OR 산업 LIKE '%%전기%%'
GROUP BY 업종, 산업
ORDER BY n DESC
"""
print(pd.read_sql(q2, engine))

# A-3) kor_price가 수정주가인지: 일간 변동이 비정상적으로 큰 날 (몇 분 걸릴 수 있음)
px = pd.read_sql("SELECT 날짜, 종목코드, 종가 FROM kor_price", engine)
px = px.sort_values(['종목코드', '날짜'])
px['ret'] = px.groupby('종목코드')['종가'].pct_change()
jump = px[(px['ret'] < -0.45) | (px['ret'] > 0.9)]
print(len(jump), jump['종목코드'].nunique())
print(jump.head(20))

# A-4) 후보군 크기: IT, 산업재, 유틸리티 (kor_ticker는 최신 기준일만)
q4 = """
SELECT s.CMP_CD AS 종목코드, s.CMP_KOR AS 종목명, s.SEC_NM_KOR AS 업종, t.시가총액, t.종가
FROM kor_sector s
JOIN kor_ticker t ON t.종목코드 = s.CMP_CD
WHERE s.기준일 = (SELECT MAX(기준일) FROM kor_sector)
  AND t.기준일 = (SELECT MAX(기준일) FROM kor_ticker)
  AND s.SEC_NM_KOR IN ('IT', '산업재', '유틸리티')
"""
cand = pd.read_sql(q4, engine)
cand['주식수'] = cand['시가총액'] / cand['종가']     # 현재 시총÷현재 종가로 주식수 근사
print(cand.groupby('업종').size())
print(len(cand))
print(cand.sort_values('시가총액', ascending=False).head(10))



#%% 셀 C-2. 산업별 종목 수와 시총 (후보군 산업을 고르기 위한 목록)
q = """
SELECT 산업, COUNT(*) AS 종목수, SUM(시가총액) AS 시총합
FROM fdr_kr_ticker
WHERE 기준일 = (SELECT MAX(기준일) FROM fdr_kr_ticker)
GROUP BY 산업
ORDER BY 시총합 DESC
LIMIT 40
"""
print(pd.read_sql(q, engine).to_string())

#%% 셀 C-3. 후보 산업별 시총 상위 종목 확인
cand_ind = [
    '통신 및 방송 장비 제조업', '반도체 제조업', '전자부품 제조업',
    '특수 목적용 기계 제조업', '일반 목적용 기계 제조업',
    '전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업',
    '절연선 및 케이블 제조업', '전기업', '일차전지 및 이차전지 제조업',
    '자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업',
    '컴퓨터 프로그래밍, 시스템 통합 및 관리업', '소프트웨어 개발 및 공급업',
    '전기 통신업',
]

q = """
SELECT 산업, 종목코드, 종목명, 시가총액
FROM fdr_kr_ticker
WHERE 기준일 = (SELECT MAX(기준일) FROM fdr_kr_ticker)
"""
df = pd.read_sql(q, engine)

for ind in cand_ind:
    sub = df[df['산업'] == ind].sort_values('시가총액', ascending=False)
    print('==', ind, '/ 종목수', len(sub))
    print(sub[['종목코드', '종목명', '시가총액']].head(8).to_string(index=False))

# 산업이 None인 종목은 무엇인지
print('== 산업 None')
print(df[df['산업'].isna()].sort_values('시가총액', ascending=False)
      [['종목코드', '종목명', '시가총액']].head(10).to_string(index=False))

#%% 셀 C-4. 후보군 풀 (산업 세트 + 보통주 + 예외 리스트)
import os
from urllib.parse import quote_plus
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(f"mysql+pymysql://root:{quote_plus(os.environ['DB_PW'])}@127.0.0.1:3306/stock_db")

INCLUDE_IND = [
    '반도체 제조업', '통신 및 방송 장비 제조업', '전자부품 제조업', '특수 목적용 기계 제조업',
    '전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업', '절연선 및 케이블 제조업', '전기업',
    '자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업',
    '컴퓨터 프로그래밍, 시스템 통합 및 관리업',
]
# 선택 산업(필요하면 위 리스트에 옮기세요):
#   '일차전지 및 이차전지 제조업', '전기 통신업', '소프트웨어 개발 및 공급업'

# 산업 분류로는 들어오지만 AI 인프라와 거리가 먼 종목 (직접 판단. 보고서에 명시)
EXCLUDE_CODES = {
    '066570': 'LG전자', '489790': '한화비전', '272210': '한화시스템', '000150': '두산',
    '277810': '레인보우로보틱스', '241560': '두산밥캣', '267270': 'HD건설기계',
    '322000': 'HD현대에너지솔루션',
}
# 산업 분류 밖이지만 편입하는 종목
INCLUDE_CODES = {'034020': '두산에너빌리티'}

MIN_CAP = 1e11     # 1,000억 원 (후보 풀 사전 필터. 실제 시총 3,000억 기준은 get_universe에서 적용)

q = """
SELECT 종목코드, 종목명, 시장구분, 산업, 시가총액, 종목구분
FROM fdr_kr_ticker
WHERE 기준일 = (SELECT MAX(기준일) FROM fdr_kr_ticker)
"""
df = pd.read_sql(q, engine)
print(df['종목구분'].value_counts(dropna=False))      # 종목구분 값이 무엇인지 확인

is_common = df['종목코드'].str[-1] == '0'            # 코드 끝자리가 0이 아니면 우선주로 보고 제외
in_set = df['산업'].isin(INCLUDE_IND) | df['종목코드'].isin(INCLUDE_CODES)
not_excl = ~df['종목코드'].isin(EXCLUDE_CODES)
big = df['시가총액'] >= MIN_CAP

pool = df[is_common & in_set & not_excl & big].copy()
pool = pool.sort_values('시가총액', ascending=False).reset_index(drop=True)
pool['w_preview'] = pool['시가총액'] / pool['시가총액'].sum()    # 캡 적용 전 비중 미리보기

print(len(pool))
print(pool.groupby('산업').size())
print(pool[['종목코드', '종목명', '산업', '시가총액', 'w_preview']].head(25).to_string())

# 다음 단계(get_universe)에서 쓰도록 DB에 저장 (project 전용 테이블)
pool.drop(columns=['w_preview']).to_sql('idx_candidate', engine, if_exists='replace', index=False)

#%% 셀 D. 가설 검증 초안 (에너지 급등기에 AI·반도체 바스켓은 어땠나)
import numpy as np
import pandas as pd

# 1) 바스켓: 후보 풀 시총 상위 15개 동일가중 (초안용)
pool = pd.read_sql("SELECT 종목코드, 종목명, 시가총액 FROM idx_candidate", engine)
top = pool.sort_values('시가총액', ascending=False).head(15)['종목코드'].tolist()
codes = ",".join(f"'{c}'" for c in top)

px = pd.read_sql(f"SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({codes})", engine)
px['날짜'] = pd.to_datetime(px['날짜'])
px = px.pivot(index='날짜', columns='종목코드', values='종가').sort_index()

ret = px.pct_change()
ret = ret.where(ret.abs() <= 0.31)      # 일일 상하한 30%를 넘는 값은 분할·감자 등으로 가격이 끊긴 날로 보고 제외
r = ret.mean(axis=1).fillna(0)
basket = (1 + r).cumprod()

# 2) 에너지·나스닥 (tv_futures_price)
fut = pd.read_sql("SELECT Date, Symbol, Close FROM tv_futures_price "
                  "WHERE Symbol IN ('CL1!','NG1!','IXIC')", engine)
fut['Date'] = pd.to_datetime(fut['Date'])
fut = fut.pivot(index='Date', columns='Symbol', values='Close').sort_index()

# 3) 주간 수익률로 맞춤
lv = pd.concat([basket.rename('BASKET'), fut], axis=1).dropna(how='all')
lv = lv.loc['2021-10-12':]
wk = lv.resample('W-FRI').last().ffill().pct_change().dropna()
print('주 수:', len(wk))
print('주간 상관\n', wk.corr().round(2))


# 4) 에너지 급등 주(상위 10%)에 바스켓은 어땠나
def cond(x_col, y_col, q=0.10, side='top'):
    if side == 'top':
        m = wk[x_col] >= wk[x_col].quantile(1 - q)
    else:
        m = wk[x_col] <= wk[x_col].quantile(q)
    return wk.loc[m, y_col].mean(), int(m.sum())


for e in ['CL1!', 'NG1!']:
    mean_, n = cond(e, 'BASKET', 0.10, 'top')
    print(e, '급등 주 바스켓 평균 주간수익률:', round(mean_ * 100, 2), '% / 주 수', n,
          '/ 전체 평균', round(wk['BASKET'].mean() * 100, 2), '%')

# 5) 나스닥이 크게 빠진 주(하위 10%)에 원유·가스는 어땠나 (나스닥 급락 시 원유 상승 가설)
for e in ['CL1!', 'NG1!']:
    mean_, n = cond('IXIC', e, 0.10, 'bottom')
    print('나스닥 급락 주', e, '평균 주간수익률:', round(mean_ * 100, 2), '% / 주 수', n,
          '/ 전체 평균', round(wk[e].mean() * 100, 2), '%')

# 6) 52주 롤링 상관 (구간별로 부호가 바뀌는지)
for e in ['CL1!', 'NG1!']:
    rc = wk['BASKET'].rolling(52).corr(wk[e])
    print(e, '52주 롤링 상관 최소/최대:', round(rc.min(), 2), round(rc.max(), 2))
    
    #%% 셀 D-2. 서브바스켓(칩 / 전력), 월간, 구간별 재검증
pool = pd.read_sql("SELECT 종목코드, 종목명, 산업, 시가총액 FROM idx_candidate", engine)

power_ind = ['전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업', '절연선 및 케이블 제조업', '전기업']
power = pool[pool['산업'].isin(power_ind) | pool['종목코드'].eq('034020')]   # 두산에너빌리티 포함
chip = pool[pool['산업'].eq('반도체 제조업') | pool['종목코드'].eq('005930')]  # 삼성전자 포함


def make_basket(sub, n=8):
    codes_ = sub.sort_values('시가총액', ascending=False).head(n)['종목코드'].tolist()
    s = ",".join(f"'{c}'" for c in codes_)
    p = pd.read_sql(f"SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({s})", engine)
    p['날짜'] = pd.to_datetime(p['날짜'])
    p = p.pivot(index='날짜', columns='종목코드', values='종가').sort_index()
    rt = p.pct_change()
    rt = rt.where(rt.abs() <= 0.31)       # 가격이 끊긴 날 제외
    return (1 + rt.mean(axis=1).fillna(0)).cumprod()


lv2 = pd.concat([make_basket(chip).rename('CHIP'), make_basket(power).rename('POWER'),
                 fut[['CL1!', 'NG1!']]], axis=1)
lv2 = lv2.loc['2021-10-12':]

# 주간과 월간 상관 (월간은 pandas 버전에 따라 경고가 뜰 수 있는데 무시해도 됩니다)
for label, rule in [('주간', 'W-FRI'), ('월간', 'M')]:
    x = lv2.resample(rule).last().ffill().pct_change().dropna()
    print(label, '표본', len(x))
    print(x.corr().round(2).loc[['CHIP', 'POWER'], ['CL1!', 'NG1!']])

# 구간별 (2022 에너지 쇼크 전후) 주간 상관
x = lv2.resample('W-FRI').last().ffill().pct_change().dropna()
for a, b in [('2021-10-12', '2022-12-31'), ('2023-01-01', '2026-10-16')]:
    print(a, '~', b, '표본', len(x.loc[a:b]))
    print(x.loc[a:b].corr().round(2).loc[['CHIP', 'POWER'], ['CL1!', 'NG1!']])
    
    #%% D-3. 누적수익률 + 52주 롤링 상관 차트
# 셀 D에서 만든 lv, wk 를 그대로 사용한다 (BASKET, CL1!, NG1!, IXIC)
# 필요 패키지: matplotlib (ta_env 에 이미 있을 가능성이 높음, 확인 안 됨)
#   없으면 Anaconda Prompt 에서  conda activate ta_env  →  pip install matplotlib
import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams['font.family'] = 'Malgun Gothic'   # 한글 폰트 (Windows)
mpl.rcParams['axes.unicode_minus'] = False       # 마이너스 기호 깨짐 방지

# 서로 단위가 다른 시리즈라 이중축 대신 시작점을 100으로 맞춘 한 축을 쓴다
lv2 = lv.ffill().dropna()
reb = lv2 / lv2.iloc[0] * 100

# 색은 시리즈별로 고정한다
COLORS = {'BASKET': '#2a78d6', 'IXIC': '#6250d6', 'CL1!': '#eb6834', 'NG1!': '#1baf7a'}
LABELS = {'BASKET': 'AI·반도체·전력 바스켓(시총 상위 15, 동일가중)',
          'IXIC': '나스닥 종합', 'CL1!': 'WTI 원유 근월물', 'NG1!': '천연가스 근월물'}

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                               gridspec_kw={'height_ratios': [3, 2]})

# 위 패널: 누적수익률 (시작=100)
for c in ['BASKET', 'IXIC', 'CL1!', 'NG1!']:
    if c in reb.columns:
        ax1.plot(reb.index, reb[c], color=COLORS[c], lw=2, label=LABELS[c])
ax1.axhline(100, color='#999999', lw=0.8, ls='--')
ax1.set_title('누적수익률 (시작일=100)', loc='left', fontsize=12)
ax1.legend(loc='upper left', frameon=False, fontsize=9)

# 아래 패널: 바스켓 주간수익률과 에너지 선물의 52주 롤링 상관
for c in ['CL1!', 'NG1!']:
    if c in wk.columns:
        rc = wk['BASKET'].rolling(52).corr(wk[c])
        ax2.plot(rc.index, rc, color=COLORS[c], lw=2, label=f'바스켓 vs {LABELS[c]}')
ax2.axhline(0, color='#999999', lw=0.8)
ax2.set_ylim(-1, 1)
ax2.set_title('52주 롤링 상관계수 (주간수익률)', loc='left', fontsize=12)
ax2.legend(loc='upper left', frameon=False, fontsize=9)

# 격자는 약하게, 테두리는 최소로
for ax in (ax1, ax2):
    ax.grid(True, color='#e5e5e5', lw=0.6)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)

fig.tight_layout()
fig.savefig('day1_chart.png', dpi=150)
plt.show()

# 주의: CL1!, NG1! 는 연속선물이라 롤오버 날짜에 가격 점프가 섞여 있다.
#       차트는 방향 확인용이고, 롤 규칙별 비교는 Day 4에서 한다.

