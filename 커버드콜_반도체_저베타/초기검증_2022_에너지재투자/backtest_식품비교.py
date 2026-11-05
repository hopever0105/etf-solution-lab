"""반도체 커버드콜 프리미엄 재투자 대상 비교 (에너지 / 식품 / 농산물 선물 / 에너지+식품) — 포트폴리오용, 실매매 없음

- backtest.py와 같은 설계: KODEX 반도체(091160) 기초, 매월 첫 거래일 1개월 ATM 콜, 블랙숄즈(σ=직전 20일 실현변동성, 하한 15%, r=3%)
- 재투자 자산 비중 상한 20%(분기 첫 거래일 점검, 초과분은 반도체로)
- 재투자 대상
  (a) 에너지: S-Oil·SK이노베이션·GS 동일가중
  (b) 식품: 삼양식품·CJ제일제당·농심·오리온 동일가중
  (c) 농산물: KODEX 3대농산물선물(H) 271060
  (d) 에너지+식품: (a) 50% + (b) 50%
  바스켓은 모두 분기 리셋
- 데이터: FinanceDataReader 네이버 시세만 사용(KRX 요청 없음). 거래비용·보수 미반영
실행: python -I backtest_식품비교.py
"""
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

OUT = Path(__file__).resolve().parent
START, R, SIG_FLOOR, CAP_E = '2022-04-04', 0.03, 0.15, 0.20
CODES = {'SEMI': '091160', 'SOIL': '010950', 'SKI': '096770', 'GS': '078930',
         'SAMYANG': '003230', 'CJ': '097950', 'NONGSHIM': '004370', 'ORION': '271560',
         'AGRI': '271060'}
BASKETS = {'에너지': ['SOIL', 'SKI', 'GS'],
           '식품': ['SAMYANG', 'CJ', 'NONGSHIM', 'ORION'],
           '농산물선물': ['AGRI']}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


# ---------------------------------------------------------------- 데이터
px = pd.concat({k: fdr.DataReader('NAVER:' + c, '2022-01-01')['Close'] for k, c in CODES.items()}, axis=1)
px = px.dropna()
vol20 = np.log(px['SEMI']).diff().rolling(20).std() * sqrt(252)
px = px.loc[START:]
dates = px.index
semi = px['SEMI']

month_first = set(pd.Series(dates, index=dates).groupby(dates.to_period('M')).first())
quarter_first = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())


def basket(levels: pd.DataFrame) -> pd.Series:
    """동일가중, 분기 리셋 바스켓 지수(시작 1.0)"""
    out = pd.Series(index=dates, dtype=float)
    units, level = None, 1.0
    n = levels.shape[1]
    for d in dates:
        p = levels.loc[d]
        if units is None or d in quarter_first:
            val = level if units is None else float((units * p).sum())
            units = val / n / p
        level = float((units * p).sum())
        out[d] = level
    return out


ASSETS = {name: basket(px[cols]) for name, cols in BASKETS.items()}
ASSETS['에너지+식품'] = basket(pd.concat({'E': ASSETS['에너지'], 'F': ASSETS['식품']}, axis=1))

mf = sorted(month_first)
EXP = {}
for i, d0 in enumerate(mf):
    nxt = mf[i + 1] if i + 1 < len(mf) else None
    EXP[d0] = dates[dates.get_loc(nxt) - 1] if nxt is not None else dates[-1]


def run(asset, k, g, static_mix=False):
    """asset: 재투자 자산 지수, k: 콜 매도 비율, g: 프리미엄 재투자 비율, static_mix: 반도체80+자산20 분기 리셋"""
    s_val, e_val = (0.8, 0.2) if static_mix else (1.0, 0.0)
    n_call, K, sig0, t_exp = 0.0, None, None, None
    rows, prev = [], None
    for d in dates:
        prem_d, dist_d = 0.0, 0.0
        if prev is not None:
            s_val *= semi[d] / semi[prev]
            e_val *= asset[d] / asset[prev]
        if t_exp is not None and d == t_exp:
            s_val -= n_call * max(semi[d] - K, 0.0)
            n_call, K, t_exp = 0.0, None, None
        if d in quarter_first and prev is not None:
            tot = s_val + e_val
            if static_mix:
                s_val, e_val = 0.8 * tot, 0.2 * tot
            elif e_val > CAP_E * tot:
                s_val, e_val = tot * (1 - CAP_E), tot * CAP_E
        if k > 0 and d in month_first and d != dates[-1]:
            sig0 = max(float(vol20[d]) if not np.isnan(vol20[d]) else SIG_FLOOR, SIG_FLOOR)
            K = semi[d]
            t_exp = EXP[d]
            n_call = k * s_val / semi[d]
            T = max((t_exp - d).days, 1) / 365
            prem = n_call * bs_call(semi[d], K, sig0, T)
            e_val += g * prem
            prem_d, dist_d = prem, (1 - g) * prem
        liab = n_call * bs_call(semi[d], K, sig0, max((t_exp - d).days, 0) / 365) if n_call > 0 else 0.0
        nav = s_val + e_val - liab
        rows.append((d, nav, prem_d, dist_d, e_val / max(s_val + e_val, 1e-12)))
        prev = d
    df = pd.DataFrame(rows, columns=['date', 'nav', 'prem', 'dist', 'e_w']).set_index('date')
    r = (df['nav'] + df['dist']) / df['nav'].shift(1) - 1
    df['wealth'] = (1 + r.fillna(0)).cumprod()
    return df


def dd_window(s, lo, hi):
    x = s.loc[lo:hi]
    trough = (x / x.cummax() - 1).idxmin()
    return x.loc[:trough].idxmax(), trough


WINDOWS = {}
p, t = dd_window(semi, '2022-04-04', '2022-12-31')
WINDOWS[f'2022하락({p:%m/%d}~{t:%m/%d})'] = (p, t)
p, t = dd_window(semi, '2026-06-01', '2026-08-31')
WINDOWS[f'2026여름하락({p:%m/%d}~{t:%m/%d})'] = (p, t)


def metrics(df, target, name):
    w = df['wealth']
    r = w.pct_change().dropna()
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * sqrt(252)
    nav_before = df['nav'].shift(1)
    out = {'재투자대상': target, '안': name, '연수익%': cagr * 100, '변동성%': vol * 100,
           '최대낙폭%': (w / w.cummax() - 1).min() * 100, '수익/변동성': cagr / vol,
           '연분배율%': (df['dist'] / nav_before).sum() / yrs * 100,
           '반도체상관': r.corr(semi.pct_change().reindex(r.index)),
           '말기재투자자산비중%': df['e_w'].iloc[-1] * 100}
    for lab, (a, b) in WINDOWS.items():
        out[lab + '%'] = (w.loc[b] / w.loc[a] - 1) * 100
    return out


def asset_profile(s, name):
    r = s.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    out = {'재투자대상': name, '안': '자산 자체', '연수익%': ((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100,
           '변동성%': r.std() * sqrt(252) * 100, '최대낙폭%': (s / s.cummax() - 1).min() * 100,
           '반도체상관': r.corr(semi.pct_change().reindex(r.index))}
    out['수익/변동성'] = out['연수익%'] / out['변동성%']
    for lab, (a, b) in WINDOWS.items():
        out[lab + '%'] = (s.loc[b] / s.loc[a] - 1) * 100
    return out


res = [metrics(run(ASSETS['에너지'], 0, 0), '-', '반도체 단독')]
for name, a in ASSETS.items():
    res.append(asset_profile(a, name))
    res.append(metrics(run(a, 0, 0, True), name, '고정 혼합(반도체80+자산20)'))
    res.append(metrics(run(a, 0.5, 0.5), name, '매도50%·재투자50%'))
    res.append(metrics(run(a, 0.3, 1.0), name, '매도30%·재투자100%'))
tab = pd.DataFrame(res).round(2)
tab.to_csv(OUT / '결과_재투자대상비교.csv', index=False, encoding='utf-8-sig')
print(f'기간 {dates[0]:%Y-%m-%d} ~ {dates[-1]:%Y-%m-%d}, {len(dates)}일')
print(WINDOWS)
print(tab.to_string())
