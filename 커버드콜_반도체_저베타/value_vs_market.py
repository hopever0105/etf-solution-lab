"""내 안(반도체 70 + 저베타 고배당 30, 콜 50% 월물, 연 10% 월분배)이 기존 커버드콜보다 상품 가치가 있나 (포트폴리오용, 실매매 없음)

1. 저베타 바구니 비교: 9종목 / KT·KT&G·DB손해보험·S-Oil 4종목 / S-Oil 뺀 3종목 (동일가중, 매월 리셋)
2. 기존 상품 구조를 같은 17년에 재현해 비교
   - 코스피200 타겟위클리형: 코스피200 + 위클리 콜을 연 프리미엄 약 15%가 되게 매도(k=0.3), 프리미엄+배당 전부 분배
   - 반도체 커버드콜형: 반도체 + 코스피200 위클리 콜 k=0.3, 전부 분배
   - 고배당 커버드콜형: 저베타 고배당 9종목 + 코스피200 위클리 콜 k=0.3, 전부 분배
3. 실제 상장 커버드콜의 상장 이후 총수익(야후 수정종가 = 분배 재투자) vs 내 안의 같은 기간 백테스트
시세: yfinance(야후), KRX 요청 없음. 거래비용·보수·세금 미반영(실제 상품은 보수·비용 반영 후)
실행: python -I value_vs_market.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '시장상품_비교'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR = 0.03, 0.10
SEMI = ['005930.KS', '000660.KS']
K200 = '069500.KS'
LOW9 = {'맥쿼리인프라': '088980.KS', 'SK텔레콤': '017670.KS', '기업은행': '024110.KS', 'KT&G': '033780.KS', 'KT': '030200.KS',
        'DB손해보험': '005830.KS', 'LG유플러스': '032640.KS', '현대해상': '001450.KS', '삼성화재': '000810.KS'}
LOW4 = {'KT': '030200.KS', 'KT&G': '033780.KS', 'DB손해보험': '005830.KS', 'S-Oil': '010950.KS'}
LOW3 = {'KT': '030200.KS', 'KT&G': '033780.KS', 'DB손해보험': '005830.KS'}
LISTED = {'KODEX 200타겟위클리커버드콜': '498400.KS', 'TIGER 배당커버드콜액티브': '472150.KS', 'RISE 200위클리커버드콜': '475720.KS',
          'KODEX 금융고배당TOP10타겟위클리커버드콜': '498410.KS', 'PLUS 고배당주위클리커버드콜': '489030.KS',
          'TIGER 반도체TOP10커버드콜액티브': '0177R0.KS', 'KODEX 반도체타겟위클리커버드콜': '0190G0.KS', 'KODEX 200커버드콜액티브': '0219E0.KS'}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


tick = sorted(set(SEMI) | {K200} | set(LOW9.values()) | set(LOW4.values()))
raw = yf.download(tick, start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
close, divs = raw['Close'], raw['Dividends'].fillna(0)
pr_all = close.pct_change(fill_method=None)
dy_all = divs.reindex(close.index).fillna(0) / close.shift(1)


def ew(tks):
    tks = list(tks)
    ok = close[tks].notna().all(axis=1)
    return pr_all[tks].mean(axis=1)[ok], dy_all[tks].mean(axis=1)[ok]


def run(base, low=None, w_low=0.0, k=0.5, tenor='M', dist='target', target=0.10):
    b_pr, b_dy = ew(base)
    parts = [b_pr.rename('b'), b_dy.rename('bd'), close[K200].rename('c')]
    if low:
        l_pr, l_dy = ew(low.values())
        parts += [l_pr.rename('l'), l_dy.rename('ld')]
    df = pd.concat(parts, axis=1).dropna()
    if not low:
        df['l'] = 0.0
        df['ld'] = 0.0
    vol = np.log(df['c']).diff().rolling(20).std() * sqrt(252)
    df = df.iloc[25:]
    dates = df.index
    per = dates.to_period('M')
    mfirst = set(pd.Series(dates, index=dates).groupby(per).first())
    mlast = set(pd.Series(dates, index=dates).groupby(per).last())
    qfirst = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())
    mf = sorted(mfirst)
    exp_m = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}
    vb, vl, pool = 1 - w_low, w_low, 0.0
    n_call = K = sig = t_exp = None
    navs, dsts, prems = [], [], []
    for i, d in enumerate(dates):
        prem = dist_d = 0.0
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
            if dist == 'all':
                dist_d, pool = pool, 0.0
            elif dist == 'target':
                dist_d = nav_pre * target / 12
                extra, pool = pool - dist_d, 0.0
                tot = vb + vl
                vb += extra * vb / tot
                vl += extra * vl / tot
            else:
                extra, pool = pool, 0.0
                tot = vb + vl
                vb += extra * vb / tot
                vl += extra * vl / tot
        navs.append(nav_pre - dist_d)
        dsts.append(dist_d)
        prems.append(prem)
    o = pd.DataFrame({'nav': navs, 'dist': dsts, 'prem': prems}, index=dates)
    r = (o['nav'] + o['dist']) / o['nav'].shift(1) - 1
    o['wealth'] = (1 + r.fillna(0)).cumprod()
    return o


def summary(o, label):
    w, nav = o['wealth'], o['nav']
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    ret = w.pct_change().dropna()
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    vol = ret.std() * sqrt(252)
    m = nav.groupby(nav.index.to_period('M')).first()
    ch5 = (m.shift(-60) / m - 1).dropna() * 100
    yt = nav.groupby(nav.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1)
    pre = o.loc[:'2023-12-31']
    wp, np_ = pre['wealth'], pre['nav']
    yp = (wp.index[-1] - wp.index[0]).days / 365.25
    return {'안': label, '연총수익%': cagr * 100, '변동성%': vol * 100, '수익/변동성': cagr / vol,
            '최대낙폭%': (w / w.cummax() - 1).min() * 100, '연분배%': (o['dist'] / nav.shift(1)).sum() / yrs * 100,
            '원금연변화%': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100,
            '원금최대하락%': (nav / nav.cummax() - 1).min() * 100, '원금줄어든해': f'{(yt < 0).sum()}/{len(yt)}',
            '5년보유_원금감소%': (ch5 < 0).mean() * 100, '5년보유_최악%': ch5.min(),
            '급등전_연총수익%': ((wp.iloc[-1] / wp.iloc[0]) ** (1 / yp) - 1) * 100,
            '급등전_원금연변화%': ((np_.iloc[-1] / np_.iloc[0]) ** (1 / yp) - 1) * 100}


# ---------------------------------------------------------------- 1·2. 같은 기간 비교
cases = {
    '내 안: 반도체70 + 저베타9종목 30, 콜50% 월물, 10% 분배': dict(base=SEMI, low=LOW9, w_low=0.3),
    '내 안: 반도체70 + KT·KT&G·DB손보·S-Oil 30, 10% 분배': dict(base=SEMI, low=LOW4, w_low=0.3),
    '내 안: 반도체70 + KT·KT&G·DB손보 30, 10% 분배': dict(base=SEMI, low=LOW3, w_low=0.3),
    '내 안(3종목) 15% 분배': dict(base=SEMI, low=LOW3, w_low=0.3, target=0.15),
    '내 안(3종목) 12% 분배': dict(base=SEMI, low=LOW3, w_low=0.3, target=0.12),
    '기존형: 코스피200 타겟위클리(콜 30%, 전부 분배)': dict(base=[K200], k=0.3, tenor='W', dist='all'),
    '기존형: 반도체 위클리 커버드콜(콜 30%, 전부 분배)': dict(base=SEMI, k=0.3, tenor='W', dist='all'),
    '기존형: 고배당 9종목 위클리 커버드콜(콜 30%, 전부 분배)': dict(base=list(LOW9.values()), k=0.3, tenor='W', dist='all'),
    '참고: 반도체 단독(분배 없음)': dict(base=SEMI, k=0.0, dist='none'),
    '참고: 코스피200 단독(분배 없음)': dict(base=[K200], k=0.0, dist='none'),
}
runs = {lab: run(**kw) for lab, kw in cases.items()}
start = max(o.index[0] for o in runs.values())
rows = []
for lab, o in runs.items():
    o = o.loc[start:].copy()
    o['wealth'] = o['wealth'] / o['wealth'].iloc[0]
    rows.append(summary(o, lab))
tab = pd.DataFrame(rows).round(2)
tab.to_csv(OUT / '1_같은기간_구조비교.csv', index=False, encoding='utf-8-sig')

# ---------------------------------------------------------------- 3. 실제 상장 상품 vs 내 안(같은 기간)
mine = runs['내 안: 반도체70 + KT·KT&G·DB손보 30, 10% 분배']['wealth']
mine9 = runs['내 안: 반도체70 + 저베타9종목 30, 콜50% 월물, 10% 분배']['wealth']
semi_w = runs['참고: 반도체 단독(분배 없음)']['wealth']
k_w = runs['참고: 코스피200 단독(분배 없음)']['wealth']
lrows = []
for name, t in LISTED.items():
    try:
        s = yf.download(t, start='2020-01-01', end='2026-10-31', auto_adjust=True, progress=False)['Close']
        s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
        s = s.dropna()
    except Exception:
        s = pd.Series(dtype=float)
    if len(s) < 40:
        lrows.append({'상품': name, '상장후 시작': '야후 데이터 없음'})
        continue
    a, b = s.index[0], min(s.index[-1], mine.index[-1])
    s = s.loc[a:b]
    def tr(x):
        x = x.loc[a:b]
        return (x.iloc[-1] / x.iloc[0] - 1) * 100
    def mdd(x):
        x = x.loc[a:b]
        return (x / x.cummax() - 1).min() * 100
    lrows.append({'상품': name, '상장후 시작': f'{a:%Y-%m-%d}', '거래일': len(s),
                  '상품 총수익%': tr(s), '상품 최대낙폭%': mdd(s),
                  '내 안(3종목) 총수익%': tr(mine), '내 안(3종목) 최대낙폭%': mdd(mine),
                  '내 안(9종목) 총수익%': tr(mine9), '반도체 단독%': tr(semi_w), '코스피200 단독%': tr(k_w)})
ltab = pd.DataFrame(lrows).round(1)
ltab.to_csv(OUT / '2_실제상품_상장후비교.csv', index=False, encoding='utf-8-sig')

pd.set_option('display.width', 320)
pd.set_option('display.max_columns', 30)
print(f'[1. 같은 기간 구조 비교] {start:%Y-%m-%d} ~ 2026-10-30, 급등전 = ~2023-12')
print(tab.to_string(index=False))
print('\n[2. 실제 상장 커버드콜 vs 내 안 (상장일부터, 야후 수정종가 = 분배 재투자 총수익)]')
print(ltab.to_string(index=False))
