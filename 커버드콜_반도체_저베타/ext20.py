"""2008 금융위기 포함 약 20년(2007~2026) 재검증 + 채권 혼합 + 분배율 높이기, 전부 비용 반영 (포트폴리오용, 실매매 없음)

- 콜 기초를 KODEX 200(2009~) 대신 코스피 지수(^KS11)로 바꿔 2007년부터 계산(코스피200과 일간 상관 약 0.99, 배당 없는 지수)
- 채권: KODEX 국고채3년(114260, 2009-07~) 수익률, 그 이전은 연 5% 고정 가정(2007~08 국고채 3년 금리 수준, 확인 필요)
- 비용: 총보수 연 0.5% + 옵션 프리미엄 10% 감소(호가 차이). 세금 미반영
combos.py의 데이터·run()·summ()을 그대로 사용. 시세 yfinance, KRX 요청 없음
실행: python -I ext20.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'combos.py').read_text(encoding='utf-8').split('rows = []\nfor bname, bw in BASES.items():')[0]
g = {'__file__': str(HERE / 'combos.py'), '__name__': 'combos'}
exec(compile(src, 'combos.py', 'exec'), g)
pd, np, yf, run, summ, BASES, LOWS, OUT = g['pd'], g['np'], g['yf'], g['run'], g['summ'], g['BASES'], g['LOWS'], g['OUT']

ks = yf.download('^KS11', start='2006-06-01', end='2026-10-31', auto_adjust=False, progress=False)['Close']
ks = ks.iloc[:, 0] if isinstance(ks, pd.DataFrame) else ks
g['kc'] = ks.reindex(g['close'].index).ffill()
bd = yf.download('114260.KS', start='2009-01-01', end='2026-10-31', auto_adjust=True, progress=False)['Close']
bd = bd.iloc[:, 0] if isinstance(bd, pd.DataFrame) else bd
br = bd.pct_change().reindex(g['close'].index)
early = br.index < bd.dropna().index[0]
br[early] = 0.05 / 252
g['pr_all']['채권'] = br.fillna(0)
g['dy_all']['채권'] = 0.0
g['close']['채권'] = 1.0

b3a = BASES['반도체3a (삼전25·하닉25·한미20)']
b2 = BASES['반도체2 (삼전35·하닉35)']
l7 = LOWS['7: KT·KT&G·DB손보·SKT·삼성화재·현대해상·LGU+']
l3 = LOWS['3: KT·KT&G·DB손보']
C = dict(fee=0.005, haircut=0.10)


def mix(bw, w_semi, lw, w_lowb, w_bond):
    """저베타+채권을 '저베타 묶음'으로 합침: 반환 (기초 비중 dict, 저베타 묶음 dict, 저베타 묶음 전체 비중)"""
    low = {n: w_lowb / len(lw) for n in lw}
    if w_bond:
        low['채권'] = w_bond
    return bw, low, w_lowb + w_bond


cases = [
    ('내 안: 반도체3a 70 + 저베타7 30, 월물 콜50%, 10%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.10)),
    ('분배↑: 같은 구조, 12%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.12)),
    ('분배↑: 같은 구조, 15%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.15)),
    ('분배↑: 월물 콜100%, 12%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.12, k=1.0)),
    ('분배↑: 위클리 콜50%, 12%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.12, tenor='W')),
    ('분배↑: 위클리 콜50%, 15%', dict(bw=b3a, lw=l7, w_low=0.3, target=0.15, tenor='W')),
    ('분배↑: 반도체 80 + 저베타 20, 위클리 콜50%, 12%', dict(bw=b3a, lw=l7, w_low=0.2, target=0.12, tenor='W')),
]
for lab, (wb, wl, wbond, tgt) in {
    '채권30: 반도체 50 + 저베타 20 + 채권 30, 월물 콜50%, 8%': (b3a, 0.2, 0.3, 0.08),
    '채권30: 같은 구조, 10%': (b3a, 0.2, 0.3, 0.10),
    '채권혼합50(퇴직연금 100%): 반도체 35 + 저베타 15 + 채권 50, 월물 콜50%, 6%': (b3a, 0.15, 0.5, 0.06),
    '채권혼합50: 같은 구조, 8%': (b3a, 0.15, 0.5, 0.08),
    '채권혼합50: 반도체 35 + 저베타 15 + 채권 50, 위클리 콜100%, 8%': (b3a, 0.15, 0.5, 0.08),
}.items():
    bw, low, w_low = mix(wb, None, l7, wl, wbond)
    kw = dict(bw=bw, lw=low, w_low=w_low, target=tgt)
    if '위클리 콜100%' in lab:
        kw.update(k=1.0, tenor='W')
    cases.append((lab, kw))
cases.append(('참고: 한미 없이 삼전35·하닉35 + 저베타3, 10%', dict(bw=b2, lw=l3, w_low=0.3, target=0.10)))

# 저베타 묶음에 채권(가중치 dict)이 들어가면 bsk가 dict로 처리
rows = []
for lab, kw in cases:
    lw = kw['lw']
    if isinstance(lw, dict):
        kw = dict(kw)
    s = summ(run(**kw, **C))
    s['안'] = lab
    rows.append(s)
tab = pd.DataFrame(rows)[['안', '기간', '연총수익%', '수익/변동성', '최대낙폭%', '원금연변화%', '원금최대하락%', '원금줄어든해',
                          '5년보유_원금감소%', '5년보유_최악%', '급등전_원금연변화%']].round(2)
tab.to_csv(OUT / '20년_채권_분배율.csv', index=False, encoding='utf-8-sig')

# 2008 금융위기 구간 따로
o = run(**cases[0][1], **C)
w = o['wealth'].loc['2007-10-01':'2009-03-31']
semi = run(b2, None, 0.0, 0.0, k=0.0)['wealth'].loc['2007-10-01':'2009-03-31']
pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 60)
print(f"기간 {o.index[0]:%Y-%m}~{o.index[-1]:%Y-%m}, 콜 기초 ^KS11, 비용 반영(보수 0.5%·프리미엄 -10%), 세금 미반영")
print(tab.to_string(index=False))
print(f"\n2008 금융위기(2007-10~2009-03) 최대 낙폭: 내 안 {(w / w.cummax() - 1).min()*100:.1f}% / 반도체(삼전·하닉) {(semi / semi.cummax() - 1).min()*100:.1f}%")
