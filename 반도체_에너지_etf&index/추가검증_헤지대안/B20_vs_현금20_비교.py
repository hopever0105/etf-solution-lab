#%% 0. 설정과 DB 연결
# B 20% (지수 A 80% + 에너지 바스켓 20%) 가 "지수 A 80% + 현금 20%" 보다 나은지 비교한다.
# 질문: 현금 20% 로도 낙폭이 비슷하게 줄면 에너지 바스켓을 넣은 의미가 약하다.
# ETF_발행시나리오_2.py 셀 11 과 같은 데이터·같은 분기 리셋 규칙을 쓴다. DB 에는 쓰지 않는다(읽기만).
import os
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)

DB_USER = os.environ.get("DB_USER", "root")
DB_PW = os.environ["DB_PW"]
engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PW)}@127.0.0.1/stock_db?charset=utf8mb4"
)

VARIANT_A = "E_quota_buffer"
EN_NAMES = ["S-Oil", "SK이노베이션", "한국가스공사"]
CASH_RATES = [0.0, 0.03]   # 현금 연 수익률 가정: 0% 와 3% (실제 금리 시계열 아님)

#%% 1. 지수 A, 에너지 바스켓, KOSPI 레벨
lv = pd.read_sql("SELECT * FROM idx_level", engine)
lv["날짜"] = pd.to_datetime(lv["날짜"])
A_lv = lv[lv["variant"] == VARIANT_A].set_index("날짜")["지수"].astype(float).sort_index()

tk = pd.read_sql("SELECT 종목코드, 종목명 FROM fdr_kr_ticker", engine)
en_codes = {}
for nm in EN_NAMES:
    hit = tk[tk["종목명"] == nm]["종목코드"].unique().tolist()
    assert len(hit) == 1, f"{nm} 코드 조회 결과: {hit}"
    en_codes[nm] = hit[0]

codes_sql = ",".join(f"'{c}'" for c in en_codes.values())
px = pd.read_sql(f"SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({codes_sql})", engine)
px["날짜"] = pd.to_datetime(px["날짜"])
px = px.pivot(index="날짜", columns="종목코드", values="종가").astype(float).sort_index()
px = px[list(en_codes.values())].dropna()

kp = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'KOSPI'", engine)
kp["Date"] = pd.to_datetime(kp["Date"])
K_lv = kp.set_index("Date")["Close"].astype(float).sort_index()


#%% 2. 분기 리셋 결합 (ETF_발행시나리오_2.py 셀 11 과 같은 함수)
def quarter_reset(levels, weights):
    levels = levels.dropna()
    q = levels.index.to_period("Q")
    out = pd.Series(index=levels.index, dtype=float)
    v0 = 1.0
    prev_row = None
    for _, seg in levels.groupby(q):
        base = prev_row if prev_row is not None else seg.iloc[0]
        rel = seg / base
        val = v0 * (rel * pd.Series(weights)).sum(axis=1)
        out.loc[seg.index] = val.values
        v0 = val.iloc[-1]
        prev_row = seg.iloc[-1]
    return out


EN_lv = quarter_reset(px, {c: 1 / len(en_codes) for c in en_codes.values()})

base = pd.concat({"A": A_lv, "EN": EN_lv, "KOSPI": K_lv}, axis=1).dropna()
# 현금 레벨: 달력일 기준 연복리
days = (base.index - base.index[0]).days.values
for r in CASH_RATES:
    base[f"CASH{r:.0%}"] = (1 + r) ** (days / 365.25)

series = {
    "지수 A": base["A"],
    "B 20% (A80+에너지20)": quarter_reset(base[["A", "EN"]], {"A": 0.8, "EN": 0.2}),
}
for r in CASH_RATES:
    col = f"CASH{r:.0%}"
    series[f"A80+현금20 (연{r:.0%})"] = quarter_reset(base[["A", col]], {"A": 0.8, col: 0.2})
series["KOSPI"] = base["KOSPI"]
lv_all = pd.DataFrame(series)
print("기간:", lv_all.index[0].date(), "~", lv_all.index[-1].date(), "/", len(lv_all), "거래일")


#%% 3. 지표: 누적·연환산·변동성·MDD·샤프(무위험 0)·지수 A 대비 하락장 방어
def stats(s, a):
    r = s.pct_change().dropna()
    ra = a.pct_change().dropna()
    n_year = (s.index[-1] - s.index[0]).days / 365.25
    tot = s.iloc[-1] / s.iloc[0] - 1
    cagr = (1 + tot) ** (1 / n_year) - 1
    vol = r.std() * np.sqrt(252)
    mdd = (s / s.cummax() - 1).min()
    down = ra < 0
    # 지수 A 가 떨어진 날 평균 수익률 비율 (낮을수록 방어)
    down_capture = r[down].mean() / ra[down].mean()
    corr_a = r.corr(ra)
    return [tot * 100, cagr * 100, vol * 100, mdd * 100, cagr / vol if vol > 0 else np.nan,
            down_capture, corr_a]


cols = ["누적(%)", "연환산(%)", "변동성(%)", "최대낙폭(%)", "수익/변동성", "하락장 참여율(A=1)", "A와 상관"]
rows = []
for label, years in [("전체", None), ("최근 3년", 3), ("최근 1년", 1)]:
    start = lv_all.index[0] if years is None else lv_all.index[-1] - pd.DateOffset(years=years)
    seg = lv_all[lv_all.index >= start]
    for name in seg.columns:
        rows.append([label, seg.index[0].date(), name] + stats(seg[name], seg["지수 A"]))
res = pd.DataFrame(rows, columns=["구간", "시작일", "구분"] + cols).round(2)
print(res.to_string(index=False))

#%% 4. 지수 A 의 큰 낙폭 구간에서 각 안이 얼마나 빠졌나
a = lv_all["지수 A"]
dd = a / a.cummax() - 1
trough = dd.idxmin()
peak = a.loc[:trough].idxmax()
print(f"\n지수 A 최대낙폭 구간: {peak.date()} ~ {trough.date()} ({dd.min():.1%})")
for name in lv_all.columns:
    s = lv_all[name]
    print(f"  {name:<22} {s.loc[trough] / s.loc[peak] - 1:+.1%}")

# 에너지 바스켓과 지수 A 의 상관 (일간)
print("\n에너지 바스켓 vs 지수 A 일간 상관:", round(base["EN"].pct_change().corr(base["A"].pct_change()), 3))

out_dir = os.path.join(os.path.expanduser("~"), "etf_pdf")
os.makedirs(out_dir, exist_ok=True)
res.to_csv(os.path.join(out_dir, "B20_vs_cash20.csv"), index=False, encoding="utf-8-sig")
lv_all.to_csv(os.path.join(out_dir, "B20_vs_cash20_levels.csv"), encoding="utf-8-sig")
print("저장:", out_dir)
