"""반도체 + 저베타 고배당 커버드콜: 저베타 비중(0~80%)과 기간(반도체 급등 전후)에 따라 연 15% 분배가 버티는지 (포트폴리오용)

multi_base_cc.py의 데이터·run()·metrics()를 그대로 쓴다(탐색 부분 앞까지만 실행).
구조: 월물 코스피200 콜을 반도체 부분의 50%만큼 매도, 매월 NAV의 1.25%(연 15%) 고정 분배
기간: 전체 2009-05~2026-10 / 반도체 급등 전 2009-05~2023-12 / 최근 5년 2021-11~2026-10
시세: yfinance(야후), KRX 요청 없음. 비용·세금 미반영
실행: python -I sweep_lowbeta_weight.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'multi_base_cc.py').read_text(encoding='utf-8').split('rows = []\nfor base in BASES:')[0]
g = {'__file__': str(HERE / 'multi_base_cc.py'), '__name__': 'mbcc'}
exec(compile(src, 'multi_base_cc.py', 'exec'), g)
pd, run, metrics, OUT = g['pd'], g['run'], g['metrics'], g['OUT']

PERIODS = {'전체': (None, None), '급등전(~2023)': (None, '2023-12-31'), '최근5년': ('2021-11-01', None)}
rows = []
for pname, (s, e) in PERIODS.items():
    for w in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8):
        for tgt in (0.12, 0.15):
            o = run('반도체', w_low=w, k=0.5, tenor='M', target=tgt, start=s)
            if e:
                o = o.loc[:e]
            m = metrics(o, f'저베타{int(w*100)}% · 목표{int(tgt*100)}%')
            m['기간구분'] = pname
            rows.append(m)
    o = run('반도체', w_low=1.0, k=0.0, target=0.0, start=s)  # 저베타 고배당만(콜·분배 없음) 참고
    if e:
        o = o.loc[:e]
    m = metrics(o, '참고: 저베타고배당 100%, 콜·분배 없음')
    m['기간구분'] = pname
    rows.append(m)
tab = pd.DataFrame(rows).round(2)
cols = ['기간구분', '안', '기간', '연총수익%', 'NAV연변화%', '최대낙폭%', 'NAV최저(시작=100)', '연분배%', '연프리미엄%']
tab = tab[cols]
tab.to_csv(OUT / '저베타비중_스윕.csv', index=False, encoding='utf-8-sig')
pd.set_option('display.width', 250)
for pname in PERIODS:
    print(f'\n[{pname}]')
    print(tab[tab['기간구분'] == pname].drop(columns='기간구분').to_string(index=False))
