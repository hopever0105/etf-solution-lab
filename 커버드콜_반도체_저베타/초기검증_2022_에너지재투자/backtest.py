"""반도체 커버드콜 + 프리미엄 에너지 재투자 근사 백테스트 (포트폴리오용, 실매매 없음)

- 기초: KODEX 반도체(091160) 가격, 에너지: S-Oil·SK이노베이션·GS 동일가중(분기 리셋)
- 매월 첫 거래일 1개월 ATM 콜을 반도체 노출의 k%만큼 매도, 프리미엄은 블랙숄즈(σ=직전 20일 실현변동성, 하한 15%, r=3%)
- 프리미엄의 g%는 에너지 매수, 나머지는 분배(현금, 이자 0, 총수익에 포함)
- 에너지 비중 상한 20%(분기 첫 거래일 점검, 초과분은 반도체로)
- 데이터: FinanceDataReader 네이버 시세만 사용(KRX 요청 없음). 거래비용·보수 미반영
실행: python -I backtest.py
"""
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import FinanceDataReader as fdr

OUT = Path(__file__).resolve().parent
START, R, SIG_FLOOR, CAP_E = '2022-04-04', 0.03, 0.15, 0.20
CODES = {'SEMI': '091160', 'SOIL': '010950', 'SKI': '096770', 'GS': '078930'}

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

# 에너지 바스켓 지수(동일가중, 분기 리셋)
en = pd.Series(index=dates, dtype=float)
units, level = None, 1.0
for d in dates:
    p = px.loc[d, ['SOIL', 'SKI', 'GS']]
    if units is None or d in quarter_first:
        val = level if units is None else float((units * p).sum())
        units = val / 3 / p
    level = float((units * p).sum())
    en[d] = level


def run(k, g, static_mix=False):
    """k: 콜 매도 비율, g: 프리미엄 재투자 비율, static_mix: 반도체80+에너지20 분기 리셋(B20식)"""
    s_val, e_val = (0.8, 0.2) if static_mix else (1.0, 0.0)
    dist_cum, prem_cum = 0.0, 0.0
    n_call, K, sig0, t_exp = 0.0, None, None, None
    rows = []
    prev = None
    exp_dates = {}
    # 만기 = 다음 달 첫 거래일 직전 거래일
    mf = sorted(month_first)
    for i, d0 in enumerate(mf):
        nxt = mf[i + 1] if i + 1 < len(mf) else None
        exp_dates[d0] = dates[dates.get_loc(nxt) - 1] if nxt is not None else dates[-1]
    for d in dates:
        prem_d, dist_d = 0.0, 0.0
        if prev is not None:
            s_val *= semi[d] / semi[prev]
            e_val *= en[d] / en[prev]
        # 만기 정산
        if t_exp is not None and d == t_exp:
            pay = n_call * max(semi[d] - K, 0.0)
            s_val -= pay
            n_call, K, t_exp = 0.0, None, None
        # 분기 점검
        if d in quarter_first and prev is not None:
            tot = s_val + e_val
            if static_mix:
                s_val, e_val = 0.8 * tot, 0.2 * tot
            elif e_val > CAP_E * tot:
                s_val, e_val = tot * (1 - CAP_E), tot * CAP_E
        # 신규 매도
        if k > 0 and d in month_first and d != dates[-1]:
            sig0 = max(float(vol20[d]) if not np.isnan(vol20[d]) else SIG_FLOOR, SIG_FLOOR)
            K = semi[d]
            t_exp = exp_dates[d]
            n_call = k * s_val / semi[d]
            T = max((t_exp - d).days, 1) / 365
            prem = n_call * bs_call(semi[d], K, sig0, T)
            prem_cum += prem
            e_val += g * prem
            dist_cum += (1 - g) * prem
            prem_d, dist_d = prem, (1 - g) * prem
        # 콜 평가(부채)
        if n_call > 0:
            T = max((t_exp - d).days, 0) / 365
            liab = n_call * bs_call(semi[d], K, sig0, T)
        else:
            liab = 0.0
        nav = s_val + e_val - liab
        rows.append((d, nav, prem_d, dist_d, e_val / max(s_val + e_val, 1e-12)))
        prev = d
    df = pd.DataFrame(rows, columns=['date', 'nav', 'prem', 'dist', 'e_w']).set_index('date')
    # 총수익(TR): 분배금을 받은 날 같은 상품에 재투자했다고 보고 계산
    r = (df['nav'] + df['dist']) / df['nav'].shift(1) - 1
    df['wealth'] = (1 + r.fillna(0)).cumprod()
    return df


def metrics(df, name):
    w = df['wealth']
    r = w.pct_change().dropna()
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * sqrt(252)
    mdd = (w / w.cummax() - 1).min()
    nav_before = df['nav'].shift(1)
    prem_y = (df['prem'] / nav_before).sum() / yrs
    dist_y = (df['dist'] / nav_before).sum() / yrs
    corr = r.corr(semi.pct_change().reindex(r.index))
    out = {'안': name, '연수익%': cagr * 100, '변동성%': vol * 100, '최대낙폭%': mdd * 100,
           '수익/변동성': cagr / vol, '연프리미엄%': prem_y * 100, '연분배율%': dist_y * 100,
           '반도체상관': corr, '말기에너지비중%': df['e_w'].iloc[-1] * 100}
    for lab, (a, b) in WINDOWS.items():
        out[lab + '%'] = (w.loc[b] / w.loc[a] - 1) * 100
    return out


def dd_window(s, lo, hi):
    x = s.loc[lo:hi]
    trough = (x / x.cummax() - 1).idxmin()
    peak = x.loc[:trough].idxmax()
    return peak, trough


WINDOWS = {}
p, t = dd_window(semi, '2022-04-04', '2022-12-31')
WINDOWS[f'2022하락({p:%m/%d}~{t:%m/%d})'] = (p, t)
p, t = dd_window(semi, '2026-06-01', '2026-08-31')
WINDOWS[f'2026여름하락({p:%m/%d}~{t:%m/%d})'] = (p, t)

cases = [('반도체 단독', 0, 0, False), ('단순 커버드콜(100%·분배)', 1.0, 0, False),
         ('B20식 정적(반도체80+에너지20)', 0, 0, True)]
for k in (0.3, 0.5, 1.0):
    for g in (0.0, 0.5, 1.0):
        if (k, g) == (1.0, 0.0):
            continue
        cases.append((f'매도{int(k*100)}%·재투자{int(g*100)}%', k, g, False))

res, series = [], {}
for name, k, g, st in cases:
    df = run(k, g, st)
    res.append(metrics(df, name))
    series[name] = df['wealth']
tab = pd.DataFrame(res).round(2)
tab.to_csv(OUT / '결과_조합별.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(series).to_csv(OUT / '결과_일별_wealth.csv', encoding='utf-8-sig')
print(f'기간 {dates[0]:%Y-%m-%d} ~ {dates[-1]:%Y-%m-%d}, {len(dates)}일')
print(WINDOWS)
print(tab.to_string())
