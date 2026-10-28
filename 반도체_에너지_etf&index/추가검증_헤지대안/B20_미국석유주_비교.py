#%% 0. 설정과 DB 연결
# 에너지 바스켓을 미국 석유 메이저(엑슨모빌 XOM, 셰브론 CVX)로 바꾸거나 섞으면 어떻게 되는지 비교한다.
# B20_vs_현금20_비교.py 와 같은 기간·같은 분기 리셋 규칙. DB 는 읽기만 한다.
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
US_TICKERS = ["XOM", "CVX"]
CASH_RATE = 0.03   # 현금 연 3% 가정

#%% 1. 데이터 읽기
lv = pd.read_sql("SELECT * FROM idx_level", engine)
lv["날짜"] = pd.to_datetime(lv["날짜"])
A_lv = lv[lv["variant"] == VARIANT_A].set_index("날짜")["지수"].astype(float).sort_index()

tk = pd.read_sql("SELECT 종목코드, 종목명 FROM fdr_kr_ticker", engine)
en_codes = []
for nm in EN_NAMES:
    hit = tk[tk["종목명"] == nm]["종목코드"].unique().tolist()
    assert len(hit) == 1, f"{nm} 코드 조회 결과: {hit}"
    en_codes.append(hit[0])
codes_sql = ",".join(f"'{c}'" for c in en_codes)
kr = pd.read_sql(f"SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({codes_sql})", engine)
kr["날짜"] = pd.to_datetime(kr["날짜"])
kr = kr.pivot(index="날짜", columns="종목코드", values="종가").astype(float).sort_index()[en_codes].dropna()

# 미국 주가: 배당 제외 가격지수와 맞추려고 수정종가가 아닌 종가를 쓴다
us_sql = ",".join(f"'{t}'" for t in US_TICKERS)
us = pd.read_sql(f"SELECT 날짜, 티커, 종가 FROM us_price WHERE 티커 IN ({us_sql})", engine)
us["날짜"] = pd.to_datetime(us["날짜"])
us = us.pivot(index="날짜", columns="티커", values="종가").astype(float).sort_index()[US_TICKERS].dropna()

fx = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'USDKRW'", engine)
fx["Date"] = pd.to_datetime(fx["Date"])
fx = fx.set_index("Date")["Close"].astype(float).sort_index()

# 한국 거래일 기준으로 맞춘다. 미국 종가는 한국 장보다 늦게 나오므로 '전날까지의 마지막 미국 종가'를 쓴다.
kr_days = A_lv.index
us_on_kr = us.reindex(us.index.union(kr_days)).ffill().shift(1).reindex(kr_days)
fx_on_kr = fx.reindex(fx.index.union(kr_days)).ffill().reindex(kr_days)
us_krw = us_on_kr.mul(fx_on_kr, axis=0)


#%% 2. 분기 리셋 결합
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


EN_kr = quarter_reset(kr, {c: 1 / len(en_codes) for c in en_codes})
EN_us = quarter_reset(us_krw, {t: 1 / len(US_TICKERS) for t in US_TICKERS})        # 원화 환산 (환노출)
EN_us_h = quarter_reset(us_on_kr, {t: 1 / len(US_TICKERS) for t in US_TICKERS})    # 달러 그대로 (환헤지 가정, 헤지비용 무시)

base = pd.concat({"A": A_lv, "KR": EN_kr, "US": EN_us, "USH": EN_us_h}, axis=1).dropna()
days = (base.index - base.index[0]).days.values
base["CASH"] = (1 + CASH_RATE) ** (days / 365.25)

lv_all = pd.DataFrame({
    "지수 A": base["A"],
    "B20 국내에너지 (기존)": quarter_reset(base[["A", "KR"]], {"A": 0.8, "KR": 0.2}),
    "A80+미국석유20 (환노출)": quarter_reset(base[["A", "US"]], {"A": 0.8, "US": 0.2}),
    "A80+미국석유20 (환헤지)": quarter_reset(base[["A", "USH"]], {"A": 0.8, "USH": 0.2}),
    "A80+국내10+미국10 (환노출)": quarter_reset(base[["A", "KR", "US"]], {"A": 0.8, "KR": 0.1, "US": 0.1}),
    "A80+현금20 (연3%)": quarter_reset(base[["A", "CASH"]], {"A": 0.8, "CASH": 0.2}),
})
print("기간:", lv_all.index[0].date(), "~", lv_all.index[-1].date(), "/", len(lv_all), "거래일")


#%% 3. 지표
def stats(s, a):
    r = s.pct_change().dropna()
    ra = a.pct_change().dropna()
    n_year = (s.index[-1] - s.index[0]).days / 365.25
    tot = s.iloc[-1] / s.iloc[0] - 1
    cagr = (1 + tot) ** (1 / n_year) - 1
    vol = r.std() * np.sqrt(252)
    mdd = (s / s.cummax() - 1).min()
    down = ra < 0
    return [tot * 100, cagr * 100, vol * 100, mdd * 100, cagr / vol, r[down].mean() / ra[down].mean()]


cols = ["누적(%)", "연환산(%)", "변동성(%)", "최대낙폭(%)", "수익/변동성", "하락일 참여율(A=1)"]
rows = []
for label, years in [("전체", None), ("최근 1년", 1)]:
    start = lv_all.index[0] if years is None else lv_all.index[-1] - pd.DateOffset(years=years)
    seg = lv_all[lv_all.index >= start]
    for name in seg.columns:
        rows.append([label, name] + stats(seg[name], seg["지수 A"]))
res = pd.DataFrame(rows, columns=["구간", "구분"] + cols).round(2)
print(res.to_string(index=False))

#%% 4. 지수 A 최대낙폭 구간, 상관
a = lv_all["지수 A"]
dd = a / a.cummax() - 1
trough = dd.idxmin()
peak = a.loc[:trough].idxmax()
print(f"\n지수 A 최대낙폭 구간: {peak.date()} ~ {trough.date()} ({dd.min():.1%})")
for name in lv_all.columns:
    s = lv_all[name]
    print(f"  {name:<26} {s.loc[trough] / s.loc[peak] - 1:+.1%}")
print(f"  (참고) 같은 구간 원달러 {fx_on_kr.loc[trough] / fx_on_kr.loc[peak] - 1:+.1%}, "
      f"국내에너지 {base['KR'].loc[trough] / base['KR'].loc[peak] - 1:+.1%}, "
      f"미국석유(원화) {base['US'].loc[trough] / base['US'].loc[peak] - 1:+.1%}, "
      f"미국석유(달러) {base['USH'].loc[trough] / base['USH'].loc[peak] - 1:+.1%}")

r = base[["A", "KR", "US", "USH"]].pct_change().dropna()
r["FX"] = fx_on_kr.reindex(r.index).pct_change()
print("\n일간 수익률 상관")
print(r.corr().round(3))

out_dir = os.path.join(os.path.expanduser("~"), "etf_pdf")
os.makedirs(out_dir, exist_ok=True)
res.to_csv(os.path.join(out_dir, "B20_us_oil.csv"), index=False, encoding="utf-8-sig")
print("저장:", out_dir)
