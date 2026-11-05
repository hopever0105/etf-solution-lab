"""월분배 커버드콜 조합 전체 비교: 기초(반도체·한미반도체·AI 밸류체인 지수 A·B20식) × 저베타 고배당 바구니 × 분배 목표 (포트폴리오용, 실매매 없음)

공통 규칙
- 기초 70 + 저베타 고배당 30 (B20식은 지수 A 80 + 정유·가스 20, 저베타 없음), 분기 리셋, 묶음 안 비중은 고정(일간 리셋 근사)
- 콜: KODEX 200(069500) 1개월 ATM 콜을 기초 평가액의 50%만큼 매월 매도, 블랙숄즈(σ=직전 20일 실현변동성, 하한 10%, r=3%)
- 분배: 매월 NAV × 목표/12 고정(10%, 12%). 프리미엄+배당이 남으면 재투자, 모자라면 자산 매도
- 상장 요건 점검: 구성 종목 10개 이상, 한 종목 30% 이하
- 지수 A 비중: 2026-09-30 구성 10종목을 '현재 시가총액(야후) 비중 + 종목당 25% 상한'으로 근사해 과거에도 고정(실제 지수는 분기마다 종목·비중 변경 → 사후 편향 있음)
기간: 전체(종목 데이터가 다 있는 첫날부터) + 공통 2017-06~2026-10(지수 A 종목이 모두 상장된 뒤)
시세: yfinance(야후), KRX 요청 없음. 거래비용·보수·세금 미반영
실행: python -I combos.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '조합_전체'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR, K200 = 0.03, 0.10, '069500.KS'
T = {'삼성전자': '005930.KS', 'SK하이닉스': '000660.KS', '한미반도체': '042700.KS', '리노공업': '058470.KQ', 'DB하이텍': '000990.KS',
     '이오테크닉스': '039030.KQ', '원익IPS': '240810.KQ', '삼성전기': '009150.KS', '두산에너빌리티': '034020.KS', 'NAVER': '035420.KS',
     'HD현대일렉트릭': '267260.KS', '한국전력': '015760.KS', '이수페타시스': '007660.KS',
     'KT': '030200.KS', 'KT&G': '033780.KS', 'DB손해보험': '005830.KS', 'SK텔레콤': '017670.KS', '삼성화재': '000810.KS',
     '현대해상': '001450.KS', 'LG유플러스': '032640.KS', '맥쿼리인프라': '088980.KS', '기업은행': '024110.KS',
     'S-Oil': '010950.KS', 'SK이노베이션': '096770.KS', 'GS': '078930.KS'}
IDX_A = ['SK하이닉스', '삼성전자', '삼성전기', '두산에너빌리티', 'NAVER', '한미반도체', 'HD현대일렉트릭', '한국전력', '이수페타시스', '원익IPS']

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, Tm, r=R):
    if Tm <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * Tm) / (sig * sqrt(Tm))
    return S * N(d1) - K * exp(-r * Tm) * N(d1 - sig * sqrt(Tm))


def cap_weights(mc, cap=0.25):
    w = mc / mc.sum()
    for _ in range(50):
        over = w > cap
        if not over.any():
            break
        ex = (w[over] - cap).sum()
        w[over] = cap
        w[~over] += ex * w[~over] / w[~over].sum()
    return w


# 지수 A 근사 비중
mcap = {}
for n in IDX_A:
    try:
        mcap[n] = float(yf.Ticker(T[n]).fast_info['market_cap'])
    except Exception:
        mcap[n] = np.nan
mc = pd.Series(mcap).fillna(pd.Series(mcap).median())
WA = cap_weights(mc)

tick = sorted(set(T.values()) | {K200})
raw = yf.download(tick, start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
inv = {v: k for k, v in T.items()}
close = raw['Close'].rename(columns=inv)
divs = raw['Dividends'].rename(columns=inv).fillna(0)
pr_all = close.pct_change(fill_method=None)
dy_all = divs.reindex(close.index).fillna(0) / close.shift(1)
kc = close[K200] if K200 in close.columns else raw['Close'][K200]


def bsk(w):
    if isinstance(w, (list, tuple)):
        w = {n: 1.0 for n in w}  # 저베타 바구니는 동일가중
    w = pd.Series(w, dtype=float)
    w = w / w.sum()
    names = list(w.index)
    ok = close[names].notna().all(axis=1)
    return (pr_all[names] * w).sum(axis=1)[ok], (dy_all[names] * w).sum(axis=1)[ok]


BASES = {
    '반도체2 (삼전35·하닉35)': {'삼성전자': 35, 'SK하이닉스': 35},
    '반도체3a (삼전25·하닉25·한미20)': {'삼성전자': 25, 'SK하이닉스': 25, '한미반도체': 20},
    '반도체3b (삼전30·하닉30·한미10)': {'삼성전자': 30, 'SK하이닉스': 30, '한미반도체': 10},
    '반도체7 (삼전25·하닉25·한미6·리노4·DB하이텍4·이오3·원익3)': {'삼성전자': 25, 'SK하이닉스': 25, '한미반도체': 6, '리노공업': 4, 'DB하이텍': 4, '이오테크닉스': 3, '원익IPS': 3},
    'AI 밸류체인 지수 A 10종목': {n: WA[n] * 70 for n in IDX_A},
}
LOWS = {
    '3: KT·KT&G·DB손보': ['KT', 'KT&G', 'DB손해보험'],
    '3: 보험 DB손보·삼성화재·현대해상': ['DB손해보험', '삼성화재', '현대해상'],
    '3: KT·KT&G·SK텔레콤': ['KT', 'KT&G', 'SK텔레콤'],
    '7: KT·KT&G·DB손보·SKT·삼성화재·현대해상·LGU+': ['KT', 'KT&G', 'DB손해보험', 'SK텔레콤', '삼성화재', '현대해상', 'LG유플러스'],
    '9: 위 7 + 맥쿼리인프라·기업은행': ['KT', 'KT&G', 'DB손해보험', 'SK텔레콤', '삼성화재', '현대해상', 'LG유플러스', '맥쿼리인프라', '기업은행'],
}


def run(bw, lw, w_low, target, k=0.5, start=None, fee=0.0, haircut=0.0, tenor='M', cser=None):
    """fee: 연 총보수(매일 자산에서 차감), haircut: 옵션 호가 차이로 깎이는 프리미엄 비율, tenor: 'M' 월물 / 'W' 5거래일,
    cser: 콜 기초 가격 시리즈(없으면 코스피200)"""
    b_pr, b_dy = bsk(bw)
    parts = [b_pr.rename('b'), b_dy.rename('bd'), (cser if cser is not None else kc).rename('c')]
    if lw:
        l_pr, l_dy = bsk(lw)
        parts += [l_pr.rename('l'), l_dy.rename('ld')]
    df = pd.concat(parts, axis=1).dropna()
    if not lw:
        df['l'] = 0.0
        df['ld'] = 0.0
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
    navs, dsts, prems, divs_ = [], [], [], []
    for i, d in enumerate(dates):
        dist_d = prem_d = div_d = 0.0
        if i:
            div_d = vb * df.at[d, 'bd'] + vl * df.at[d, 'ld']
            pool += div_d
            vb *= (1 + df.at[d, 'b']) * (1 - fee / 252)
            vl *= (1 + df.at[d, 'l']) * (1 - fee / 252)
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
            prem_d = n_call * bs_call(K, K, sig, max((t_exp - d).days, 1) / 365) * (1 - haircut)
            pool += prem_d
        liab = n_call * bs_call(df.at[d, 'c'], K, sig, max((t_exp - d).days, 0) / 365) if n_call else 0.0
        nav_pre = vb + vl + pool - liab
        if d in mlast:
            dist_d = nav_pre * target / 12
            extra, pool = pool - dist_d, 0.0
            tot = vb + vl
            vb += extra * vb / tot
            vl += extra * vl / tot
        navs.append(nav_pre - dist_d)
        dsts.append(dist_d)
        prems.append(prem_d)
        divs_.append(div_d)
    o = pd.DataFrame({'nav': navs, 'dist': dsts, 'prem': prems, 'div': divs_}, index=dates)
    r = (o['nav'] + o['dist']) / o['nav'].shift(1) - 1
    o['wealth'] = (1 + r.fillna(0)).cumprod()
    return o


def summ(o):
    w, nav = o['wealth'], o['nav']
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    ret = w.pct_change().dropna()
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    m = nav.groupby(nav.index.to_period('M')).first()
    ch5 = (m.shift(-60) / m - 1).dropna() * 100
    yt = nav.groupby(nav.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1)
    pre = o.loc[:'2023-12-31']
    yp = (pre.index[-1] - pre.index[0]).days / 365.25
    return {'기간': f'{w.index[0]:%Y-%m}~{w.index[-1]:%Y-%m}', '연총수익%': cagr * 100, '수익/변동성': cagr / (ret.std() * sqrt(252)),
            '최대낙폭%': (w / w.cummax() - 1).min() * 100, '원금연변화%': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100,
            '원금최대하락%': (nav / nav.cummax() - 1).min() * 100, '원금줄어든해': f'{(yt < 0).sum()}/{len(yt)}',
            '5년보유_원금감소%': (ch5 < 0).mean() * 100 if len(ch5) else np.nan, '5년보유_최악%': ch5.min() if len(ch5) else np.nan,
            '급등전_원금연변화%': ((pre['nav'].iloc[-1] / pre['nav'].iloc[0]) ** (1 / yp) - 1) * 100}


def check(bw, lw, w_low):
    w = {n: v * (0.7 / sum(bw.values())) / 0.7 * (1 - w_low) for n, v in bw.items()}
    w = {n: v / sum(bw.values()) * (1 - w_low) * 100 for n, v in bw.items()}
    for n in (lw or []):
        w[n] = w.get(n, 0) + w_low * 100 / len(lw)
    ok = len(w) >= 10 and max(w.values()) <= 30 + 1e-9
    return len(w), max(w.values()), '✓' if ok else '✗'


rows = []
for bname, bw in BASES.items():
    for lname, lw in LOWS.items():
        for tgt in (0.10, 0.12):
            for period, st in (('전체', None), ('공통 2017-06~', '2017-06-01')):
                o = run(bw, lw, 0.3, tgt, start=st)
                n, mx, ok = check(bw, lw, 0.3)
                s = summ(o)
                s.update({'기초(70)': bname, '저베타(30)': lname, '목표': f'{int(tgt*100)}%', '구간': period, '종목수': n, '최대비중%': round(mx, 1), '상장요건': ok})
                rows.append(s)
# B20식 + 커버드콜(저베타 없음): 지수 A 80 + 정유·가스 20, 콜은 지수 A 부분 50%
b20 = {n: WA[n] * 80 for n in IDX_A}
for tgt in (0.10, 0.12):
    for period, st in (('전체', None), ('공통 2017-06~', '2017-06-01')):
        o = run(b20, ['S-Oil', 'SK이노베이션', 'GS'], 0.2, tgt, start=st)
        s = summ(o)
        w = {n: v for n, v in b20.items()}
        w.update({x: 20 / 3 for x in ['S-Oil', 'SK이노베이션', 'GS']})
        s.update({'기초(70)': 'B20식: 지수 A 80', '저베타(30)': '정유·가스 20 (S-Oil·SK이노·GS)', '목표': f'{int(tgt*100)}%', '구간': period,
                  '종목수': len(w), '최대비중%': round(max(w.values()), 1), '상장요건': '✓' if len(w) >= 10 and max(w.values()) <= 30 else '✗'})
        rows.append(s)
cols = ['구간', '기초(70)', '저베타(30)', '목표', '종목수', '최대비중%', '상장요건', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%',
        '원금최대하락%', '원금줄어든해', '5년보유_원금감소%', '5년보유_최악%', '급등전_원금연변화%']
tab = pd.DataFrame(rows)[cols].round(2)
tab.to_csv(OUT / '조합_전체.csv', index=False, encoding='utf-8-sig')
pd.Series(WA * 100).round(1).to_csv(OUT / '지수A_근사비중.csv', encoding='utf-8-sig')

pd.set_option('display.width', 400)
pd.set_option('display.max_columns', 30)
pd.set_option('display.max_colwidth', 40)
print('지수 A 근사 비중(현재 시총, 25% 상한):', (WA * 100).round(1).to_dict())
for period in ('전체', '공통 2017-06~'):
    for tgt in ('10%', '12%'):
        x = tab[(tab['구간'] == period) & (tab['목표'] == tgt)].sort_values('5년보유_최악%', ascending=False)
        print(f'\n[{period} · 목표 {tgt}] (5년 보유 최악 원금 변화가 좋은 순)')
        print(x.drop(columns=['구간', '목표']).to_string(index=False))
