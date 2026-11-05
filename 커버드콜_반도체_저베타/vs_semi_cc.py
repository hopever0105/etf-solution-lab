"""기존 반도체 커버드콜 구조를 2007~2026에 재현해 같은 급락 구간에서 내 안과 비교 (포트폴리오용, 실매매 없음)

반도체 구성은 모두 같게: 삼성전자 25 · SK하이닉스 25 · 한미반도체 20 비율
- 내 안      : 반도체 70 + 저베타 고배당 7종목 30, 코스피 지수(^KS11) 월물 콜을 반도체 부분 50% 매도, 연 10% 분배
- KODEX형    : 반도체 100, 코스피 지수 위클리 콜 30% 매도, 연 9% 분배 (기사: '연 9% 목표, 약 30% 코스피200 콜')
- TIGER형    : 반도체 100, 반도체 바구니 자체 콜(개별주식 옵션 근사) 월물 50% 매도, 연 10% 분배 (매도 비중·분배율은 가정)
- 단순 전량형: 반도체 100, 반도체 자체 콜 월물 100% 매도, 연 15% 분배
- 반도체 단독(분배 없음)
비용: 총보수 0.5% + 옵션 프리미엄 10% 감소, 세금 미반영. 시세 yfinance, KRX 요청 없음
급락 구간: 반도체 바구니가 고점 대비 -20% 이상 빠진 구간(고점→저점)
실행: python -I vs_semi_cc.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'combos.py').read_text(encoding='utf-8').split('rows = []\nfor bname, bw in BASES.items():')[0]
g = {'__file__': str(HERE / 'combos.py'), '__name__': 'combos'}
exec(compile(src, 'combos.py', 'exec'), g)
pd, np, yf, run, summ, BASES, LOWS, OUT, bsk = g['pd'], g['np'], g['yf'], g['run'], g['summ'], g['BASES'], g['LOWS'], g['OUT'], g['bsk']

ks = yf.download('^KS11', start='2006-06-01', end='2026-10-31', auto_adjust=False, progress=False)['Close']
ks = ks.iloc[:, 0] if isinstance(ks, pd.DataFrame) else ks
g['kc'] = ks.reindex(g['close'].index).ffill()

semi = {'삼성전자': 25, 'SK하이닉스': 25, '한미반도체': 20}
l7 = LOWS['7: KT·KT&G·DB손보·SKT·삼성화재·현대해상·LGU+']
s_pr, _ = bsk(semi)
semi_px = (1 + s_pr.fillna(0)).cumprod()  # 반도체 바구니 가격지수 = 자체 콜 기초
C = dict(fee=0.005, haircut=0.10)
cases = {
    '내 안 (반도체70+저베타30, 코스피 월물 콜50%, 10%)': dict(bw=semi, lw=l7, w_low=0.3, target=0.10),
    'KODEX형 (반도체100, 코스피 위클리 콜30%, 9%)': dict(bw=semi, lw=None, w_low=0.0, target=0.09, k=0.3, tenor='W'),
    'TIGER형 (반도체100, 자체 콜 월물50%, 10%)': dict(bw=semi, lw=None, w_low=0.0, target=0.10, k=0.5, cser=semi_px),
    '단순 전량형 (반도체100, 자체 콜 월물100%, 15%)': dict(bw=semi, lw=None, w_low=0.0, target=0.15, k=1.0, cser=semi_px),
}
res = {lab: run(**kw, **C) for lab, kw in cases.items()}
alone = run(semi, None, 0.0, 0.0, k=0.0)
start = max(o.index[0] for o in res.values())

rows = []
for lab, o in list(res.items()) + [('반도체 단독 (분배 없음)', alone)]:
    o = o.loc[start:].copy()
    o['wealth'] = o['wealth'] / o['wealth'].iloc[0]
    s = summ(o)
    s['안'] = lab
    rows.append(s)
tab = pd.DataFrame(rows)[['안', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%', '원금최대하락%', '원금줄어든해',
                          '5년보유_원금감소%', '5년보유_최악%']].round(1)

# 급락 구간별 총수익 낙폭
aw = alone['wealth'].loc[start:]
dd = aw / aw.cummax() - 1
eps, inside = [], False
for d in dd.index:
    if not inside and dd[d] <= -0.20:
        inside, s0 = True, aw.loc[:d].idxmax()
    if inside and dd[d] == 0:
        eps.append((s0, d))
        inside = False
if inside:
    eps.append((s0, dd.index[-1]))
eps = [(s0, (aw.loc[s0:e] / aw.loc[s0]).idxmin()) for s0, e in eps]
erow = []
for s0, e in eps:
    r = {'급락 구간': f'{s0:%Y-%m}~{e:%Y-%m}'}
    for lab, o in list(res.items()) + [('반도체 단독', alone)]:
        w = o['wealth'].loc[s0:e]
        r[lab.split(' (')[0]] = (w / w.cummax() - 1).min() * 100
    erow.append(r)
etab = pd.DataFrame(erow).round(1)
ewin = etab.copy()
mine = etab.columns[1]
others = [c for c in etab.columns[2:]]
wins = {c: int((etab[mine] > etab[c]).sum()) for c in others}

tab.to_csv(OUT / '반도체CC_재현비교_요약.csv', index=False, encoding='utf-8-sig')
etab.to_csv(OUT / '반도체CC_재현비교_급락구간.csv', index=False, encoding='utf-8-sig')
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 60)
print(f'기간 {start:%Y-%m}~2026-10, 비용 반영(보수 0.5%·프리미엄 -10%), 세금 미반영')
print(tab.to_string(index=False))
print(f'\n[반도체 -20% 급락 {len(eps)}번, 각 구간 최대 낙폭 %]')
print(etab.to_string(index=False))
print('\n내 안이 덜 빠진 횟수:', wins)
