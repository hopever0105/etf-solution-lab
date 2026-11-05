"""보고서 그림 6장: final8.py 결과(시점선정/최종8_*.csv)를 읽어 그린다 → 보고서/img/
실행: python -I make_charts.py
"""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent
SRC = HERE / '시점선정'
IMG = HERE / '보고서' / 'img'
IMG.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'font.family': 'Malgun Gothic', 'axes.unicode_minus': False, 'font.size': 9,
                     'axes.edgecolor': '#52514e', 'axes.labelcolor': '#52514e', 'xtick.color': '#52514e', 'ytick.color': '#52514e',
                     'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.color': '#e6e5e1', 'grid.linewidth': 0.6,
                     'figure.facecolor': '#fcfcfb', 'axes.facecolor': '#fcfcfb', 'savefig.facecolor': '#fcfcfb'})
C1, C2, C3, GRAY, INK = '#2a78d6', '#eb6834', '#1baf7a', '#9a9993', '#0b0b0b'
SER = [('내안', '내 안 (8%)', C1), ('KODEX형 재현', 'KODEX형 재현 (9%)', C2), ('TIGER형 재현', 'TIGER형 재현 (10%)', C3),
       ('반도체 단독', '반도체 단독 (분배 없음)', GRAY)]

d = pd.read_csv(SRC / '최종8_일별.csv', index_col=0, parse_dates=True)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=200)
    plt.close(fig)


# 1. 누적 총수익(분배 재투자) — 로그 축
fig, ax = plt.subplots(figsize=(7.2, 3.4))
for key, lab, col in SER:
    s = d[key + '_총수익'].dropna()
    ax.plot(s.index, s, color=col, lw=2 if key == '내안' else 1.4, label=lab)
    dy = {'내안': 5, 'TIGER형 재현': -6}.get(key, 0)
    ax.annotate(f'{s.iloc[-1]:.0f}배', (s.index[-1], s.iloc[-1]), xytext=(4, dy), textcoords='offset points', fontsize=8, color=INK, va='center')
ax.set_yscale('log')
ax.set_ylabel('누적 총수익 (시작 = 1, 로그)')
ax.legend(frameon=False, fontsize=8, loc='upper left')
ax.xaxis.set_major_locator(mdates.YearLocator(3))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
save(fig, 'fig1_누적총수익.png')

# 2. 낙폭
fig, ax = plt.subplots(figsize=(7.2, 3.0))
for key, lab, col in SER:
    s = d[key + '_총수익'].dropna()
    dd = (s / s.cummax() - 1) * 100
    ax.plot(dd.index, dd, color=col, lw=1.6 if key == '내안' else 1.1, label=lab)
ax.set_ylabel('고점 대비 낙폭 (%)')
ax.legend(frameon=False, fontsize=8, loc='lower left', ncol=2)
ax.xaxis.set_major_locator(mdates.YearLocator(3))
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
save(fig, 'fig2_낙폭.png')

# 3. 연도별 원금(기준가) 변화와 받은 분배
yr = pd.read_csv(SRC / '최종8_1_연도별.csv')
fig, ax = plt.subplots(figsize=(7.2, 3.0))
x = range(len(yr))
ax.bar([i - 0.2 for i in x], yr['원금(기준가) 변화%'], width=0.4, color=C1, label='원금(기준가) 변화')
ax.bar([i + 0.2 for i in x], yr['그해 받은 분배%'], width=0.4, color=C2, label='그해 받은 분배')
ax.axhline(0, color='#52514e', lw=0.8)
ax.set_xticks(list(x))
ax.set_xticklabels([str(y)[2:] for y in yr['연도']], fontsize=8)
ax.set_ylabel('% (연초 기준가 대비)')
ax.legend(frameon=False, fontsize=8, loc='upper left')
save(fig, 'fig3_연도별.png')

# 4. 적립식 60개월 결과 분포
dca = pd.read_csv(SRC / '최종8_3_적립식60개월.csv')
fig, ax = plt.subplots(figsize=(7.2, 2.8))
ax.plot(pd.PeriodIndex(dca['시작'], freq='M').to_timestamp(), dca['원금 대비 평가액%'], color=C1, lw=1.8, label='평가액 (분배 제외)')
ax.plot(pd.PeriodIndex(dca['시작'], freq='M').to_timestamp(), dca['원금 대비 평가액+분배%'], color=C2, lw=1.4, label='평가액 + 받은 분배')
ax.axhline(0, color='#52514e', lw=0.8)
ax.set_ylabel('낸 돈 대비 (%)')
ax.set_xlabel('적립 시작 달 (매달 같은 금액, 60개월 뒤 평가)')
ax.legend(frameon=False, fontsize=8, loc='upper left')
save(fig, 'fig4_적립식.png')

# 5. 1억 거치 시 월 평균 분배금
md = pd.read_csv(SRC / '최종8_1억월분배.csv')
fig, ax = plt.subplots(figsize=(7.2, 2.6))
ax.bar(md['Date'].astype(str).str[2:], md['월 평균(원)'] / 1e4, color=C1, width=0.6)
for i, v in enumerate(md['월 평균(원)'] / 1e4):
    if i in (0, 1, len(md) - 3, len(md) - 2):
        ax.annotate(f'{v:.0f}만', (i, v), xytext=(0, 2), textcoords='offset points', ha='center', fontsize=7.5, color=INK)
ax.set_ylabel('월 평균 분배금 (만 원)')
ax.set_xlabel('2007년 초 1억 원 거치, 분배율 8% 고정 (2026년은 10월까지)')
save(fig, 'fig5_월분배금.png')

# 6. 분배율별 5년 보유 원금 감소 확률
t = pd.read_csv(SRC / '시점선정_분배율별.csv')
fig, ax = plt.subplots(figsize=(4.6, 2.6))
ax.bar(t['분배'], t['5년보유_원금감소%'], color=[C1 if s == '8%' else '#86b6ef' for s in t['분배']], width=0.55)
for i, v in enumerate(t['5년보유_원금감소%']):
    ax.annotate(f'{v:.1f}%', (i, v), xytext=(0, 2), textcoords='offset points', ha='center', fontsize=8, color=INK)
ax.set_ylabel('5년 보유 시 원금 감소 확률 (%)')
ax.set_xlabel('연 분배율')
save(fig, 'fig6_분배율.png')
print('그림 저장:', sorted(p.name for p in IMG.glob('*.png')))
