"""반도체 70 + 저베타 고배당 30, 월물 콜 50%, 목표 15%: 언제 시작해도 원금이 지켜졌나 (포트폴리오용)

- 연도별 총수익과 원금(NAV) 변화: 15% 분배를 못 벌어 원금이 줄어든 해
- 매월 시작점별 3년·5년 보유 시 원금 변화: 가장 나쁜 시작점, 원금이 줄어든 비율
multi_base_cc.py의 데이터·run()을 그대로 사용. 시세 yfinance, KRX 요청 없음. 비용·세금 미반영
실행: python -I check_70_30_target15.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'multi_base_cc.py').read_text(encoding='utf-8').split('rows = []\nfor base in BASES:')[0]
g = {'__file__': str(HERE / 'multi_base_cc.py'), '__name__': 'mbcc'}
exec(compile(src, 'multi_base_cc.py', 'exec'), g)
pd, np, run, OUT = g['pd'], g['np'], g['run'], g['OUT']

import sys
TGT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.15
WL = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
o = run('반도체', w_low=WL, k=0.5, tenor='M', target=TGT)
semi = run('반도체', k=0.0, target=0.0)['wealth']
nav, w = o['nav'], o['wealth']

# 연도별
yr = pd.DataFrame({
    '총수익%': w.groupby(w.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1) * 100,
    '원금변화%': nav.groupby(nav.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1) * 100,
    '반도체단독%': semi.groupby(semi.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1) * 100,
}).round(1)
yr['원금줄어듦'] = np.where(yr['원금변화%'] < 0, '✗', '')

# 시작점별 3년·5년
m_nav = nav.groupby(nav.index.to_period('M')).first()
roll = {}
for yrs in (3, 5):
    ch = (m_nav.shift(-12 * yrs) / m_nav - 1).dropna() * 100
    roll[yrs] = ch
summ = pd.DataFrame({f'{y}년 보유': {'시작점 수': len(c), '원금 줄어든 비율%': round((c < 0).mean() * 100, 1),
                                    '가장 나쁜 원금변화%': round(c.min(), 1), '가장 나쁜 시작': str(c.idxmin()),
                                    '중앙값%': round(c.median(), 1)} for y, c in roll.items()})

# 원금 최저점과 회복
dd_nav = nav / nav.cummax() - 1
trough = dd_nav.idxmin()
peak = nav.loc[:trough].idxmax()
rec = nav.loc[trough:][nav.loc[trough:] >= nav.loc[peak]]
yr.to_csv(OUT / f'{int(100-WL*100)}_{int(WL*100)}_목표{int(TGT*100)}_연도별.csv', encoding='utf-8-sig')
pd.set_option('display.width', 200)
print('[연도별]  (원금변화 = 15% 분배 후 NAV 변화)')
print(yr.to_string())
print(f"\n원금이 줄어든 해: {(yr['원금변화%'] < 0).sum()}개 / {len(yr)}개")
print('\n[시작 시점별]')
print(summ.to_string())
print(f'\n원금 최대 하락: {peak:%Y-%m} → {trough:%Y-%m} {dd_nav.min()*100:.1f}%, 회복 {rec.index[0]:%Y-%m}' if len(rec) else f'\n원금 최대 하락 {dd_nav.min()*100:.1f}%, 미회복')

