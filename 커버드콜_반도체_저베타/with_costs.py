"""비용 반영 재계산: 총보수 연 0.5%(매일 차감) + 옵션 호가 차이로 프리미엄 10% 감소. 세금은 미반영(투자자 계좌별로 다름)
대상: 내 안(반도체3a + 저베타7, 10%·12%), 반도체7 + 저베타3, 기존형 재현(반도체 위클리 CC·코스피200 타겟위클리형은 value_vs_market.py 구조와 같은 가정으로 비용 동일 적용)
combos.py의 데이터·run()·summ()을 그대로 사용. 시세 yfinance, KRX 요청 없음
실행: python -I with_costs.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'combos.py').read_text(encoding='utf-8').split('rows = []\nfor bname, bw in BASES.items():')[0]
g = {'__file__': str(HERE / 'combos.py'), '__name__': 'combos'}
exec(compile(src, 'combos.py', 'exec'), g)
pd, run, summ, BASES, LOWS, OUT = g['pd'], g['run'], g['summ'], g['BASES'], g['LOWS'], g['OUT']

b3a = BASES['반도체3a (삼전25·하닉25·한미20)']
b7 = BASES['반도체7 (삼전25·하닉25·한미6·리노4·DB하이텍4·이오3·원익3)']
b2 = BASES['반도체2 (삼전35·하닉35)']
l7 = LOWS['7: KT·KT&G·DB손보·SKT·삼성화재·현대해상·LGU+']
l3 = LOWS['3: KT·KT&G·DB손보']
cases = [
    ('내 안: 반도체3a + 저베타7, 10%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.10)),
    ('내 안: 반도체3a + 저베타7, 12%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.12)),
    ('반도체7 + 저베타3, 10%', dict(bw=b7, lw=l3, w_low=0.3, target=0.10)),
    ('반도체2(삼전·하닉만) + 저베타3, 10% (한미 없이)', dict(bw=b2, lw=l3, w_low=0.3, target=0.10)),
]
rows = []
for lab, kw in cases:
    for cost_lab, fee, hc in (('비용 없음', 0.0, 0.0), ('보수 0.5% + 프리미엄 -10%', 0.005, 0.10)):
        s = summ(run(**kw, fee=fee, haircut=hc))
        s.update({'안': lab, '비용': cost_lab})
        rows.append(s)
tab = pd.DataFrame(rows)[['안', '비용', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%', '원금최대하락%', '원금줄어든해',
                          '5년보유_원금감소%', '5년보유_최악%', '급등전_원금연변화%']].round(2)
tab.to_csv(OUT / '비용반영.csv', index=False, encoding='utf-8-sig')
pd.set_option('display.width', 300)
print(tab.to_string(index=False))
