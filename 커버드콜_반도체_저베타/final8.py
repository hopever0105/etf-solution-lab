"""최종안(연 8% 월분배, 반기마다 그 시점 정보로 저베타 고배당 재선정) 상세 검증 (포트폴리오용, 실매매 없음)

1. 측정 기준 정의별 원금 손실: 달력 연도(1월 첫 거래일 → 12월 마지막 거래일), 아무 달에 사서 1·3·5년 보유
2. 적립식: 매달 첫 거래일 같은 금액을 60개월 매수 → 60개월 뒤 평가(시작 달을 한 달씩 옮겨 전부 계산)
3. 거치식 1억 원의 월 분배금(원) 변화
4. 최근 3년(2024·2025·2026) 기존 반도체 커버드콜 구조 재현·실제 상품과 비교
5. 연말 특별분배(그해 잉여를 12월에 추가 분배) vs 재투자(몸집 키우기)
기준: pit_select.py run(freq='H', cap=0.5, mode='strict', tgt=0.08), 콜 기초 ^KS11, 총보수 0.5% + 옵션 비용, 세금 미반영
시세: yfinance(야후), KRX 요청 없음
실행: python -I final8.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / 'pit_select.py').read_text(encoding='utf-8-sig').split('cases = [')[0]
g = {'__file__': str(HERE / 'pit_select.py'), '__name__': 'pit'}
exec(compile(src, 'pit_select.py', 'exec'), g)
pd, np, yf, OUT = g['pd'], g['np'], g['yf'], g['OUT']
run = g['run']

# 기존 구조 재현용(combos.py) 네임스페이스
src2 = (HERE / 'combos.py').read_text(encoding='utf-8-sig').split('rows = []\nfor bname, bw in BASES.items():')[0]
c = {'__file__': str(HERE / 'combos.py'), '__name__': 'combos'}
exec(compile(src2, 'combos.py', 'exec'), c)
ks = g['ks']
c['kc'] = ks.reindex(c['close'].index).ffill()

o8, h8 = run(freq='H', cap=0.5, mode='strict', start='2007-02-01', tgt=0.08)
o8b, _ = run(freq='H', cap=0.5, mode='strict', start='2007-02-01', tgt=0.08, bonus=True)
nav, dist, w = o8['nav'], o8['dist'], o8['wealth']

# ---------------------------------------------------------------- 1. 달력 연도
yr = []
for y, x in o8.groupby(o8.index.year):
    a, b = x.index[0], x.index[-1]
    yr.append({'연도': y, '시작일': f'{a:%m-%d}', '끝일': f'{b:%m-%d}', '원금(기준가) 변화%': (x['nav'].iloc[-1] / x['nav'].iloc[0] - 1) * 100,
               '그해 받은 분배%': x['dist'].sum() / x['nav'].iloc[0] * 100, '총수익%': (x['wealth'].iloc[-1] / x['wealth'].iloc[0] - 1) * 100})
yr = pd.DataFrame(yr).round(1)
yr['원금 손실'] = np.where(yr['원금(기준가) 변화%'] < 0, '✗', '')
yr['총수익도 손실'] = np.where(yr['총수익%'] < 0, '✗', '')

# 거치식 보유 기간별
m_nav = nav.groupby(nav.index.to_period('M')).first()
m_w = w.groupby(w.index.to_period('M')).first()
hold = []
for yrs in (1, 3, 5):
    ch = (m_nav.shift(-12 * yrs) / m_nav - 1).dropna() * 100
    tr = (m_w.shift(-12 * yrs) / m_w - 1).dropna() * 100
    hold.append({'보유 기간': f'{yrs}년', '시작 시점 수': len(ch), '원금(기준가) 손실 확률%': (ch < 0).mean() * 100, '원금 최악%': ch.min(),
                 '최악 시작': str(ch.idxmin()), '분배 포함해도 손실 확률%': (tr < 0).mean() * 100, '분배 포함 최악%': tr.min(), '중앙값 원금%': ch.median()})
hold = pd.DataFrame(hold).round(1)

# ---------------------------------------------------------------- 2. 적립식 60개월
mfirst = pd.Series(o8.index, index=o8.index).groupby(o8.index.to_period('M')).first()
mlast_set = set(pd.Series(o8.index, index=o8.index).groupby(o8.index.to_period('M')).last())
units_dist = o8['dist']  # 1좌당 분배(기준가 단위)
dca = []
months = list(mfirst.index)
for k in range(len(months) - 60):
    buys = [mfirst[months[k + j]] for j in range(60)]
    end = mfirst[months[k + 60]]
    units, cash = 0.0, 0.0
    bset = set(buys)
    for d in o8.loc[buys[0]:end].index:
        if d in bset:
            units += 1.0 / nav[d]
        if d in mlast_set and d < end:
            cash += units * dist[d]
    val = units * nav[end]
    dca.append({'시작': str(months[k]), '낸 돈': 60, '5년 뒤 평가액': val, '받은 분배 합': cash})
dca = pd.DataFrame(dca)
dca['원금 대비 평가액%'] = (dca['5년 뒤 평가액'] / 60 - 1) * 100
dca['원금 대비 평가액+분배%'] = ((dca['5년 뒤 평가액'] + dca['받은 분배 합']) / 60 - 1) * 100
dca_sum = {'시작 시점 수': len(dca), '평가액이 낸 돈보다 적은 비율%': (dca['원금 대비 평가액%'] < 0).mean() * 100,
           '평가액 최악%': dca['원금 대비 평가액%'].min(), '최악 시작': dca.loc[dca['원금 대비 평가액%'].idxmin(), '시작'],
           '평가액+분배가 낸 돈보다 적은 비율%': (dca['원금 대비 평가액+분배%'] < 0).mean() * 100,
           '평가액+분배 최악%': dca['원금 대비 평가액+분배%'].min(), '평가액 중앙값%': dca['원금 대비 평가액%'].median(),
           '분배 합 중앙값(낸 돈 대비%)': (dca['받은 분배 합'] / 60).median() * 100}
# 거치식 비교(같은 시작 달에 60을 한 번에)
lump = (m_nav.shift(-60) / m_nav - 1).dropna() * 100

# ---------------------------------------------------------------- 3. 1억 원 거치 시 월 분배금
units0 = 1e8 / nav.iloc[0]
mdist = (dist[dist > 0] * units0).groupby(dist[dist > 0].index.year).agg(['mean', 'min', 'max']).round(-3)
mdist.columns = ['월 평균(원)', '월 최소(원)', '월 최대(원)']

# ---------------------------------------------------------------- 4. 최근 3년 비교
semi = {'삼성전자': 25, 'SK하이닉스': 25, '한미반도체': 20}
s_pr, _ = c['bsk'](semi)
semi_px = (1 + s_pr.fillna(0)).cumprod()
C = dict(fee=0.005, haircut=0.10)
rep = {'KODEX형 재현(반도체100, 코스피 위클리 콜30%, 9%)': c['run'](semi, None, 0.0, 0.09, k=0.3, tenor='W', **C),
       'TIGER형 재현(반도체100, 자체 콜50%, 10%)': c['run'](semi, None, 0.0, 0.10, k=0.5, cser=semi_px, **C),
       '반도체 단독(분배 없음)': c['run'](semi, None, 0.0, 0.0, k=0.0)}
rec = []
for y in (2024, 2025, 2026):
    r = {'연도': f'{y}' + (' (10/30까지)' if y == 2026 else '')}
    for lab, o in [('내 안 8%', o8)] + list(rep.items()):
        x = o.loc[str(y)]
        r[lab + ' 총수익%'] = (x['wealth'].iloc[-1] / x['wealth'].iloc[0] - 1) * 100
        r[lab + ' 원금%'] = (x['nav'].iloc[-1] / x['nav'].iloc[0] - 1) * 100
        r[lab + ' 연중최대낙폭%'] = (x['wealth'] / x['wealth'].cummax() - 1).min() * 100
    rec.append(r)
rec = pd.DataFrame(rec).round(1)
real = []
for name, t in {'TIGER 반도체TOP10커버드콜액티브': '0177R0.KS', 'KODEX 반도체타겟위클리커버드콜': '0190G0.KS'}.items():
    dd = yf.download(t, start='2026-01-01', end='2026-10-31', auto_adjust=False, progress=False)
    p = (dd['Close'].iloc[:, 0] if isinstance(dd['Close'], pd.DataFrame) else dd['Close']).dropna()
    a = (dd['Adj Close'].iloc[:, 0] if isinstance(dd['Adj Close'], pd.DataFrame) else dd['Adj Close']).dropna()
    s0, e0 = p.index[0], min(p.index[-1], o8.index[-1])
    x = o8.loc[s0:e0]
    real.append({'실제 상품': name, '상장일': f'{s0:%Y-%m-%d}', '상품 기준가%': (p.iloc[-1] / p.iloc[0] - 1) * 100,
                 '상품 분배 포함%': (a.iloc[-1] / a.iloc[0] - 1) * 100, '상품 최대낙폭%': (a / a.cummax() - 1).min() * 100,
                 '내 안 원금%': (x['nav'].iloc[-1] / x['nav'].iloc[0] - 1) * 100,
                 '내 안 분배 포함%': (x['wealth'].iloc[-1] / x['wealth'].iloc[0] - 1) * 100,
                 '내 안 최대낙폭%': (x['wealth'] / x['wealth'].cummax() - 1).min() * 100})
real = pd.DataFrame(real).round(1)

# ---------------------------------------------------------------- 5. 특별분배 vs 재투자
def bsum(o, lab):
    yrs = (o.index[-1] - o.index[0]).days / 365.25
    u = 1e8 / o['nav'].iloc[0]
    m = o['nav'].groupby(o['nav'].index.to_period('M')).first()
    ch5 = (m.shift(-60) / m - 1).dropna() * 100
    yd = o['dist'].groupby(o.index.year).sum() / o['nav'].groupby(o.index.year).first() * 100
    return {'안': lab, '연총수익%': ((o['wealth'].iloc[-1] / o['wealth'].iloc[0]) ** (1 / yrs) - 1) * 100,
            '원금 연변화%': ((o['nav'].iloc[-1] / o['nav'].iloc[0]) ** (1 / yrs) - 1) * 100,
            '연 분배율 평균%': yd.mean(), '연 분배율 최소~최대%': f'{yd.min():.1f}~{yd.max():.1f}',
            '1억 20년 받은 분배 합(억)': o['dist'].sum() * u / 1e8, '1억 20년 뒤 평가액(억)': o['nav'].iloc[-1] * u / 1e8,
            '5년보유 원금감소%': (ch5 < 0).mean() * 100, '마지막 해 월 분배(만원)': o['dist'].loc[str(o.index[-1].year)].replace(0, np.nan).mean() * u / 1e4}
bon = pd.DataFrame([bsum(o8, '8% 고정 + 잉여 재투자(몸집 키우기)'), bsum(o8b, '8% 고정 + 연말 특별분배')]).round(2)

for nm, t in [('1_연도별', yr), ('2_보유기간별', hold), ('3_적립식60개월', dca), ('4_최근3년', rec), ('5_실제상품_올해', real), ('6_특별분배vs재투자', bon)]:
    t.to_csv(OUT / f'최종8_{nm}.csv', index=False, encoding='utf-8-sig')
mdist.to_csv(OUT / '최종8_1억월분배.csv', encoding='utf-8-sig')
# 보고서 그림용 일별 시리즈
daily = pd.DataFrame({'내안_총수익': o8['wealth'], '내안_원금': o8['nav'] / o8['nav'].iloc[0],
                      '특별분배_총수익': o8b['wealth'], '특별분배_원금': o8b['nav'] / o8b['nav'].iloc[0]})
for lab, o in rep.items():
    x = o.loc[o8.index[0]:]
    daily[lab.split('(')[0] + '_총수익'] = x['wealth'] / x['wealth'].iloc[0]
    daily[lab.split('(')[0] + '_원금'] = x['nav'] / x['nav'].iloc[0]
daily.to_csv(OUT / '최종8_일별.csv', encoding='utf-8-sig')
h8.to_csv(OUT / '최종8_반기별선정종목.csv', index=False, encoding='utf-8-sig')

pd.set_option('display.width', 320)
pd.set_option('display.max_columns', 30)
print('[1. 달력 연도 (그해 첫 거래일 → 마지막 거래일)]')
print(yr.to_string(index=False))
print('\n[2. 거치식: 아무 달 첫 거래일에 사서 N년 보유]')
print(hold.to_string(index=False))
print('\n[3. 적립식: 매달 첫 거래일 같은 금액 60개월, 60개월째 평가]')
print(pd.Series({k: (round(v, 1) if isinstance(v, float) else v) for k, v in dca_sum.items()}).to_string())
print(f'(같은 시작 달 거치식 5년: 원금 손실 비율 {(lump < 0).mean()*100:.1f}%, 최악 {lump.min():.1f}%)')
print('\n[4. 1억 원 거치 시 연도별 월 분배금]')
print(mdist.to_string())
print('\n[5. 최근 3년: 같은 반도체(삼전25·하닉25·한미20) 기준 재현]')
print(rec.T.to_string())
print('\n[6. 올해 실제 상품 vs 내 안 (상품 상장일부터)]')
print(real.to_string(index=False))
print('\n[7. 연말 특별분배 vs 재투자]')
print(bon.to_string(index=False))
