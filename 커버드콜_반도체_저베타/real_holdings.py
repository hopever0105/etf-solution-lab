"""실제 반도체 커버드콜이 담는 반도체 그대로 70% + 저베타 고배당 30%로 바꾸면? + 분배 재원(콜 프리미엄·배당) 분해 (포트폴리오용, 실매매 없음)

실제 상품의 반도체 부분은 그 기초지수를 추종하는 ETF 가격으로 대신한다
- KODEX 반도체타겟위클리커버드콜 → 기초 KRX 반도체 TR(37종목, 하닉 28.3·삼전 22.2, 4/20 기준) ≈ KODEX 반도체(091160)
- TIGER 반도체TOP10커버드콜액티브 → TIGER 반도체TOP10(396500)과 같은 종목(하닉 28·삼전 24, 4/21 기준), 2021-08~
- FOCUS AI반도체위클리고정커버드콜 → AI반도체 상위 20종목 70% + 코스피200 위클리 콜 30%(구성 비공개 → KODEX 반도체로 근사)
비교: 상품 구조 재현(반도체 100 + 그 상품의 콜 방식) vs 같은 반도체 70 + 저베타 고배당 7종목 30 + 코스피 월물 콜 50%, 연 10% 분배
콜 기초: 코스피 지수(^KS11). 비용: 총보수 0.5% + 옵션 프리미엄 10% 감소. 세금 미반영. 시세 yfinance, KRX 요청 없음
실행: python -I real_holdings.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'combos.py').read_text(encoding='utf-8').split('rows = []\nfor bname, bw in BASES.items():')[0]
g = {'__file__': str(HERE / 'combos.py'), '__name__': 'combos'}
exec(compile(src, 'combos.py', 'exec'), g)
pd, np, yf, run, summ, LOWS, OUT = g['pd'], g['np'], g['yf'], g['run'], g['summ'], g['LOWS'], g['OUT']

ks = yf.download('^KS11', start='2006-06-01', end='2026-10-31', auto_adjust=False, progress=False)['Close']
ks = ks.iloc[:, 0] if isinstance(ks, pd.DataFrame) else ks
g['kc'] = ks.reindex(g['close'].index).ffill()
for name, t in {'KODEX 반도체': '091160.KS', 'TIGER 반도체TOP10': '396500.KS'}.items():
    d = yf.download(t, start='2006-01-01', end='2026-10-31', auto_adjust=False, actions=True, progress=False)
    c = d['Close'].iloc[:, 0] if isinstance(d['Close'], pd.DataFrame) else d['Close']
    dv = d['Dividends'].iloc[:, 0] if isinstance(d['Dividends'], pd.DataFrame) else d['Dividends']
    c = c.reindex(g['close'].index)
    g['close'][name] = c
    g['pr_all'][name] = c.pct_change(fill_method=None)
    g['dy_all'][name] = (dv.reindex(g['close'].index).fillna(0) / c.shift(1)).fillna(0)

l7 = LOWS['7: KT·KT&G·DB손보·SKT·삼성화재·현대해상·LGU+']
C = dict(fee=0.005, haircut=0.10)
pairs = [
    ('KODEX 반도체타겟위클리CC (KRX 반도체)', {'KODEX 반도체': 1}, dict(k=0.3, tenor='W', target=0.09)),
    ('FOCUS AI반도체위클리고정CC (근사: 반도체 70 + 콜 30)', {'KODEX 반도체': 1}, dict(k=0.3 / 0.7, tenor='W', target=0.09)),
    ('TIGER 반도체TOP10CC (TOP10, 2021~)', {'TIGER 반도체TOP10': 1}, dict(k=0.5, tenor='M', target=0.10)),
]
rows, decomp = [], []
for lab, base, kw in pairs:
    prod = run(base, None, 0.0, **kw, **C)
    mine = run(base, l7, 0.3, 0.10, **C)
    st = max(prod.index[0], mine.index[0])
    for who, o in (('상품 구조 재현', prod), ('같은 반도체 70 + 저베타 30 (내 방식)', mine)):
        o = o.loc[st:].copy()
        o['wealth'] = o['wealth'] / o['wealth'].iloc[0]
        s = summ(o)
        # 2026 여름 급락, 2008 금융위기 구간 낙폭
        for wl, (a, b) in {'2008낙폭%': ('2007-10-01', '2009-03-31'), '2022낙폭%': ('2021-06-01', '2022-12-31'), '2026여름낙폭%': ('2026-06-01', '2026-08-31')}.items():
            x = o['wealth'].loc[a:b]
            s[wl] = (x / x.cummax() - 1).min() * 100 if len(x) > 20 else np.nan
        s.update({'상품': lab, '안': who})
        rows.append(s)
        yrs = (o.index[-1] - o.index[0]).days / 365.25
        m = o[['prem', 'div', 'dist']].groupby(o.index.to_period('M')).sum()
        mnav = o['nav'].groupby(o.index.to_period('M')).first()
        m = m.div(mnav, axis=0) * 100
        short = (m['dist'] - m['prem'] - m['div']).clip(lower=0)
        decomp.append({'상품': lab, '안': who, '연 콜 프리미엄%(비용 후)': m['prem'].sum() / yrs, '연 배당%': m['div'].sum() / yrs,
                       '연 분배%': m['dist'].sum() / yrs, '모자라서 원금에서 낸 몫%(연)': short.sum() / yrs,
                       '모자란 달 비율%': (short > 0).mean() * 100})
tab = pd.DataFrame(rows)[['상품', '안', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%', '원금최대하락%', '5년보유_원금감소%',
                          '5년보유_최악%', '2008낙폭%', '2022낙폭%', '2026여름낙폭%']].round(1)
dtab = pd.DataFrame(decomp).round(2)
tab.to_csv(OUT / '실제구성_재현비교.csv', index=False, encoding='utf-8-sig')
dtab.to_csv(OUT / '분배재원_분해.csv', index=False, encoding='utf-8-sig')

# 한 달 콜 프리미엄 예시(최근 12개월 평균): 내 방식, KODEX 반도체 기초
o = run({'KODEX 반도체': 1}, l7, 0.3, 0.10, **C)
last = o.loc['2025-11-01':]
mp = last['prem'][last['prem'] > 0] / last['nav'].shift(1)[last['prem'] > 0] * 100
pd.set_option('display.width', 320)
pd.set_option('display.max_colwidth', 50)
print(tab.to_string(index=False))
print('\n[분배 재원 분해 (연, NAV 대비)]')
print(dtab.to_string(index=False))
print(f'\n최근 12개월 월 콜 프리미엄(NAV 대비, 비용 후): 평균 {mp.mean():.2f}%, 최소 {mp.min():.2f}%, 최대 {mp.max():.2f}%  → 100억이면 월 평균 {mp.mean():.2f}억')
