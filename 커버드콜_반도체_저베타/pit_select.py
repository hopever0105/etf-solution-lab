"""저베타 고배당을 '그 시점 정보로만' 다시 고르는 백테스트 (사후 선택 편향 제거, 포트폴리오용, 실매매 없음)

리밸런싱 날(연 1회 1월 첫 거래일 / 반기 1회 1·7월 첫 거래일)마다, 그날 이전 데이터만으로
  ① 직전 60거래일 하루 평균 거래대금 30억 원 이상
  ② 직전 2년(504거래일) 일간 수익률 기준 코스피(^KS11) 대비 베타 ≤ 한도(기본 0.5)
  ③ 통과 종목 중 직전 12개월 배당수익률 상위 최대 7종목, 동일가중
  - 'strict' : 한도를 끝까지 지킴. 전체 10종목이 안 되면 반도체 보조 종목(리노공업·DB하이텍·이오테크닉스·원익IPS 순)을 각 1%씩 넣어 채움(반도체 70에서 덜어냄)
  - 'fill'   : 7종목이 안 되면 베타가 낮은 순서로 한도 밖 종목을 채움
  교체 비용: 바뀐 비중 × 0.2%
반도체 70: 삼성전자 25 · SK하이닉스 25 · 한미반도체 20 (보조 종목 편입 시 비례 축소)
콜: 코스피 지수(^KS11) 월물 ATM, 반도체 평가액의 50%. 분배 연 10% 고정. 총보수 0.5% + 옵션 프리미엄 10% 감소. 세금 미반영
후보: 반도체 제외 국내 대형·배당주 약 45종목(현재 상장 종목만 → 상장폐지 종목이 빠진 생존 편향은 남음)
시세: yfinance(야후), KRX 요청 없음
실행: python -I pit_select.py
"""
import sys
from math import log, sqrt, exp, erf
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent / '시점선정'
OUT.mkdir(exist_ok=True)
R, SIG_FLOOR, FEE, HC, TC = 0.03, 0.10, 0.005, 0.10, 0.002
SEMI = {'삼성전자': '005930.KS', 'SK하이닉스': '000660.KS', '한미반도체': '042700.KS'}
FILLERS = {'리노공업': '058470.KQ', 'DB하이텍': '000990.KS', '이오테크닉스': '039030.KQ', '원익IPS': '240810.KQ'}
UNIV = {'KT&G': '033780.KS', 'KT': '030200.KS', 'SK텔레콤': '017670.KS', 'LG유플러스': '032640.KS', 'DB손해보험': '005830.KS',
        '삼성화재': '000810.KS', '현대해상': '001450.KS', '삼성생명': '032830.KS', '한화생명': '088350.KS', 'KB금융': '105560.KS',
        '신한지주': '055550.KS', '하나금융지주': '086790.KS', '우리금융지주': '316140.KS', '기업은행': '024110.KS', 'BNK금융지주': '138930.KS',
        'DGB금융지주': '139130.KS', '삼성카드': '029780.KS', 'NH투자증권': '005940.KS', '삼성증권': '016360.KS', '한국금융지주': '071050.KS',
        '키움증권': '039490.KS', '맥쿼리인프라': '088980.KS', '한국전력': '015760.KS', '한국가스공사': '036460.KS', '지역난방공사': '071320.KS',
        'S-Oil': '010950.KS', 'GS': '078930.KS', 'SK이노베이션': '096770.KS', 'POSCO홀딩스': '005490.KS', '현대차': '005380.KS',
        '기아': '000270.KS', '현대모비스': '012330.KS', '유한양행': '000100.KS', '녹십자': '006280.KS', '농심': '004370.KS',
        'CJ제일제당': '097950.KS', '오리온홀딩스': '001800.KS', '오뚜기': '007310.KS', 'LG생활건강': '051900.KS', '아모레퍼시픽': '090430.KS',
        '롯데쇼핑': '023530.KS', '이마트': '139480.KS', 'BGF리테일': '282330.KS', 'GS리테일': '007070.KS', '현대건설': '000720.KS',
        '삼성물산': '028260.KS', 'LG': '003550.KS', 'SK': '034730.KS', '한국타이어앤테크놀로지': '161390.KS', '에스원': '012750.KS'}
ALL = {**SEMI, **FILLERS, **UNIV}

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))


def bs_call(S, K, sig, T, r=R):
    if T <= 1e-9:
        return max(S - K, 0.0)
    d1 = (log(S / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    return S * N(d1) - K * exp(-r * T) * N(d1 - sig * sqrt(T))


raw = yf.download(list(ALL.values()), start='2004-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
inv = {v: k for k, v in ALL.items()}
close = raw['Close'].rename(columns=inv)
volu = raw['Volume'].rename(columns=inv)
divs = raw['Dividends'].rename(columns=inv).fillna(0)
ks = yf.download('^KS11', start='2004-01-01', end='2026-10-31', auto_adjust=False, progress=False)['Close']
ks = ks.iloc[:, 0] if isinstance(ks, pd.DataFrame) else ks
idx = close.index.intersection(ks.dropna().index)
close, volu, divs, ks = close.loc[idx], volu.loc[idx], divs.reindex(idx).fillna(0), ks.loc[idx]
ret = close.pct_change(fill_method=None)
dyl = divs / close.shift(1)
kr = ks.pct_change()
tv = (close * volu).rolling(60, min_periods=40).mean() / 1e8
dy12 = (divs.rolling(252, min_periods=200).sum() / close)
vol20 = np.log(ks).diff().rolling(20).std() * sqrt(252)


def select(d, cap, mode):
    i = close.index.get_loc(d)
    if i < 504:
        return []
    win = slice(close.index[i - 504], close.index[i - 1])
    rows = []
    for n in UNIV:
        r = ret[n].loc[win]
        if r.notna().sum() < 400 or np.isnan(tv[n].iloc[i - 1]) or tv[n].iloc[i - 1] < 30 or np.isnan(dy12[n].iloc[i - 1]):
            continue
        both = pd.concat([r, kr.loc[win]], axis=1).dropna()
        beta = both.iloc[:, 0].cov(both.iloc[:, 1]) / both.iloc[:, 1].var()
        rows.append((n, beta, dy12[n].iloc[i - 1]))
    t = pd.DataFrame(rows, columns=['n', 'beta', 'dy'])
    ok = t[t['beta'] <= cap].sort_values('dy', ascending=False)
    pick = list(ok['n'].head(7))
    if mode == 'fill' and len(pick) < 7:
        rest = t[~t['n'].isin(pick)].sort_values('beta')
        pick += list(rest['n'].head(7 - len(pick)))
    return pick, t.set_index('n')


def build_dates(freq):
    s = pd.Series(close.index, index=close.index)
    if freq == 'Y':
        return set(s.groupby(close.index.year).first())
    return set(s.groupby([close.index.year, (close.index.month - 1) // 6]).first())


def run(freq='Y', cap=0.5, mode='strict', start='2009-01-01', tgt=0.10, bonus=False):
    """bonus=True: 그해 쌓인 잉여(프리미엄+배당−월 분배)가 플러스면 12월 마지막 거래일에 추가 분배(특별분배)"""
    ysur = 0.0
    rdates = build_dates(freq)
    dates = close.loc[start:].index
    per = dates.to_period('M')
    mfirst = set(pd.Series(dates, index=dates).groupby(per).first())
    mlast = set(pd.Series(dates, index=dates).groupby(per).last())
    mf = sorted(mfirst)
    exp_m = {d0: (dates[dates.get_loc(mf[i + 1]) - 1] if i + 1 < len(mf) else dates[-1]) for i, d0 in enumerate(mf)}
    val, pool = {}, 0.0
    n_call = K = sig = t_exp = None
    hist, navs, dsts, prems, dvs = [], [], [], [], []
    target = {}
    for i, d in enumerate(dates):
        prem_d = dist_d = div_d = 0.0
        if i:
            for n in list(val):
                if dyl.at[d, n] > 0:
                    x = val[n] * dyl.at[d, n]
                    div_d += x
                    pool += x
                r = ret.at[d, n]
                val[n] *= (1 + (0.0 if np.isnan(r) else r)) * (1 - FEE / 252)
        if t_exp is not None and d == t_exp:
            pay = n_call * max(ks[d] - K, 0.0)
            s_tot = sum(val[n] for n in val if n in SEMI or n in FILLERS)
            for n in val:
                if n in SEMI or n in FILLERS:
                    val[n] -= pay * val[n] / s_tot
            n_call = K = sig = t_exp = None
        tot = sum(val.values()) if val else 1.0
        if i == 0 or d in rdates:
            pick, info = select(d, cap, mode)
            n_fill = max(0, 10 - 3 - len(pick))
            fill = [f for f in FILLERS if not np.isnan(close.at[d, f])][:n_fill]
            semi_w = 0.70 - 0.01 * len(fill)
            target = {'삼성전자': semi_w * 25 / 70, 'SK하이닉스': semi_w * 25 / 70, '한미반도체': semi_w * 20 / 70}
            target.update({f: 0.01 for f in fill})
            for n in pick:
                target[n] = 0.30 / len(pick)
            if not pick:
                target = {k: v / 0.70 for k, v in target.items()}
            new = {n: tot * w for n, w in target.items()}
            turnover = sum(abs(new.get(n, 0) - val.get(n, 0)) for n in set(new) | set(val)) / 2 if val else 0.0
            val = {n: v - turnover * TC * w for (n, v), w in zip(new.items(), target.values())}
            hist.append({'날짜': f'{d:%Y-%m}', '저베타 종목': ', '.join(pick), '저베타 수': len(pick), '보조 반도체': ', '.join(fill),
                         '종목 수': len(target), '평균 베타': round(info.loc[pick, 'beta'].mean(), 2) if pick else np.nan,
                         '최대 베타': round(info.loc[pick, 'beta'].max(), 2) if pick else np.nan,
                         '평균 배당%': round(info.loc[pick, 'dy'].mean() * 100, 2) if pick else np.nan})
        elif d.month in (1, 4, 7, 10) and d in mfirst:  # 분기 비중 되돌림(종목은 그대로)
            val = {n: tot * w for n, w in target.items()}
        if d in mfirst and t_exp is None and i < len(dates) - 1:
            sig = max(float(vol20[d]) if not np.isnan(vol20[d]) else SIG_FLOOR, SIG_FLOOR)
            K = ks[d]
            t_exp = exp_m[d]
            s_tot = sum(val[n] for n in val if n in SEMI or n in FILLERS)
            n_call = 0.5 * s_tot / K
            prem_d = n_call * bs_call(K, K, sig, max((t_exp - d).days, 1) / 365) * (1 - HC)
            pool += prem_d
        liab = n_call * bs_call(ks[d], K, sig, max((t_exp - d).days, 0) / 365) if n_call else 0.0
        nav_pre = sum(val.values()) + pool - liab
        if d in mlast:
            dist_d = nav_pre * tgt / 12
            extra, pool = pool - dist_d, 0.0
            ysur += extra
            t2 = sum(val.values())
            val = {n: v + extra * v / t2 for n, v in val.items()}
            if bonus and d.month == 12:
                if ysur > 0:
                    t2 = sum(val.values())
                    val = {n: v - ysur * v / t2 for n, v in val.items()}
                    dist_d += ysur
                ysur = 0.0
        navs.append(nav_pre - dist_d)
        dsts.append(dist_d)
        prems.append(prem_d)
        dvs.append(div_d)
    o = pd.DataFrame({'nav': navs, 'dist': dsts, 'prem': prems, 'div': dvs}, index=dates)
    r = (o['nav'] + o['dist']) / o['nav'].shift(1) - 1
    o['wealth'] = (1 + r.fillna(0)).cumprod()
    return o, pd.DataFrame(hist)


def summ(o):
    w, nav = o['wealth'], o['nav']
    yrs = (w.index[-1] - w.index[0]).days / 365.25
    cagr = (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1
    m = nav.groupby(nav.index.to_period('M')).first()
    ch5 = (m.shift(-60) / m - 1).dropna() * 100
    x = w.loc['2007-10-01':'2009-03-31']
    y = w.loc['2026-06-01':'2026-08-31']
    return {'기간': f'{w.index[0]:%Y-%m}~{w.index[-1]:%Y-%m}', '연총수익%': cagr * 100,
            '수익/변동성': cagr / (w.pct_change().std() * sqrt(252)), '최대낙폭%': (w / w.cummax() - 1).min() * 100,
            '원금연변화%': ((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) * 100, '5년보유_원금감소%': (ch5 < 0).mean() * 100,
            '5년보유_최악%': ch5.min(), '2008낙폭%': (x / x.cummax() - 1).min() * 100 if len(x) > 20 else np.nan,
            '2026여름낙폭%': (y / y.cummax() - 1).min() * 100}


cases = [
    ('베타≤0.5 고정, 모자라면 반도체 1%로 채움, 연 1회', dict(freq='Y', cap=0.5, mode='strict')),
    ('베타≤0.5 고정, 모자라면 반도체 1%로 채움, 반기 1회', dict(freq='H', cap=0.5, mode='strict')),
    ('베타≤0.5, 모자라면 베타 낮은 순 채움, 연 1회', dict(freq='Y', cap=0.5, mode='fill')),
    ('베타≤0.6 고정, 연 1회', dict(freq='Y', cap=0.6, mode='strict')),
]
rows, hists = [], {}
for st in ('2007-02-01', '2009-05-01'):
    for lab, kw in cases:
        o, h = run(start=st, **kw)
        s = summ(o)
        s.update({'안': lab, '시작': st[:7], '평균 저베타 수': round(h['저베타 수'].mean(), 1), '보조 반도체 쓴 횟수': int((h['보조 반도체'] != '').sum()),
                  '평균 선정 베타': round(h['평균 베타'].mean(), 2)})
        rows.append(s)
        hists[(st, lab)] = h
tab = pd.DataFrame(rows)[['시작', '안', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%', '5년보유_원금감소%', '5년보유_최악%',
                          '2008낙폭%', '2026여름낙폭%', '평균 저베타 수', '평균 선정 베타', '보조 반도체 쓴 횟수']].round(2)
tab.to_csv(OUT / '시점선정_비교.csv', index=False, encoding='utf-8-sig')
main = hists[('2007-02-01', cases[0][0])]
main.to_csv(OUT / '시점선정_연도별종목_베타0.5_연1회.csv', index=False, encoding='utf-8-sig')
hists[('2007-02-01', cases[1][0])].to_csv(OUT / '시점선정_종목_베타0.5_반기.csv', index=False, encoding='utf-8-sig')
# 종목별 선정 횟수
cnt = pd.Series([x for s in main['저베타 종목'] for x in s.split(', ') if x]).value_counts()

pd.set_option('display.width', 320)
pd.set_option('display.max_colwidth', 80)
print('[비교] 비교 대상: 지금 고정 7종목(사후 선택) = 2007~ 총수익 24.0%, MDD -53.8%, 5년 원금감소 5.1%, 최악 -15.1% (ext20.py)')
print(tab.to_string(index=False))
print('\n[베타≤0.5 연 1회, 해마다 뽑힌 종목]')
print(main.to_string(index=False))
print('\n[20년 동안 뽑힌 횟수]')
print(cnt.to_string())

