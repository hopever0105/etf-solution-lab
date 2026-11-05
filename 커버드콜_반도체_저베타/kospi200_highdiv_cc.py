"""코스피200 + 저베타 고배당 (+ 채권) 커버드콜: 연 15% 넘는 분배가 원금을 지키며 가능한가 (포트폴리오용, 실매매 없음)

1단계 스크리닝: 코스피200(KODEX 200) 대비 베타·상관·배당·거래대금·코스피200 급락 때 성과
          → 연배당 3% 이상, 베타 0.6 이하, 최근 1년 하루 거래대금 100억 이상, 2010년 이전 상장 종목만 바구니에
2단계 백테스트: 코스피200 부분에만 코스피200 ATM 콜 매도(월물 또는 위클리 5거래일), 블랙숄즈(σ=직전 20일 실현변동성, 하한 10%, r=3%)
  분배 방식 'all' = 프리미엄+배당 전부 분배 / 'target' = 매월 NAV의 1.25%(연 15%) 고정 분배, 남는 현금은 재투자
  채권 = KODEX 국고채3년(114260) 가격(야후에 없으면 연 3% 고정)
시세: yfinance(야후), KRX 요청 없음. 거래비용·보수·세금 미반영. 위클리 옵션은 2019년 이후 상장이지만 전 기간 가정
실행: python -I kospi200_highdiv_cc.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '코스피200_저베타고배당'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR = 0.03, 0.10
CAND = {'KT&G': '033780.KS', 'KT': '030200.KS', 'SK텔레콤': '017670.KS', 'LG유플러스': '032640.KS',
        'DB손해보험': '005830.KS', '삼성화재': '000810.KS', '현대해상': '001450.KS', '삼성생명': '032830.KS',
        'KB금융': '105560.KS', '신한지주': '055550.KS', '하나금융지주': '086790.KS', '기업은행': '024110.KS', 'BNK금융지주': '138930.KS',
        'S-Oil': '010950.KS', 'GS': '078930.KS', 'SK이노베이션': '096770.KS',
        '한국전력': '015760.KS', '한국가스공사': '036460.KS', 'POSCO홀딩스': '005490.KS',
        '유한양행': '000100.KS', '농심': '004370.KS', 'CJ제일제당': '097950.KS', '오리온홀딩스': '001800.KS',
        '현대차': '005380.KS', '기아': '000270.KS', '삼성카드': '029780.KS', '맥쿼리인프라': '088980.KS',
        '한국금융지주': '071050.KS', 'NH투자증권': '005940.KS', '삼성증권': '016360.KS'}
K200_T, BOND_T = '069500.KS', '114260.KS'

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


tick = {'K200': K200_T, **CAND}
raw = yf.download(list(tick.values()), start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
inv = {v: k for k, v in tick.items()}
close = raw['Close'].rename(columns=inv)
volu = raw['Volume'].rename(columns=inv)
divs = raw['Dividends'].rename(columns=inv).fillna(0)
ret = close.pct_change(fill_method=None)

# ---------------------------------------------------------------- 1단계 스크리닝
k_r = ret['K200']
k_w = (1 + k_r.fillna(0)).cumprod()
dd = k_w / k_w.cummax() - 1
eps, inside = [], False
for d in dd.index:
    if not inside and dd[d] <= -0.20:
        inside, start = True, k_w.loc[:d].idxmax()
    if inside and dd[d] == 0:
        eps.append((start, d))
        inside = False
if inside:
    eps.append((start, dd.index[-1]))
eps = [(s, (k_w.loc[s:e] / k_w.loc[s]).idxmin()) for s, e in eps]

rows = []
for n in CAND:
    r = ret[n]
    both = pd.concat([r, k_r], axis=1).dropna()
    if len(both) < 1000:
        continue
    beta = both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var()
    yrs = len(both) / 252
    dy = (divs[n] / close[n].shift(1)).loc[both.index].sum() / yrs
    tv = (close[n] * volu[n]).loc['2025-11-01':].mean() / 1e8
    er = []
    for s, e in eps:
        x = r.loc[s:e].dropna()
        er.append((1 + x).prod() - 1 if len(x) > 0.8 * len(k_r.loc[s:e]) else np.nan)
    kr = [(k_w.loc[e] / k_w.loc[s] - 1) for s, e in eps]
    rows.append({'종목': n, '시작': both.index[0].date(), '베타': beta, '상관': both.corr().iloc[0, 1], '연배당%': dy * 100,
                 '거래대금_억': tv, f'코스피200급락{len(eps)}번_평균%': np.nanmean(er) * 100,
                 '급락때_코스피200대비%p': np.nanmean([a - b for a, b in zip(er, kr) if not np.isnan(a)]) * 100})
scr = pd.DataFrame(rows).round(2).sort_values('연배당%', ascending=False)
scr.to_csv(OUT / '스크리닝_코스피200대비.csv', index=False, encoding='utf-8-sig')
pick = scr[(scr['연배당%'] >= 3) & (scr['베타'] <= 0.6) & (scr['거래대금_억'] >= 100) & (pd.to_datetime(scr['시작']) <= '2010-12-31')]
LOW = list(pick['종목'])

# ---------------------------------------------------------------- 2단계 백테스트
bond = yf.download(BOND_T, start='2007-01-01', end='2026-10-31', auto_adjust=True, progress=False)['Close']
bond = bond.iloc[:, 0] if isinstance(bond, pd.DataFrame) else bond
cols = ['K200'] + LOW
px = close[cols].dropna()
if bond.dropna().shape[0] > 3000:
    px = px.join(bond.rename('BOND'), how='inner')
    BOND_SRC = BOND_T
else:
    px['BOND'] = (1 + 0.03 / 252) ** np.arange(len(px))
    BOND_SRC = '연 3% 고정'
dv = divs.reindex(px.index).fillna(0)
vol20 = np.log(px['K200']).diff().rolling(20).std() * sqrt(252)
px = px.iloc[25:]
dates = px.index
rt = px.pct_change().fillna(0)
per = dates.to_period('M')
month_first = set(pd.Series(dates, index=dates).groupby(per).first())
month_last = set(pd.Series(dates, index=dates).groupby(per).last())
quarter_first = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())
mf = sorted(month_first)
exp_m = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}


def run(w_k=1.0, w_low=0.0, w_bond=0.0, k=0.0, tenor='M', dist='all', target=0.15):
    """w_*: 목표 비중(분기 리셋), k: 코스피200 부분 대비 콜 매도 비율, tenor 'M' 월물 / 'W' 5거래일, dist 'all' / 'target'"""
    val = {'K200': w_k, 'BOND': w_bond}
    for n in LOW:
        val[n] = w_low / len(LOW)
    pool = 0.0
    n_call = K = sig0 = t_exp = None
    rows, prev = [], None
    for i, d in enumerate(dates):
        prem_d = div_d = dist_d = 0.0
        if prev is not None:
            for n in val:
                if n != 'BOND' and dv.at[d, n] > 0:
                    x = val[n] * dv.at[d, n] / px.at[prev, n]
                    div_d += x
                    pool += x
                val[n] *= 1 + rt.at[d, n]
        if t_exp is not None and d == t_exp:
            val['K200'] -= n_call * max(px.at[d, 'K200'] - K, 0.0)
            n_call = K = sig0 = t_exp = None
        if d in quarter_first and prev is not None:
            tot = sum(val.values())
            val['K200'], val['BOND'] = tot * w_k, tot * w_bond
            for n in LOW:
                val[n] = tot * w_low / len(LOW)
        new = (tenor == 'M' and d in month_first) or (tenor == 'W' and i % 5 == 0)
        if k > 0 and new and t_exp is None and i < len(dates) - 1:
            sig0 = max(float(vol20[d]) if not np.isnan(vol20[d]) else SIG_FLOOR, SIG_FLOOR)
            K = px.at[d, 'K200']
            t_exp = exp_m[d] if tenor == 'M' else dates[min(i + 5, len(dates) - 1)]
            n_call = k * val['K200'] / K
            prem_d = n_call * bs_call(K, K, sig0, max((t_exp - d).days, 1) / 365)
            pool += prem_d
        liab = n_call * bs_call(px.at[d, 'K200'], K, sig0, max((t_exp - d).days, 0) / 365) if n_call else 0.0
        nav_pre = sum(val.values()) + pool - liab
        if d in month_last:
            if dist == 'all':
                dist_d, pool = pool, 0.0
            else:
                dist_d = nav_pre * target / 12
                extra = pool - dist_d  # 남으면 재투자, 모자라면 보유 자산을 팔아 채움(원금 분배)
                pool = 0.0
                tot = sum(val.values())
                for n in val:
                    val[n] += extra * val[n] / tot
        nav = nav_pre - dist_d
        rows.append((d, nav, prem_d, div_d, dist_d))
        prev = d
    df = pd.DataFrame(rows, columns=['date', 'nav', 'prem', 'div', 'dist']).set_index('date')
    r = (df['nav'] + df['dist']) / df['nav'].shift(1) - 1
    df['wealth'] = (1 + r.fillna(0)).cumprod()
    return df


def metrics(df, name):
    w, nav = df['wealth'], df['nav']
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    nb = nav.shift(1)
    return {'안': name, '연총수익%': ((w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1) * 100,
            'NAV연변화%(원금유지)': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100,
            '변동성%': w.pct_change().std() * sqrt(252) * 100, '최대낙폭%': (w / w.cummax() - 1).min() * 100,
            '연분배율%': (df['dist'] / nb).sum() / yrs * 100, '연프리미엄%': (df['prem'] / nb).sum() / yrs * 100,
            '연배당%': (df['div'] / nb).sum() / yrs * 100,
            '최근5년_총수익%': ((w.iloc[-1] / w.loc['2021-11-01':].iloc[0]) ** (1 / 5) - 1) * 100}


cases = [
    ('코스피200 단독', dict()),
    ('코스피200 콜100% 월물, 전부 분배', dict(k=1.0)),
    ('코스피200 콜100% 위클리, 전부 분배', dict(k=1.0, tenor='W')),
    ('코스피200 위클리 타겟15%', dict(k=1.0, tenor='W', dist='target')),
    ('코스피200 60 + 저베타고배당 40, 위클리100%, 전부 분배', dict(w_k=0.6, w_low=0.4, k=1.0, tenor='W')),
    ('코스피200 50 + 저베타고배당 50, 위클리100%, 전부 분배', dict(w_k=0.5, w_low=0.5, k=1.0, tenor='W')),
    ('코스피200 50 + 저베타고배당 50, 위클리100%, 타겟15%', dict(w_k=0.5, w_low=0.5, k=1.0, tenor='W', dist='target')),
    ('코스피200 50 + 저베타고배당 50, 위클리100%, 타겟18%', dict(w_k=0.5, w_low=0.5, k=1.0, tenor='W', dist='target', target=0.18)),
    ('채권혼합: 코스피200 30 + 저베타 20 + 채권 50, 위클리100%, 전부 분배', dict(w_k=0.3, w_low=0.2, w_bond=0.5, k=1.0, tenor='W')),
    ('채권혼합: 코스피200 50 + 채권 50, 위클리100%, 전부 분배', dict(w_k=0.5, w_bond=0.5, k=1.0, tenor='W')),
    ('채권혼합: 코스피200 30 + 저베타 20 + 채권 50, 위클리100%, 타겟15%', dict(w_k=0.3, w_low=0.2, w_bond=0.5, k=1.0, tenor='W', dist='target')),
]
res, series = [], {}
for name, kw in cases:
    df = run(**kw)
    res.append(metrics(df, name))
    series[name] = df['wealth']
tab = pd.DataFrame(res).round(2)
tab.to_csv(OUT / '결과_조합별.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(series).to_csv(OUT / '결과_일별_wealth.csv', encoding='utf-8-sig')

print(f'코스피200 -20% 급락 {len(eps)}번:', [(f'{s:%Y-%m}', f'{e:%Y-%m}') for s, e in eps])
print('\n[스크리닝: 코스피200 대비]')
print(scr.to_string(index=False))
print('\n저베타 고배당 바구니:', LOW)
print(f'\n백테스트 {dates[0]:%Y-%m-%d} ~ {dates[-1]:%Y-%m-%d} ({len(dates)/252:.1f}년), 채권 {BOND_SRC}')
print(tab.to_string(index=False))
