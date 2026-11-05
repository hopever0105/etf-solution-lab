"""반도체(삼성전자·SK하이닉스)와 상관 낮은 국내 섹터 후보 스크리닝 (포트폴리오용)

기준: 일간 수익률 상관(전체·최근 5년), 반도체 -20% 급락 구간 평균 수익률, 연 배당수익률, 최근 1년 하루 평균 거래대금
시세: yfinance(야후), KRX 요청 없음
실행: python -I screen_lowcorr.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(__file__).resolve().parent
SEMI = {'삼성전자': '005930.KS', 'SK하이닉스': '000660.KS'}
CAND = {
    # 섹터: {종목: 티커}
    '정유': {'S-Oil': '010950.KS', 'SK이노베이션': '096770.KS', 'GS': '078930.KS'},
    '식품': {'CJ제일제당': '097950.KS', '농심': '004370.KS', '오뚜기': '007310.KS', '오리온홀딩스': '001800.KS', '삼양식품': '003230.KS'},
    '통신': {'SK텔레콤': '017670.KS', 'KT': '030200.KS', 'LG유플러스': '032640.KS'},
    '유틸리티': {'한국전력': '015760.KS', '한국가스공사': '036460.KS', '지역난방공사': '071320.KS'},
    '담배': {'KT&G': '033780.KS'},
    '보험': {'삼성화재': '000810.KS', 'DB손해보험': '005830.KS', '현대해상': '001450.KS', '삼성생명': '032830.KS'},
    '은행지주': {'KB금융': '105560.KS', '신한지주': '055550.KS', '하나금융지주': '086790.KS', '우리금융지주': '316140.KS'},
    '제약': {'유한양행': '000100.KS', '녹십자': '006280.KS', '한미약품': '128940.KS', '종근당': '185750.KS'},
    '화장품': {'아모레퍼시픽': '090430.KS', 'LG생활건강': '051900.KS'},
    '유통': {'이마트': '139480.KS', '롯데쇼핑': '023530.KS', 'BGF리테일': '282330.KS'},
    '건설': {'현대건설': '000720.KS', 'GS건설': '006360.KS', 'DL이앤씨': '375500.KS'},
    '방산': {'한화에어로스페이스': '012450.KS', 'LIG넥스원': '079550.KS', '한국항공우주': '047810.KS'},
    '조선': {'HD한국조선해양': '009540.KS', '삼성중공업': '010140.KS', '한화오션': '042660.KS'},
    '해운': {'HMM': '011200.KS', '팬오션': '028670.KS'},
    '철강': {'POSCO홀딩스': '005490.KS', '현대제철': '004020.KS'},
    '게임·인터넷': {'엔씨소프트': '036570.KS', 'NAVER': '035420.KS', '카카오': '035720.KS'},
    '엔터': {'하이브': '352820.KS', 'JYP Ent.': '035900.KQ'},
    '자동차': {'현대차': '005380.KS', '기아': '000270.KS'},
}
tick = {**SEMI}
sector_of = {}
for sec, d in CAND.items():
    for n, t in d.items():
        tick[n] = t
        sector_of[n] = sec

raw = yf.download(list(tick.values()), start='2007-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
inv = {v: k for k, v in tick.items()}
close = raw['Close'].rename(columns=inv)
volu = raw['Volume'].rename(columns=inv)
divs = raw['Dividends'].rename(columns=inv).fillna(0)
ret = close.pct_change(fill_method=None)
semi_r = ret[list(SEMI)].mean(axis=1)
semi_w = (1 + semi_r.fillna(0)).cumprod()

dd = semi_w / semi_w.cummax() - 1
eps, inside = [], False
for d in dd.index:
    if not inside and dd[d] <= -0.20:
        inside, start = True, semi_w.loc[:d].idxmax()
    if inside and dd[d] == 0:
        eps.append((start, d))
        inside = False
if inside:
    eps.append((start, dd.index[-1]))
# 고점 → 반도체 저점 구간(반도체가 빠지는 동안)으로 바꿈
eps = [(s, (semi_w.loc[s:e] / semi_w.loc[s]).idxmin()) for s, e in eps]


def ep_ret(series_r, s, e):
    x = series_r.loc[s:e].dropna()
    if len(x) < 0.8 * len(semi_r.loc[s:e]):
        return np.nan
    return (1 + x).prod() - 1


rows = []
last5 = semi_r.index >= pd.Timestamp('2021-11-01')
for n in tick:
    if n in SEMI:
        continue
    r = ret[n]
    ok = r.notna()
    if ok.sum() < 500:
        continue
    eps_r = [ep_ret(r, s, e) for s, e in eps]
    semi_eps = [ep_ret(semi_r, s, e) for s, e in eps]
    diff = [a - b for a, b in zip(eps_r, semi_eps) if not np.isnan(a)]
    yrs = ok.sum() / 252
    dy = (divs[n] / close[n].shift(1)).loc[ok].sum() / yrs
    tv = (close[n] * volu[n]).loc['2025-11-01':].mean() / 1e8
    rows.append({'섹터': sector_of[n], '종목': n, '데이터시작': r.first_valid_index().date(),
                 '상관_전체': r.corr(semi_r), '상관_최근5년': r[last5].corr(semi_r[last5]),
                 f'급락{len(eps)}번_평균수익%': np.nanmean(eps_r) * 100,
                 '급락때_반도체대비_평균%p': np.mean(diff) * 100 if diff else np.nan,
                 '급락_플러스횟수': int(np.nansum([x > 0 for x in eps_r])), '급락_구간수': int(np.sum(~np.isnan(eps_r))),
                 '연배당%': dy * 100, '최근1년_일평균거래대금_억': tv})
tab = pd.DataFrame(rows).round(2)
sec = tab.groupby('섹터')[['상관_전체', '상관_최근5년', f'급락{len(eps)}번_평균수익%', '급락때_반도체대비_평균%p', '연배당%', '최근1년_일평균거래대금_억']].mean().round(2)
sec = sec.sort_values('급락때_반도체대비_평균%p', ascending=False)
tab.sort_values('급락때_반도체대비_평균%p', ascending=False).to_csv(OUT / '저상관후보_종목별.csv', index=False, encoding='utf-8-sig')
sec.to_csv(OUT / '저상관후보_섹터별.csv', encoding='utf-8-sig')
print(f'반도체 -20% 급락 구간 {len(eps)}개:', [(f'{s:%Y-%m}', f'{e:%Y-%m}') for s, e in eps])
print('\n[섹터별 평균] (급락 때 반도체보다 덜 빠진 순)')
print(sec.to_string())
print('\n[종목별]')
print(tab.sort_values('급락때_반도체대비_평균%p', ascending=False).to_string(index=False))
