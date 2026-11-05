"""반도체·코스피200·코스닥150 커버드콜 + 저베타 고배당 30%: 같은 기준으로 연도별·구간별·급락 유무별 비교 (포트폴리오용, 실매매 없음)

공통 기준
- 콜: 기초 평가액의 50%만큼 1개월 ATM 콜 매도(매월 첫 거래일 ~ 월말). 반도체·코스피200은 KODEX 200(069500), 코스닥150은 KODEX 코스닥150(229200)
  블랙숄즈(σ = 콜 기초 직전 20일 실현변동성, 하한 10%, r = 3%)
- 분배: 매월 NAV × 목표/12 고정(목표 10%, 15%). 프리미엄+배당이 남으면 재투자, 모자라면 보유 자산을 팔아 채움
- 구조 '정적'   : 기초 70 + 저베타 30, 분기 리셋
  구조 '재투자' : 기초 100으로 시작, 남는 현금(프리미엄+배당−분배)으로 저베타를 사서 30%까지 채움(분기마다 30% 초과분은 기초로)
- 저베타 고배당 9종목(kospi200_highdiv_cc.py 스크리닝): 바구니 안 비중 '동일' / '배당'(직전 12개월 배당수익률 비례) / '역변동'(직전 60일 변동성 역수 비례), 매월 첫 거래일 재계산
- 급락 해 = 그해 안에 코스피200이 고점 대비 15% 이상 빠진 해
시세: yfinance(야후), KRX 요청 없음. 거래비용·보수·세금 미반영. 코스닥150은 2015-11부터
실행: python -I compare3.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '세기초_비교'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR, CAP = 0.03, 0.10, 0.30
BASES = {'반도체': ['005930.KS', '000660.KS'], '코스피200': ['069500.KS'], '코스닥150': ['229200.KS']}
CALL_ON = {'반도체': '069500.KS', '코스피200': '069500.KS', '코스닥150': '229200.KS'}
LOW = {'맥쿼리인프라': '088980.KS', 'SK텔레콤': '017670.KS', '기업은행': '024110.KS', 'KT&G': '033780.KS', 'KT': '030200.KS',
       'DB손해보험': '005830.KS', 'LG유플러스': '032640.KS', '현대해상': '001450.KS', '삼성화재': '000810.KS'}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


tick = sorted({t for v in BASES.values() for t in v} | set(LOW.values()) | set(CALL_ON.values()))
raw = yf.download(tick, start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
close, divs = raw['Close'], raw['Dividends'].fillna(0)
pr_all = close.pct_change(fill_method=None)
dy_all = divs.reindex(close.index).fillna(0) / close.shift(1)


def ew(tks):
    ok = close[tks].notna().all(axis=1)
    return pr_all[tks].mean(axis=1)[ok], dy_all[tks].mean(axis=1)[ok]


def low_basket(scheme):
    tks = list(LOW.values())
    c = close[tks]
    ok = c.notna().all(axis=1)
    idx = c.index[ok]
    pr, dy = pr_all[tks].loc[idx], dy_all[tks].loc[idx]
    per = idx.to_period('M')
    firsts = pd.Series(idx, index=idx).groupby(per).first()
    w = pd.DataFrame(np.nan, index=idx, columns=tks)
    for d in firsts:
        if scheme == '동일':
            x = pd.Series(1.0, index=tks)
        elif scheme == '배당':
            x = dy.loc[:d].iloc[-252:].sum().clip(lower=1e-4)
        else:
            x = 1 / pr.loc[:d].iloc[-60:].std().clip(lower=1e-4)
        w.loc[d] = x / x.sum()
    w = w.ffill()
    return (pr * w).sum(axis=1), (dy * w).sum(axis=1)


LOWS = {s: low_basket(s) for s in ('동일', '배당', '역변동')}
k200 = close['069500.KS'].dropna()


def run(base, structure='정적', target=0.10, k=0.5, scheme='동일', call=True, dist=True):
    b_pr, b_dy = ew(BASES[base])
    l_pr, l_dy = LOWS[scheme]
    cs = close[CALL_ON[base]]
    df = pd.concat([b_pr.rename('b'), b_dy.rename('bd'), l_pr.rename('l'), l_dy.rename('ld'), cs.rename('c')], axis=1).dropna()
    vol = np.log(df['c']).diff().rolling(20).std() * sqrt(252)
    df = df.iloc[25:]
    dates = df.index
    per = dates.to_period('M')
    mfirst = set(pd.Series(dates, index=dates).groupby(per).first())
    mlast = set(pd.Series(dates, index=dates).groupby(per).last())
    qfirst = set(pd.Series(dates, index=dates).groupby(dates.to_period('Q')).first())
    mf = sorted(mfirst)
    exp_m = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}
    if structure == '정적':
        vb, vl = 1 - CAP, CAP
    elif structure == '재투자':
        vb, vl = 1.0, 0.0
    else:  # 기초만
        vb, vl = 1.0, 0.0
    pool = 0.0
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
            if structure == '정적':
                vb, vl = tot * (1 - CAP), tot * CAP
            elif vl > CAP * tot:
                vb, vl = tot * (1 - CAP), tot * CAP
        if call and d in mfirst and t_exp is None and i < len(dates) - 1:
            sig = max(float(vol[d]) if not np.isnan(vol[d]) else SIG_FLOOR, SIG_FLOOR)
            K = df.at[d, 'c']
            t_exp = exp_m[d]
            n_call = k * vb / K
            prem = n_call * bs_call(K, K, sig, max((t_exp - d).days, 1) / 365)
            pool += prem
        liab = n_call * bs_call(df.at[d, 'c'], K, sig, max((t_exp - d).days, 0) / 365) if n_call else 0.0
        nav_pre = vb + vl + pool - liab
        if d in mlast:
            dist_d = nav_pre * target / 12 if dist else 0.0
            extra = pool - dist_d
            pool = 0.0
            if structure == '재투자' and extra > 0:
                room = max(CAP * (vb + vl + extra) - vl, 0.0)
                to_l = min(extra, room)
                vl += to_l
                vb += extra - to_l
            else:
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


def summary(o):
    w, nav = o['wealth'], o['nav']
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    m = nav.groupby(nav.index.to_period('M')).first()
    ch5 = (m.shift(-60) / m - 1).dropna() * 100
    dd = nav / nav.cummax() - 1
    return {'기간': f'{w.index[0]:%Y-%m}~{w.index[-1]:%Y-%m}',
            '연총수익%': ((w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1) * 100,
            '원금연변화%': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100,
            '최대낙폭%': (w / w.cummax() - 1).min() * 100, '원금최대하락%': dd.min() * 100,
            '원금줄어든해': None, '5년보유_원금감소비율%': (ch5 < 0).mean() * 100 if len(ch5) else np.nan,
            '5년보유_최악%': ch5.min() if len(ch5) else np.nan,
            '연프리미엄%': (o['prem'] / nav.shift(1)).sum() / yrs * 100}


def yearly(o):
    w, nav = o['wealth'], o['nav']
    return pd.DataFrame({'총수익%': w.groupby(w.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1) * 100,
                         '원금%': nav.groupby(nav.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1) * 100})


# 급락 해
kdd = k200.groupby(k200.index.year).apply(lambda x: (x / x.cummax() - 1).min())
crash_years = set(kdd[kdd <= -0.15].index)

# ---------------------------------------------------------------- 1. 요약
rows, yr_tabs = [], {}
for base in BASES:
    alone = run(base, structure='기초만', call=False, dist=False)
    s = summary(alone)
    s.update({'기초': base, '구조': '기초만(콜·분배 없음)', '목표': '-'})
    yt = yearly(alone)
    s['원금줄어든해'] = f"{(yt['원금%'] < 0).sum()}/{len(yt)}"
    rows.append(s)
    yr_tabs[(base, '기초만')] = yt
    for structure in ('정적', '재투자'):
        for tgt in (0.10, 0.15):
            o = run(base, structure, tgt)
            s = summary(o)
            yt = yearly(o)
            s.update({'기초': base, '구조': structure, '목표': f'{int(tgt*100)}%', '원금줄어든해': f"{(yt['원금%'] < 0).sum()}/{len(yt)}"})
            rows.append(s)
            yr_tabs[(base, structure, tgt)] = yt
tab = pd.DataFrame(rows)[['기초', '구조', '목표', '기간', '연총수익%', '원금연변화%', '최대낙폭%', '원금최대하락%', '원금줄어든해',
                          '5년보유_원금감소비율%', '5년보유_최악%', '연프리미엄%']].round(1)
tab.to_csv(OUT / '1_요약.csv', index=False, encoding='utf-8-sig')

# ---------------------------------------------------------------- 2. 연도별(정적 70/30, 목표 10%·15%)
yrs_all = sorted(set().union(*[set(t.index) for t in yr_tabs.values()]))
ytab = pd.DataFrame(index=yrs_all)
ytab['급락해'] = ['●' if y in crash_years else '' for y in yrs_all]
ytab['코스피200 연중최대하락%'] = (kdd * 100).reindex(yrs_all).round(1)
for base in BASES:
    ytab[f'{base} 단독 총수익%'] = yr_tabs[(base, '기초만')]['총수익%'].reindex(yrs_all)
    ytab[f'{base} 정적10% 원금%'] = yr_tabs[(base, '정적', 0.10)]['원금%'].reindex(yrs_all)
    ytab[f'{base} 정적15% 원금%'] = yr_tabs[(base, '정적', 0.15)]['원금%'].reindex(yrs_all)
ytab = ytab.round(1)
ytab.to_csv(OUT / '2_연도별.csv', encoding='utf-8-sig')

# ---------------------------------------------------------------- 3. 급락 유무별 평균
grp = []
for base in BASES:
    for key, lab in [((base, '기초만'), '기초만'), ((base, '정적', 0.10), '정적 10%'), ((base, '정적', 0.15), '정적 15%'),
                     ((base, '재투자', 0.10), '재투자 10%'), ((base, '재투자', 0.15), '재투자 15%')]:
        t = yr_tabs[key]
        c = t[t.index.isin(crash_years)]
        n = t[~t.index.isin(crash_years)]
        grp.append({'기초': base, '안': lab, '급락해 수': len(c), '급락해 평균 총수익%': c['총수익%'].mean(), '급락해 평균 원금%': c['원금%'].mean(),
                    '평온해 수': len(n), '평온해 평균 총수익%': n['총수익%'].mean(), '평온해 평균 원금%': n['원금%'].mean()})
gtab = pd.DataFrame(grp).round(1)
gtab.to_csv(OUT / '3_급락유무별.csv', index=False, encoding='utf-8-sig')

# ---------------------------------------------------------------- 4. 5년 구간별(정적, 목표 10%·15%)
blocks = [(2009, 2013), (2014, 2018), (2019, 2023), (2024, 2026)]
brow = []
for base in BASES:
    for key, lab in [((base, '기초만'), '기초만'), ((base, '정적', 0.10), '정적 10%'), ((base, '정적', 0.15), '정적 15%')]:
        t = yr_tabs[key]
        r = {'기초': base, '안': lab}
        for a, b in blocks:
            x = t.loc[(t.index >= a) & (t.index <= b)]
            if len(x) == 0:
                r[f'{a}~{b} 총수익(연)%'] = np.nan
                r[f'{a}~{b} 원금(누적)%'] = np.nan
                continue
            r[f'{a}~{b} 총수익(연)%'] = ((1 + x['총수익%'] / 100).prod() ** (1 / len(x)) - 1) * 100
            r[f'{a}~{b} 원금(누적)%'] = ((1 + x['원금%'] / 100).prod() - 1) * 100
        brow.append(r)
btab = pd.DataFrame(brow).round(1)
btab.to_csv(OUT / '4_5년구간별.csv', index=False, encoding='utf-8-sig')

# ---------------------------------------------------------------- 5. 저베타 바구니 비중 방식(반도체·코스피200, 정적)
wrow = []
for base in ('반도체', '코스피200'):
    for scheme in ('동일', '배당', '역변동'):
        for tgt in (0.10, 0.15):
            o = run(base, '정적', tgt, scheme=scheme)
            s = summary(o)
            yt = yearly(o)
            s.update({'기초': base, '바구니 비중': scheme, '목표': f'{int(tgt*100)}%', '원금줄어든해': f"{(yt['원금%'] < 0).sum()}/{len(yt)}"})
            wrow.append(s)
wtab = pd.DataFrame(wrow)[['기초', '바구니 비중', '목표', '연총수익%', '원금연변화%', '최대낙폭%', '원금최대하락%', '원금줄어든해',
                           '5년보유_원금감소비율%', '5년보유_최악%']].round(1)
wtab.to_csv(OUT / '5_바구니비중방식.csv', index=False, encoding='utf-8-sig')

pd.set_option('display.width', 300)
pd.set_option('display.max_columns', 30)
print('급락 해(코스피200 연중 -15% 이상):', sorted(crash_years))
print('\n[1. 요약]')
print(tab.to_string(index=False))
print('\n[2. 연도별]')
print(ytab.to_string())
print('\n[3. 급락 유무별 연평균]')
print(gtab.to_string(index=False))
print('\n[4. 5년 구간별]')
print(btab.to_string(index=False))
print('\n[5. 저베타 바구니 비중 방식]')
print(wtab.to_string(index=False))
