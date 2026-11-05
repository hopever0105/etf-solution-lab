"""반도체 커버드콜 20년 백테스트: 콜 매도 분배 vs 정유·식품 재투자, 월분배 재원과 배당 달력 (포트폴리오용, 실매매 없음)

- 반도체: 삼성전자·SK하이닉스 50:50 (분기 리셋)
- 저상관: 정유(S-Oil·SK이노베이션) + 식품(CJ제일제당·농심·오뚜기) 동일가중
- 콜: 코스피200(^KS200, 없으면 KODEX 200) 1개월 ATM 콜을 반도체 평가액의 k%만큼 매월 첫 거래일 매도.
  프리미엄은 블랙숄즈(σ = 코스피200 직전 20일 실현변동성, 하한 10%, r = 3%). 정산은 월말(다음 달 첫 거래일 직전)
- 프리미엄의 g%는 저상관 주식 매수, 나머지는 분배 재원. 종목 배당(배당락일 기준)은 분배 재원
- 분배 재원은 매월 마지막 거래일에 전부 분배. 총수익은 분배금을 그날 같은 상품에 재투자했다고 보고 계산
- 저상관 비중 상한 20%(분기 첫 거래일), 정적 혼합안은 분기마다 80:20 리셋
- 시세: yfinance(야후) 수정 안 된 종가 + 배당. KRX 요청 없음. 거래비용·보수·세금 미반영
실행: python -I backtest.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent
R, SIG_FLOOR, CAP_LOW = 0.03, 0.10, 0.20
SEMI = {'삼성전자': '005930.KS', 'SK하이닉스': '000660.KS'}
BASKETS = {
    # 기존: 정유 + 식품
    '정유식품': {'S-Oil': '010950.KS', 'SK이노베이션': '096770.KS', 'CJ제일제당': '097950.KS', '농심': '004370.KS', '오뚜기': '007310.KS'},
    # screen_lowcorr.py에서 반도체 급락 때 덜 빠지고 거래대금 100억 이상인 담배·제약·식품·보험·통신 대표 1종목씩
    '방어5': {'KT&G': '033780.KS', '유한양행': '000100.KS', '농심': '004370.KS', 'DB손해보험': '005830.KS', 'KT': '030200.KS'},
}
BASKET = sys.argv[1] if len(sys.argv) > 1 else '정유식품'
LOW = BASKETS[BASKET]
OUT = OUT / BASKET
OUT.mkdir(exist_ok=True)
ALL = {**SEMI, **LOW}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


# ---------------------------------------------------------------- 데이터
raw = yf.download(list(ALL.values()), start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
inv = {v: k for k, v in ALL.items()}
close = raw['Close'].rename(columns=inv)
divs = raw['Dividends'].rename(columns=inv).fillna(0)
k200 = None
for t in ('^KS200', '069500.KS'):
    s = yf.download(t, start='2007-01-01', end='2026-10-31', auto_adjust=False, progress=False)['Close']
    s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
    if s.dropna().shape[0] > 4000:
        k200, K200_SRC = s, t
        break
px = pd.concat([close, k200.rename('K200')], axis=1).dropna()
divs = divs.reindex(px.index).fillna(0)
vol20 = np.log(px['K200']).diff().rolling(20).std() * sqrt(252)
px = px.iloc[25:]
dates = px.index
ret = px[list(ALL)].pct_change().fillna(0)

per = dates.to_period('M')
month_first = set(pd.Series(dates, index=dates).groupby(per).first())
month_last = set(pd.Series(dates, index=dates).groupby(per).last())
quarter_first = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())
mf = sorted(month_first)
exp_date = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}


def run(k=0.0, g=0.0, static_low=0.0, div_to_dist=True):
    """k: 콜 매도 비율(반도체 평가액 대비), g: 프리미엄 재투자 비율, static_low: 저상관 고정 비중(0이면 상한 20%만)"""
    val = {n: 0.0 for n in ALL}
    for n in SEMI:
        val[n] = (1 - static_low) / len(SEMI)
    for n in LOW:
        val[n] = static_low / len(LOW)
    pool = 0.0
    n_call = K = sig0 = t_exp = None
    rows, prev = [], None
    for d in dates:
        prem_d = div_d = dist_d = 0.0
        if prev is not None:
            for n in ALL:
                # 배당: 배당락일에 보유 평가액(전일) × 주당배당 ÷ 전일 종가
                dv = val[n] * divs.at[d, n] / px.at[prev, n] if divs.at[d, n] > 0 else 0.0
                val[n] *= 1 + ret.at[d, n]
                if dv > 0:
                    div_d += dv
                    if div_to_dist:
                        pool += dv
                    else:
                        val[n] += dv
        # 콜 만기 정산(반도체에서 지급)
        if t_exp is not None and d == t_exp:
            pay = n_call * max(px.at[d, 'K200'] - K, 0.0)
            s_tot = sum(val[n] for n in SEMI)
            for n in SEMI:
                val[n] -= pay * val[n] / s_tot
            n_call = K = sig0 = t_exp = None
        # 분기 리셋
        if d in quarter_first and prev is not None:
            s_tot = sum(val[n] for n in SEMI)
            l_tot = sum(val[n] for n in LOW)
            tot = s_tot + l_tot
            if static_low > 0:
                s_tot, l_tot = tot * (1 - static_low), tot * static_low
            elif l_tot > CAP_LOW * tot:
                s_tot, l_tot = tot * (1 - CAP_LOW), tot * CAP_LOW
            for n in SEMI:
                val[n] = s_tot / len(SEMI)
            for n in LOW:
                val[n] = l_tot / len(LOW)
        # 신규 콜 매도
        if k > 0 and d in month_first and d != dates[-1]:
            sig0 = max(float(vol20[d]) if not np.isnan(vol20[d]) else SIG_FLOOR, SIG_FLOOR)
            K, t_exp = px.at[d, 'K200'], exp_date[d]
            n_call = k * sum(val[n] for n in SEMI) / K
            T = max((t_exp - d).days, 1) / 365
            prem = n_call * bs_call(K, K, sig0, T)
            prem_d = prem
            for n in LOW:
                val[n] += g * prem / len(LOW)
            pool += (1 - g) * prem
        liab = 0.0
        if n_call:
            liab = n_call * bs_call(px.at[d, 'K200'], K, sig0, max((t_exp - d).days, 0) / 365)
        nav_pre = sum(val.values()) + pool - liab
        if d in month_last:
            dist_d, pool = pool, 0.0
        nav = nav_pre - dist_d
        low_w = sum(val[n] for n in LOW) / max(sum(val.values()), 1e-12)
        rows.append((d, nav, prem_d, div_d, dist_d, low_w))
        prev = d
    df = pd.DataFrame(rows, columns=['date', 'nav', 'prem', 'div', 'dist', 'low_w']).set_index('date')
    r = (df['nav'] + df['dist']) / df['nav'].shift(1) - 1
    df['wealth'] = (1 + r.fillna(0)).cumprod()
    return df


semi_only = run(div_to_dist=False)['wealth']
dd = semi_only / semi_only.cummax() - 1
eps, inside = [], False
for d in dd.index:
    if not inside and dd[d] <= -0.20:
        inside, start = True, semi_only.loc[:d].idxmax()
    if inside and dd[d] == 0:
        eps.append((start, d))
        inside = False
if inside:
    eps.append((start, dd.index[-1]))


def metrics(df, name):
    w = df['wealth']
    r = w.pct_change().dropna()
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    nb = df['nav'].shift(1)
    dist_y = (df['dist'] / nb).sum() / yrs
    prem_y = (df['prem'] / nb).sum() / yrs
    div_y = (df['div'] / nb).sum() / yrs
    md = (df['dist'] / nb)[df['dist'] > 0]
    md = md.groupby(md.index.to_period('M')).sum()
    better = sum(((w.loc[s:e] / w.loc[s]).min() > (semi_only.loc[s:e] / semi_only.loc[s]).min()) for s, e in eps)
    return {'안': name, '연총수익%': cagr * 100, '변동성%': r.std() * sqrt(252) * 100,
            '최대낙폭%': (w / w.cummax() - 1).min() * 100, '연분배율%': dist_y * 100,
            '연프리미엄%': prem_y * 100, '연배당%': div_y * 100,
            '월분배_최소%': md.min() * 100 if len(md) else 0, '월분배_최대%': md.max() * 100 if len(md) else 0,
            f'급락{len(eps)}번중_덜빠짐': better, '말기저상관비중%': df['low_w'].iloc[-1] * 100}


cases = [
    ('반도체 단독(배당 재투자)', dict(div_to_dist=False)),
    (f'반도체80+{BASKET}20, 배당만 분배', dict(static_low=0.2)),
    ('콜30%, 전부 분배', dict(k=0.3)),
    ('콜30%, 프리미엄 절반 재투자', dict(k=0.3, g=0.5)),
    ('콜50%, 전부 분배', dict(k=0.5)),
    ('콜50%, 프리미엄 절반 재투자', dict(k=0.5, g=0.5)),
    ('콜100%, 전부 분배', dict(k=1.0)),
    (f'반도체80+{BASKET}20 + 콜30%, 전부 분배', dict(k=0.3, static_low=0.2)),
]
res, series, dist_m = [], {}, {}
for name, kw in cases:
    df = run(**kw)
    res.append(metrics(df, name))
    series[name] = df['wealth']
    dist_m[name] = df['dist'][df['dist'] > 0]
tab = pd.DataFrame(res).round(2)
tab.to_csv(OUT / '결과_조합별.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(series).to_csv(OUT / '결과_일별_wealth.csv', encoding='utf-8-sig')

# 배당 달력: 최근 5년(2021-11~2026-10) 배당락일이 있었던 달
cal = divs.loc['2021-11-01':]
cal_tab = pd.DataFrame({n: [int(((cal[n] > 0) & (cal.index.month == m)).sum()) for m in range(1, 13)] for n in ALL},
                       index=[f'{m}월' for m in range(1, 13)]).T
cal_tab.to_csv(OUT / '배당락_달력_최근5년.csv', encoding='utf-8-sig')

# 배당만으로 받는 월별 현금 비중(반도체80+정유식품20): 달별 평균 배당 ÷ 연 배당
st = run(static_low=0.2)
dm = (st['div'] / st['nav'].shift(1)).groupby(st.index.month).sum()
dm = dm / dm.sum() * 100

print(f'기간 {dates[0]:%Y-%m-%d} ~ {dates[-1]:%Y-%m-%d} ({len(dates)/252:.1f}년), 콜 기초 {K200_SRC}')
print('반도체 vs 코스피200 상관', round(ret[list(SEMI)].mean(axis=1).corr(px['K200'].pct_change()), 2),
      '/ 반도체 vs 저상관 상관', round(ret[list(SEMI)].mean(axis=1).corr(ret[list(LOW)].mean(axis=1)), 2))
print(f'반도체 -20% 급락 구간 {len(eps)}개')
print(tab.to_string(index=False))
print('\n배당락일 있었던 횟수(최근 5년, 달별)')
print(cal_tab.to_string())
print(f'\n배당 현금이 들어온 달 비중(반도체80+{BASKET}20, 20년 합계 기준 %)')
print(dm.round(1).to_string())

