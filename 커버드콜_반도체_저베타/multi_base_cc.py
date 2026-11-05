"""기초자산별(코스피200·반도체·금융·코스닥150) 커버드콜: 연 15% 이상 분배하면서 원금(NAV)을 지키는 조합 찾기 (포트폴리오용, 실매매 없음)

- 기초 바스켓: 종목 동일가중(일간 리셋 근사), 가격수익률 + 배당(배당락일 주당배당÷전일종가)
- 저베타 고배당 바구니(kospi200_highdiv_cc.py 스크리닝 결과 9종목)를 0~40% 섞을 수 있음
- 콜: 코스닥은 KODEX 코스닥150(229200), 나머지는 KODEX 200(069500) ATM 콜을 기초 바스켓 평가액의 k%만큼 매도
  월물(매월 첫 거래일~월말) 또는 위클리(5거래일). 블랙숄즈(σ=콜 기초 직전 20일 실현변동성, 하한 10%, r=3%)
- 분배: 매월 NAV × 목표율/12 고정(타겟형). 프리미엄+배당이 남으면 재투자, 모자라면 자산을 팔아 채움
- 판정: 'NAV 연변화 ≥ 0' 이면 원금을 지키며 그 분배를 준 것
시세: yfinance(야후), KRX 요청 없음. 거래비용·보수·세금 미반영. 위클리 옵션은 실제로는 2019년 이후
실행: python -I multi_base_cc.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '기초자산별_타겟분배'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR = 0.03, 0.10
BASES = {
    '코스피200': {'KODEX 200': '069500.KS'},
    '반도체': {'삼성전자': '005930.KS', 'SK하이닉스': '000660.KS'},
    '금융': {'KB금융': '105560.KS', '신한지주': '055550.KS', '하나금융지주': '086790.KS', '기업은행': '024110.KS'},
    '코스닥150': {'KODEX 코스닥150': '229200.KS'},
}
CALL_ON = {'코스피200': '069500.KS', '반도체': '069500.KS', '금융': '069500.KS', '코스닥150': '229200.KS'}
LOW = {'맥쿼리인프라': '088980.KS', 'SK텔레콤': '017670.KS', '기업은행': '024110.KS', 'KT&G': '033780.KS', 'KT': '030200.KS',
       'DB손해보험': '005830.KS', 'LG유플러스': '032640.KS', '현대해상': '001450.KS', '삼성화재': '000810.KS'}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


tick = set(CALL_ON.values()) | set(LOW.values())
for b in BASES.values():
    tick |= set(b.values())
raw = yf.download(sorted(tick), start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
close, divs = raw['Close'], raw['Dividends'].fillna(0)


def basket(tks):
    c = close[list(tks)]
    pr = c.pct_change(fill_method=None).mean(axis=1)
    dy = (divs[list(tks)].reindex(c.index).fillna(0) / c.shift(1)).mean(axis=1)
    ok = c.notna().all(axis=1)
    return pr[ok], dy[ok]


low_pr, low_dy = basket(LOW.values())


def run(base, w_low=0.0, k=1.0, tenor='W', target=0.15, start=None):
    b_pr, b_dy = basket(BASES[base].values())
    cs = close[CALL_ON[base]]
    df = pd.concat([b_pr.rename('b'), b_dy.rename('bd'), low_pr.rename('l'), low_dy.rename('ld'), cs.rename('c')], axis=1).dropna()
    vol = np.log(df['c']).diff().rolling(20).std() * sqrt(252)
    df = df.iloc[25:]
    if start:
        df = df.loc[start:]
    dates = df.index
    per = dates.to_period('M')
    mfirst = set(pd.Series(dates, index=dates).groupby(per).first())
    mlast = set(pd.Series(dates, index=dates).groupby(per).last())
    qfirst = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())
    mf = sorted(mfirst)
    exp_m = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}
    vb, vl, pool = 1 - w_low, w_low, 0.0
    n_call = K = sig = t_exp = None
    navs, dists, prems = [], [], []
    for i, d in enumerate(dates):
        prem = dist = 0.0
        if i:
            pool += vb * df.at[d, 'bd'] + vl * df.at[d, 'ld']
            vb *= 1 + df.at[d, 'b']
            vl *= 1 + df.at[d, 'l']
        if t_exp is not None and d == t_exp:
            vb -= n_call * max(df.at[d, 'c'] - K, 0.0)
            n_call = K = sig = t_exp = None
        if d in qfirst and i:
            tot = vb + vl
            vb, vl = tot * (1 - w_low), tot * w_low
        new = (tenor == 'M' and d in mfirst) or (tenor == 'W' and i % 5 == 0)
        if k > 0 and new and t_exp is None and i < len(dates) - 1:
            sig = max(float(vol[d]) if not np.isnan(vol[d]) else SIG_FLOOR, SIG_FLOOR)
            K = df.at[d, 'c']
            t_exp = exp_m[d] if tenor == 'M' else dates[min(i + 5, len(dates) - 1)]
            n_call = k * vb / K
            prem = n_call * bs_call(K, K, sig, max((t_exp - d).days, 1) / 365)
            pool += prem
        liab = n_call * bs_call(df.at[d, 'c'], K, sig, max((t_exp - d).days, 0) / 365) if n_call else 0.0
        nav_pre = vb + vl + pool - liab
        if d in mlast:
            dist = nav_pre * target / 12
            extra = pool - dist
            pool = 0.0
            tot = vb + vl
            vb += extra * vb / tot
            vl += extra * vl / tot
        navs.append(nav_pre - dist)
        dists.append(dist)
        prems.append(prem)
    out = pd.DataFrame({'nav': navs, 'dist': dists, 'prem': prems}, index=dates)
    r = (out['nav'] + out['dist']) / out['nav'].shift(1) - 1
    out['wealth'] = (1 + r.fillna(0)).cumprod()
    return out


def metrics(o, label):
    yrs = (o.index[-1] - o.index[0]).days / 365.25
    w, nav = o['wealth'], o['nav']
    nb = nav.shift(1)
    return {'안': label, '기간': f'{o.index[0]:%Y-%m}~{o.index[-1]:%Y-%m}',
            '연총수익%': ((w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1) * 100,
            'NAV연변화%': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100,
            '최대낙폭%': (w / w.cummax() - 1).min() * 100,
            'NAV최저(시작=100)': nav.min() / nav.iloc[0] * 100,
            '연분배%': (o['dist'] / nb).sum() / yrs * 100, '연프리미엄%': (o['prem'] / nb).sum() / yrs * 100}


rows = []
for base in BASES:
    for w_low in (0.0, 0.2):
        for tenor in ('M', 'W'):
            for k in (0.5, 1.0):
                for tgt in (0.15, 0.18, 0.20):
                    o = run(base, w_low, k, tenor, tgt)
                    rows.append(metrics(o, f'{base} | 저베타{int(w_low*100)}% | {"월물" if tenor=="M" else "위클리"} 콜{int(k*100)}% | 목표{int(tgt*100)}%'))
    o = run(base, k=0.0, target=0.0)
    rows.append(metrics(o, f'{base} | 콜·분배 없음(기준)'))
tab = pd.DataFrame(rows).round(2)
tab.to_csv(OUT / '결과_전체.csv', index=False, encoding='utf-8-sig')
ok = tab[(tab['NAV연변화%'] >= 0) & (tab['연분배%'] >= 15)].sort_values(['연분배%', '최대낙폭%'], ascending=[False, False])
ok.to_csv(OUT / '결과_15%이상_원금유지.csv', index=False, encoding='utf-8-sig')

# 통과한 것 중 상위 3개는 최근 5년만 다시
recent = []
for lab in ok['안'].head(6):
    p = [x.strip() for x in lab.split('|')]
    base, w_low = p[0], int(p[1].replace('저베타', '').replace('%', '')) / 100
    tenor = 'M' if p[2].startswith('월물') else 'W'
    k = int(p[2].split('콜')[1].replace('%', '')) / 100
    tgt = int(p[3].replace('목표', '').replace('%', '')) / 100
    recent.append(metrics(run(base, w_low, k, tenor, tgt, start='2021-11-01'), lab + ' (최근5년)'))
rec = pd.DataFrame(recent).round(2)

pd.set_option('display.width', 250)
print('[기초자산별 기준(콜·분배 없음)]')
print(tab[tab['안'].str.contains('기준')].to_string(index=False))
print(f'\n[연 15% 이상 분배 + 원금(NAV) 유지 통과: {len(ok)}개 / 전체 {len(tab)}개]')
print(ok.to_string(index=False))
print('\n[통과 상위 6개, 최근 5년]')
print(rec.to_string(index=False))
