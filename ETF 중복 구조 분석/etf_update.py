# -*- coding: utf-8 -*-
"""
ETF 유니버스 갱신 자동화 v2 (pykrx 사용, 내 PC에서 실행)
엑셀 '1. ETF 요약'에 있는 ETF 티커마다
  (1) 최신 구성종목(PDF)  (2) 최근 괴리율  (3) 추적오차  (4) 거래대금
을 받아 기준일이 붙은 CSV로 저장하고, 비중이 있는 ETF끼리 가중 겹침(= sum of min weight)을 계산한다.

[v2 변경점 - 첫 실행에서 확인된 사실 반영]
  - 해외종목은 pykrx '비중' 열이 0 으로 온다 -> '금액' 열로 ETF별 비중을 직접 계산한다.
  - 해외종목 코드는 KRX 내부 코드(예 8176E1), 이름은 영문이다 -> 엑셀의 미국 티커와 직접 비교 불가.
    엑셀 대조는 6자리 한국 종목코드가 있는 ETF만 하고, 해외 이름은 foreign_names CSV로 따로 저장한다.
KRX 로그인 정보는 코드에 쓰지 않는다 (필요하면 환경변수 KRX_ID / KRX_PW 로만 사용).
"""
import os
import re
import time
import numpy as np
import pandas as pd
from pykrx import stock

# =========================== [설정] ===========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE_DIR, '송호빈_ETF_유니버스.xlsx')
OUT_DIR = os.path.join(BASE_DIR, 'etf_out')
STAT_DAYS = 60          # 괴리율/추적오차/거래대금 평균을 낼 최근 기간(달력일)
TOP_N_COMPARE = 10      # 엑셀 정리본과 비교할 상위 종목 개수
SLEEP = 0.3             # 과호출 방지
TEST_N = None           # 처음엔 5 로 두고 오류 확인 -> 문제 없으면 None (전체 98개)
# ==============================================================
os.makedirs(OUT_DIR, exist_ok=True)
KR_CODE = re.compile(r'^\d{6}$')


def norm_ticker(v):
    s = str(v).strip().upper()
    return s.zfill(6) if s.isdigit() else s


def last_trading_day(max_back=10):
    """오늘부터 거슬러 가며 ETF 목록이 나오는 가장 가까운 거래일(YYYYMMDD)."""
    d = pd.Timestamp.today().normalize()
    for _ in range(max_back):
        ds = d.strftime('%Y%m%d')
        try:
            if stock.get_etf_ticker_list(ds):
                return ds
        except Exception:
            pass
        d -= pd.Timedelta(days=1)
    raise RuntimeError('최근 거래일을 찾지 못했습니다 (pykrx/KRX 연결 확인)')


def main():
    summary = pd.read_excel(XLSX, sheet_name='1. ETF 요약', dtype=str)
    summary['티커'] = summary['티커(단축코드)'].map(norm_ticker)
    xl_hold = pd.read_excel(XLSX, sheet_name='2. ETF별 구성종목', dtype=str)
    xl_hold['ETF티커'] = xl_hold['티커'].map(norm_ticker)
    xl_hold['종목코드'] = xl_hold['티커/코드'].map(lambda v: norm_ticker(v) if pd.notna(v) else np.nan)

    asof = last_trading_day()
    start = (pd.Timestamp(asof) - pd.Timedelta(days=STAT_DAYS)).strftime('%Y%m%d')
    print(f'기준일 {asof} | 통계 조회 시작 {start}')

    targets = summary if TEST_N is None else summary.head(TEST_N)
    hold_rows, stat_rows, fails = [], [], []

    for k, r in enumerate(targets.itertuples(index=False), 1):
        tk, nm = r.티커, r.ETF명
        try:
            pdf = stock.get_etf_portfolio_deposit_file(tk, asof)
            if pdf is None or len(pdf) == 0:
                raise ValueError('구성종목 비어 있음')
            pdf = pdf.reset_index().rename(columns={pdf.index.name or 'index': '구성티커'})
            pdf['ETF티커'], pdf['ETF명'], pdf['기준일'] = tk, nm, asof
            hold_rows.append(pdf)

            dev = stock.get_etf_price_deviation(start, asof, tk)
            te = stock.get_etf_tracking_error(start, asof, tk)
            px = stock.get_etf_ohlcv_by_date(start, asof, tk)
            stat_rows.append({
                '기준일': asof, 'ETF티커': tk, 'ETF명': nm, '섹터': r.섹터,
                '평균|괴리율|%': dev['괴리율'].abs().mean() if len(dev) else np.nan,
                '최대|괴리율|%': dev['괴리율'].abs().max() if len(dev) else np.nan,
                '평균추적오차율%': te['추적오차율'].mean() if len(te) else np.nan,
                '평균거래대금(원)': px['거래대금'].mean() if len(px) else np.nan,
                '평균거래량': px['거래량'].mean() if len(px) else np.nan,
                '구성종목수(PDF)': len(pdf),
            })
        except Exception as e:
            fails.append((tk, nm, repr(e)))
            print(f'  [실패] {nm}({tk}): {e}')
        time.sleep(SLEEP)
        if k % 10 == 0 or k == len(targets):
            print(f'  진행 {k}/{len(targets)}')

    if not hold_rows:
        print('받은 구성종목이 없습니다. 실패 목록을 확인하세요.')
        return

    H = pd.concat(hold_rows, ignore_index=True)
    # 비중 직접 계산: pykrx '비중'이 0 인 해외종목이 있어서 '금액'으로 ETF별 비율(%)을 만든다
    H['금액'] = pd.to_numeric(H['금액'], errors='coerce').fillna(0.0).clip(lower=0)
    tot = H.groupby('ETF티커')['금액'].transform('sum')
    H['비중계산%'] = np.where(tot > 0, H['금액'] / tot * 100, 0.0)
    H.to_csv(os.path.join(OUT_DIR, f'etf_holdings_{asof}.csv'), index=False, encoding='utf-8-sig')
    S = pd.DataFrame(stat_rows)
    S.to_csv(os.path.join(OUT_DIR, f'etf_stats_{asof}.csv'), index=False, encoding='utf-8-sig')
    print(f'\n저장: etf_holdings_{asof}.csv ({len(H)}행) / etf_stats_{asof}.csv ({len(S)}행)')
    print('실패', len(fails), '개:', [f[1] for f in fails][:10])

    # --- 비중 확인: pykrx 비중 합 vs 금액으로 계산한 비중 ---
    chk = H.groupby(['ETF티커', 'ETF명']).agg(pykrx비중합=('비중', 'sum'), 금액합=('금액', 'sum'),
                                          종목수=('구성티커', 'count')).reset_index()
    print('\n[확인] ETF별 pykrx 비중 합 / 금액 합 (비중 합이 0 이어도 금액이 있으면 금액으로 계산함)')
    print(chk.round(1).head(15).to_string(index=False))
    print('\n[확인] 구성종목 상위(금액 기준) 샘플')
    top_show = H.sort_values(['ETF티커', '비중계산%'], ascending=[True, False]).groupby('ETF티커').head(3)
    print(top_show[['ETF명', '구성티커', '구성종목명', '비중계산%']].round(2).to_string(index=False))

    # --- 해외종목 이름 목록 따로 저장 (엑셀 미국 티커와 연결할 매핑표 만들 때 사용) ---
    foreign = H[~H['구성티커'].astype(str).str.match(KR_CODE)][['구성티커', '구성종목명']].drop_duplicates()
    foreign.to_csv(os.path.join(OUT_DIR, f'foreign_names_{asof}.csv'), index=False, encoding='utf-8-sig')
    print(f'\n[해외·기타 코드 종목] {len(foreign)}개 -> foreign_names_{asof}.csv (6자리 한국코드가 아닌 것)')

    # --- 엑셀 정리본 vs 현재 상위 종목 (한국 종목코드 기준, 6자리 코드가 있는 ETF만) ---
    cmp_rows, skipped = [], []
    for tk, g in H.groupby('ETF티커'):
        xl = xl_hold[xl_hold['ETF티커'] == tk]['종목코드'].dropna()
        xl = {x for x in xl if KR_CODE.match(str(x))}
        if not xl:
            skipped.append(g['ETF명'].iloc[0])
            continue
        top_now = set(g.sort_values('비중계산%', ascending=False)['구성티커'].astype(str).head(TOP_N_COMPARE))
        cmp_rows.append({'ETF티커': tk, 'ETF명': g['ETF명'].iloc[0], '엑셀종목수': len(xl),
                         '현재상위에도있는수': len(xl & top_now), '일치율': len(xl & top_now) / len(xl)})
    print(f'\n[엑셀 vs 현재 상위 {TOP_N_COMPARE}] 한국 종목코드가 없는 ETF {len(skipped)}개는 비교 제외(해외종목 위주)')
    C = pd.DataFrame(cmp_rows)
    if len(C):
        C.to_csv(os.path.join(OUT_DIR, f'excel_vs_now_{asof}.csv'), index=False, encoding='utf-8-sig')
        print(f'  비교 ETF {len(C)}개, 평균 일치율 {C["일치율"].mean() * 100:.1f}% '
              f'(낮은 ETF = 구성이 바뀌었거나 상위 {TOP_N_COMPARE}개 밖에 있어 갱신 필요)')
        print(C.sort_values('일치율').head(10).round(2).to_string(index=False))

    # --- 가중 겹침: sum_i min(w_a,i , w_b,i)   (0~100%) ---
    W = H[H['비중계산%'] > 0].copy()
    if W.empty:
        print('\n[가중 겹침] 금액이 있는 구성종목이 없어 건너뜁니다.')
        return
    W['k'] = W['구성티커'].astype(str)
    mat = W.pivot_table(index='ETF티커', columns='k', values='비중계산%', aggfunc='sum').fillna(0.0)
    mat = mat.div(mat.sum(axis=1), axis=0) * 100
    ids = list(mat.index)
    name_of = dict(zip(H['ETF티커'], H['ETF명']))
    arr = mat.values
    rows = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ov = np.minimum(arr[i], arr[j]).sum()
            if ov > 0:
                rows.append({'ETF_A': name_of[ids[i]], 'ETF_B': name_of[ids[j]], '가중겹침%': ov})
    if not rows:
        print('\n[가중 겹침] 겹치는 종목이 있는 쌍이 없습니다.')
        return
    O = pd.DataFrame(rows).sort_values('가중겹침%', ascending=False)
    O.to_csv(os.path.join(OUT_DIR, f'etf_weighted_overlap_{asof}.csv'), index=False, encoding='utf-8-sig')
    print(f'\n[가중 겹침 상위 15쌍] (ETF {len(ids)}개 기준, 100% = 구성과 비중이 완전히 같음)')
    print(O.head(15).round(1).to_string(index=False))
    print(f'\n저장 폴더: {OUT_DIR}')


if __name__ == '__main__':
    main()