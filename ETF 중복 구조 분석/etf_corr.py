# -*- coding: utf-8 -*-
"""
ETF 수익률 상관관계 분석 (내 PC에서 실행)
목적: 구성종목 겹침(가중 겹침, Jaccard)과 실제 가격 움직임(일간 수익률 상관)이 얼마나 일치하는지 검증하고,
      직접 분류한 대분류/섹터가 상관 구조를 설명하는지 확인한다.

[사전 고정 사항 - 결과를 본 뒤 바꾸지 않는다]
  기간: 2025-10-17 ~ 2026-10-16 (최근 1년)
  수익률: 종가 기준 일간 수익률(pct_change)
  최소 관측일: 200일 미만 ETF(신규 상장)는 제외
  상관계수: 피어슨. 겹침과의 관계는 순위상관(스피어먼)으로 확인
필요 패키지: pip install finance-datareader
입력: 송호빈_ETF_유니버스.xlsx, etf_out/etf_weighted_overlap_*.csv
출력: etf_out/etf_return_corr.csv, etf_pair_overlap_vs_corr.csv, etf_corr_heatmap.png
"""
import os
import glob
import time
import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import matplotlib.pyplot as plt

# =========================== [설정] ===========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE_DIR, '송호빈_ETF_유니버스.xlsx')
OUT_DIR = os.path.join(BASE_DIR, 'etf_out')
START, END = '2025-10-17', '2026-10-16'
MIN_DAYS = 200
SLEEP = 0.3
RETRY = 3
TEST_N = None            # 처음엔 5 로 시험 -> 문제 없으면 None
# 해외종목 금액이 빠져 비중이 왜곡되는 혼합형(가중 겹침 비교에서 제외)
BAD_MIXED = ['TIGER 글로벌AI사이버보안', 'TIGER 구글 밸류체인', 'TIMEFOLIO 글로벌우주테크&방산액티브',
             'KOACT 팔란티어', 'ACE 엔비디아밸류체인액티브', 'ACE 일라이릴리밸류체인', 'KIWOOM 글로벌AI반도체']
# ==============================================================
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False
os.makedirs(OUT_DIR, exist_ok=True)


def norm_ticker(v):
    s = str(v).strip().upper()
    return s.zfill(6) if s.isdigit() else s


def get_close(tk):
    last = None
    for k in range(RETRY):
        try:
            df = fdr.DataReader(tk, START, END)
            if df is not None and len(df) and 'Close' in df.columns:
                return df['Close'].astype(float)
            last = ValueError('빈 결과')
        except Exception as e:
            last = e
        time.sleep(1.0 + k)
    raise last


def main():
    S = pd.read_excel(XLSX, sheet_name='1. ETF 요약', dtype=str)
    S['티커'] = S['티커(단축코드)'].map(norm_ticker)
    # 대분류 이름 뒤의 비중 표기 '(60%)' 등은 분석에 쓰지 않는다
    S['대분류'] = S['대분류'].str.replace(r'\s*\(.*?\)\s*$', '', regex=True)
    if TEST_N:
        S = S.head(TEST_N)

    prices, fails = {}, []
    for k, r in enumerate(S.itertuples(index=False), 1):
        try:
            prices[r.ETF명] = get_close(r.티커)
        except Exception as e:
            fails.append((r.ETF명, r.티커, repr(e)[:80]))
        time.sleep(SLEEP)
        if k % 10 == 0 or k == len(S):
            print(f'  진행 {k}/{len(S)}')
    print(f'수집 성공 {len(prices)}개, 실패 {len(fails)}개')
    for f in fails:
        print('  [실패]', f)

    P = pd.DataFrame(prices).sort_index()
    cnt = P.count()
    short = cnt[cnt < MIN_DAYS].index.tolist()
    if short:
        print(f'관측일 {MIN_DAYS}일 미만으로 제외: {len(short)}개 {short}')
    P = P.drop(columns=short)
    R = P.pct_change(fill_method=None)
    C = R.corr(min_periods=MIN_DAYS - 20)
    C.to_csv(os.path.join(OUT_DIR, 'etf_return_corr.csv'), encoding='utf-8-sig')

    # --- 쌍 단위 표: 수익률 상관 + 같은 대분류/섹터 여부 ---
    meta = S.set_index('ETF명')[['대분류', '섹터']]
    names = list(C.columns)
    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            rows.append({'ETF_A': a, 'ETF_B': b, '수익률상관': C.loc[a, b],
                         '같은대분류': meta.loc[a, '대분류'] == meta.loc[b, '대분류'],
                         '같은섹터': meta.loc[a, '섹터'] == meta.loc[b, '섹터']})
    T = pd.DataFrame(rows)

    print('\n[1] 직접 분류가 상관 구조를 설명하는가 (평균 수익률 상관)')
    print('  같은 섹터  :', round(T.loc[T.같은섹터, '수익률상관'].mean(), 3), f'({int(T.같은섹터.sum())}쌍)')
    print('  같은 대분류(섹터는 다름):',
          round(T.loc[T.같은대분류 & ~T.같은섹터, '수익률상관'].mean(), 3))
    print('  대분류도 다름:', round(T.loc[~T.같은대분류, '수익률상관'].mean(), 3))

    # --- 구성 겹침 vs 수익률 상관 ---
    wf = sorted(glob.glob(os.path.join(OUT_DIR, 'etf_weighted_overlap_*.csv')))
    if wf:
        W = pd.read_csv(wf[-1])
        W = W[~W.ETF_A.isin(BAD_MIXED) & ~W.ETF_B.isin(BAD_MIXED)]
        M = T.merge(W, on=['ETF_A', 'ETF_B'], how='inner')
        # 같은 쌍이 (B, A) 순서로 저장된 경우도 맞춘다
        W2 = W.rename(columns={'ETF_A': 'ETF_B', 'ETF_B': 'ETF_A'})
        M = pd.concat([M, T.merge(W2, on=['ETF_A', 'ETF_B'], how='inner')], ignore_index=True)
        M.to_csv(os.path.join(OUT_DIR, 'etf_pair_overlap_vs_corr.csv'), index=False, encoding='utf-8-sig')
        print(f'\n[2] 구성 겹침(가중) vs 수익률 상관: {len(M)}쌍')
        if len(M) >= 10:
            print('  스피어먼 순위상관:', round(M['가중겹침%'].corr(M['수익률상관'], method='spearman'), 3))
        hi = M[M['가중겹침%'] >= 50]
        lo = M[M['가중겹침%'] < 20]
        if len(hi):
            print(f'  겹침 50% 이상 {len(hi)}쌍의 평균 수익률 상관: {hi["수익률상관"].mean():.3f}')
        if len(lo):
            print(f'  겹침 20% 미만 {len(lo)}쌍의 평균 수익률 상관: {lo["수익률상관"].mean():.3f}')
        print('\n  겹침은 낮은데 수익률 상관이 높은 쌍 (구성으로는 안 보이는 동조)')
        print(M[M['가중겹침%'] < 20].sort_values('수익률상관', ascending=False)
              .head(10)[['ETF_A', 'ETF_B', '가중겹침%', '수익률상관']].round(3).to_string(index=False))
    else:
        print('\n[2] etf_weighted_overlap_*.csv 가 없어 겹침 비교는 건너뜁니다.')

    # --- 히트맵: 직접 분류 순서로 정렬 ---
    order = meta.loc[names].sort_values(['대분류', '섹터']).index.tolist()
    Cm = C.loc[order, order]
    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(Cm.values, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(order)))
    ax.set_yticks(range(len(order)))
    ax.set_xticklabels(order, rotation=90, fontsize=5)
    ax.set_yticklabels(order, fontsize=5)
    fig.colorbar(im, ax=ax, shrink=0.6, label='일간 수익률 상관계수')
    ax.set_title(f'ETF 수익률 상관 ({START} ~ {END}, 대분류·섹터 순 정렬)')
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, 'etf_corr_heatmap.png'), dpi=150)
    print('\n저장 완료:', OUT_DIR)


if __name__ == '__main__':
    main()