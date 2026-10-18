# -*- coding: utf-8 -*-
"""
ETF 겹침 지도 + 종목 편입 빈도 분석  (엑셀만 사용, 인터넷 불필요)
입력 : 송호빈_ETF_유니버스.xlsx 의 '2. ETF별 구성종목' 시트
출력 : etf_out 폴더 (표 CSV 3개 + 그림 PNG 3개)
기준 : ETF마다 공개된 상위 3~10개 종목 '집합'의 겹침 (비중이 없으므로 비중 유사도가 아님)
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# =========================== [설정] ===========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE_DIR, '송호빈_ETF_유니버스.xlsx')
SHEET = '2. ETF별 구성종목'
OUT_DIR = os.path.join(BASE_DIR, 'etf_out')

MIN_N = 5            # 공개 종목이 이 개수 미만인 ETF는 쌍 비교에서 제외 (표본이 너무 적어 Jaccard가 불안정)
HIGH = 0.50          # Jaccard >= 0.50 : 사실상 중복   (결과를 보기 전에 정한 기준. 결과에 맞춰 바꾸지 않는다)
MID = 0.20           # 0.20 <= Jaccard < 0.50 : 부분 중복,  Jaccard < 0.20 : 분산
SAME_COMPANY = {'GOOG': 'GOOGL'}   # 같은 회사의 복수 티커(보통주/클래스) 통일
SKIP_NAMES = ('미기재', '균등배분')  # 구성종목이 실제로 적혀 있지 않은 행
# ==============================================================

plt.rcParams['font.family'] = ['Malgun Gothic', 'AppleGothic', 'NanumGothic',
                               'Noto Sans CJK KR', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
os.makedirs(OUT_DIR, exist_ok=True)


def norm_ticker(v):
    """엑셀에서 앞자리 0이 잘린 한국 종목코드(86520 -> 086520)를 바로잡고, 복수 티커를 통일."""
    if pd.isna(v):
        return np.nan
    s = str(v).strip().upper()
    if s.isdigit():
        s = s.zfill(6)
    return SAME_COMPANY.get(s, s)


# ---------- 1) 불러오기 + 정리 ----------
raw = pd.read_excel(XLSX, sheet_name=SHEET, dtype=str)
raw['티커정리'] = raw['티커/코드'].map(norm_ticker)
fixed = (raw['티커/코드'].notna() & (raw['티커/코드'].str.strip() != raw['티커정리'])).sum()
print(f'[정리] 앞자리 0 복원·복수 티커 통일로 바뀐 행: {fixed}개 (엑셀 티커 열을 "텍스트" 서식으로 바꾸면 원천 해결)')

skip = raw['종목명'].astype(str).apply(lambda x: any(k in x for k in SKIP_NAMES))
print(f'[정리] 종목이 적혀 있지 않은 행 제외: {int(skip.sum())}개')
c = raw[~skip].copy()
c['key'] = c['티커정리'].fillna(c['종목명'])        # 티커가 없으면 종목명으로 대신
c = c.drop_duplicates(['ETF명', 'key'])

meta = c.drop_duplicates('ETF명').set_index('ETF명')[['대분류', '섹터']]
sets = c.groupby('ETF명')['key'].apply(set)
n_all = len(sets)
sets = sets[sets.map(len) >= MIN_N]
print(f'[대상] ETF {n_all}개 중 공개 종목 {MIN_N}개 이상 {len(sets)}개로 쌍 비교 (나머지 {n_all - len(sets)}개는 표본 부족으로 제외)')

names = sorted(sets.index, key=lambda n: (meta.loc[n, '대분류'], meta.loc[n, '섹터'], n))

# ---------- 2) 쌍별 겹침 ----------
rows = []
M = pd.DataFrame(0.0, index=names, columns=names)
for i, a in enumerate(names):
    M.loc[a, a] = 1.0
    for b in names[i + 1:]:
        sa, sb = sets[a], sets[b]
        inter = len(sa & sb)
        jac = inter / len(sa | sb)
        M.loc[a, b] = M.loc[b, a] = jac
        rows.append({
            'ETF_A': a, 'ETF_B': b,
            '섹터_A': meta.loc[a, '섹터'], '섹터_B': meta.loc[b, '섹터'],
            '같은섹터': meta.loc[a, '섹터'] == meta.loc[b, '섹터'],
            '공개종목수_A': len(sa), '공개종목수_B': len(sb), '겹친종목수': inter,
            'Jaccard': jac, '포함도': inter / min(len(sa), len(sb)),
            '겹친종목': ', '.join(sorted(c[(c['key'].isin(sa & sb)) & (c['ETF명'] == a)]['종목명'])),
        })
P = pd.DataFrame(rows)
P['분류'] = np.where(P['Jaccard'] >= HIGH, '사실상 중복',
                   np.where(P['Jaccard'] >= MID, '부분 중복', '분산'))
P.sort_values('Jaccard', ascending=False).to_csv(
    os.path.join(OUT_DIR, 'etf_pair_overlap.csv'), index=False, encoding='utf-8-sig')

tot = len(P)
print(f'\n[쌍 비교] 전체 {tot}쌍')
print(P['분류'].value_counts().to_string())
print(f'겹침이 전혀 없는 쌍(Jaccard=0): {(P["Jaccard"] == 0).sum()}쌍 ({(P["Jaccard"] == 0).mean() * 100:.1f}%)')

pd.set_option('display.width', 220)
pd.set_option('display.max_colwidth', 30)
show = ['ETF_A', 'ETF_B', '섹터_A', '섹터_B', '겹친종목수', 'Jaccard']
print('\n[분산처럼 보이지만 겹치는 쌍] 섹터가 다른데 Jaccard >= %.2f' % HIGH)
x = P[(~P['같은섹터']) & (P['Jaccard'] >= HIGH)].sort_values('Jaccard', ascending=False)
print(x[show].round(2).to_string(index=False) if len(x) else '없음')

print('\n[같은 섹터인데 겹침이 거의 없는 쌍 = 같은 테마 안의 진짜 다른 ETF] 같은섹터 & Jaccard < %.2f (상위 10개)' % MID)
y = P[(P['같은섹터']) & (P['Jaccard'] < MID)].sort_values(['공개종목수_A', '공개종목수_B'], ascending=False)
print(y[show].round(2).head(10).to_string(index=False) if len(y) else '없음')

print('\n[같은 섹터 안 쌍의 분류]')
print(P[P['같은섹터']]['분류'].value_counts().to_string())

# ---------- 3) 히트맵 ----------
fig, ax = plt.subplots(figsize=(17, 15))
im = ax.imshow(M.values, cmap='YlOrRd', vmin=0, vmax=1)
ax.set_xticks(range(len(names)))
ax.set_yticks(range(len(names)))
ax.set_xticklabels(names, rotation=90, fontsize=6)
ax.set_yticklabels(names, fontsize=6)
ax.set_title(f'ETF 간 상위 공개종목 겹침 (Jaccard, ETF {len(names)}개 / 대분류·섹터 순 정렬)')
fig.colorbar(im, ax=ax, shrink=0.6, label='Jaccard')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'etf_overlap_heatmap.png'), dpi=150)
plt.close()

# 겹침이 있는 ETF만 확대 (파트너가 하나라도 Jaccard >= MID)
keep = [n for n in names if (M.loc[n].drop(n) >= MID).any()]
if len(keep) >= 2:
    Mk = M.loc[keep, keep]
    fig, ax = plt.subplots(figsize=(max(8, len(keep) * 0.42), max(7, len(keep) * 0.4)))
    ax.imshow(Mk.values, cmap='YlOrRd', vmin=0, vmax=1)
    ax.set_xticks(range(len(keep)))
    ax.set_yticks(range(len(keep)))
    ax.set_xticklabels(keep, rotation=90, fontsize=7)
    ax.set_yticklabels(keep, fontsize=7)
    for i in range(len(keep)):
        for j in range(len(keep)):
            v = Mk.values[i, j]
            if i != j and v >= MID:
                ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=5)
    ax.set_title(f'겹침 있는 ETF만 확대 (Jaccard >= {MID} 인 짝이 있는 {len(keep)}개)')
    plt.tight_layout()
    plt.savefig(os.path.join(OUT_DIR, 'etf_overlap_heatmap_zoom.png'), dpi=150)
    plt.close()

# ---------- 4) 종목 편입 빈도 / 집중도 ----------
base = c[c['ETF명'].isin(sets.index)]            # 쌍 비교와 같은 ETF 집합
freq = (base.groupby('key')
        .agg(종목명=('종목명', 'first'), 편입ETF수=('ETF명', 'nunique'))
        .sort_values('편입ETF수', ascending=False).reset_index())
freq['ETF비율%'] = freq['편입ETF수'] / len(sets) * 100
freq.to_csv(os.path.join(OUT_DIR, 'stock_frequency.csv'), index=False, encoding='utf-8-sig')

slots = freq['편입ETF수'].sum()
share = freq['편입ETF수'] / slots
hhi = (share ** 2).sum()
print(f'\n[종목 편입 빈도] ETF {len(sets)}개의 공개 종목 칸 {slots}개 = 서로 다른 종목 {len(freq)}개')
print(f'  평균: 종목 1개가 ETF {slots / len(freq):.2f}개에 편입')
print(f'  상위 10개 종목이 차지하는 칸 비율 {share.head(10).sum() * 100:.1f}%')
print(f'  HHI {hhi:.4f} → 유효 종목 수(1/HHI) {1 / hhi:.0f}개  (공개된 종목 칸이 {len(freq)}개 종목에 고르게 퍼졌다면 {len(freq)}개)')
print(f'  2개 이상 ETF에 편입된 종목 {int((freq["편입ETF수"] >= 2).sum())}개 / 전체 {len(freq)}개')
print('\n[가장 많은 ETF에 들어간 종목 TOP 15]')
print(freq.head(15)[['종목명', '편입ETF수', 'ETF비율%']].round(1).to_string(index=False))

fig, ax = plt.subplots(figsize=(9, 6))
t = freq.head(20).iloc[::-1]
ax.barh(t['종목명'], t['편입ETF수'], color='#c0392b')
ax.set_xlabel(f'편입 ETF 수 (분석 대상 {len(sets)}개 중)')
ax.set_title('많은 ETF에 반복해서 들어가는 종목 TOP 20')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'stock_frequency_top20.png'), dpi=150)
plt.close()

# 대분류별 집중도
print('\n[대분류별 집중도]')
for g, sub in base.groupby('대분류'):
    f = sub.groupby('key')['ETF명'].nunique().sort_values(ascending=False)
    n_etf = sub['ETF명'].nunique()
    s = f / f.sum()
    print(f'  {g}: ETF {n_etf}개, 서로 다른 종목 {len(f)}개, 상위 5개 종목 칸 비율 {s.head(5).sum() * 100:.1f}%, '
          f'1위 {sub[sub.key == f.index[0]]["종목명"].iloc[0]}({f.iloc[0]}개 ETF)')

print(f'\n저장 폴더: {OUT_DIR}')