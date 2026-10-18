#%% 0. 설정과 DB 연결
# day5: B 20% (주식 지수 A 80% + 에너지주 바스켓 20%) 를 ETF 구성종목표(PDF)로 바꾼다.
# 먼저 day3_index_engine.py 까지 실행해서 idx_weight_hist 가 DB에 있어야 한다.
# 비밀번호는 코드에 쓰지 않고 환경변수 DB_PW 에서 읽는다. (DB 계정이 root 가 아니면 DB_USER 도 환경변수로)
import os
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text, inspect

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)
pd.set_option("display.float_format", lambda x: f"{x:,.4f}")

DB_USER = os.environ.get("DB_USER", "root")
DB_PW = os.environ["DB_PW"]
engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PW)}@127.0.0.1/stock_db?charset=utf8mb4"
)

# 지수 / 상품 파라미터
VARIANT_A = "E_quota_buffer"   # 주 사양 (Day 3의 E)
W_A = 0.80                     # 주식 지수 비중
W_EN = 0.20                    # 에너지주 바스켓 비중 (분기마다 이 비율로 되돌림)
CAP = 0.25                     # 종목 캡 (A와 에너지 바스켓 각각)
EN_MCAP_MIN = 3000e8           # 에너지 바스켓 시총 기준 3,000억 (Day 4의 EN_base)
EN_ADV_MIN = 10e8              # 63거래일 평균 거래대금 10억
EN_INDUSTRY = ["석유 정제품 제조업", "연료용 가스 제조 및 배관공급업", "연료 소매업"]
# EN_INDUSTRY 는 Day 4 보고서에 적힌 산업명을 옮긴 것이다. day4 코드의 값과 다르면 그쪽에 맞춘다.

# ETF 설계 가정 (확인된 규정이 아니라 내가 둔 값)
AUM_WON = 100e8                # 상장 초기 순자산 100억 원
NAV_PER_SHARE = 10_000         # 1주당 기준가 (원)
CU_SHARES = 50_000             # 설정단위(CU) 1개 = ETF 5만 주 -> 5억 원
PART_RATE = 0.20               # 하루 거래대금의 20% 만 쓴다는 가정 (Day 4와 같음, 관행은 확인 안 됨)
MIN_STOCKS = 10                # 기사로 확인한 ETF 요건: 10종목 이상
MAX_WEIGHT = 0.30              # 기사로 확인한 ETF 요건: 종목당 30% 이내 (법령 원문은 확인 안 됨)

#%% 1. 필요한 테이블 / 컬럼 확인
# 테이블이 없으면 어떤 파일을 먼저 돌려야 하는지 알려 준다.
NEED = {
    "idx_weight_hist": "day2_universe_and_cap.py, day3_index_engine.py",
    "idx_candidate": "day1_data_check_and_hypothesis.py",
    "fdr_kr_ticker": "FinanceDataReader 종목 수집 코드 (프로젝트의 기존 수집 파일)",
    "kor_price": "국내 주식 데이터 수집.py",
}
insp = inspect(engine)
have = set(insp.get_table_names())
missing = [t for t in NEED if t not in have]
if missing:
    for t in missing:
        print(f"[없음] {t}  ->  먼저 실행: {NEED[t]}")
    raise SystemExit("필요한 테이블이 없어서 중단합니다.")

for t in NEED:
    cols = [c["name"] for c in insp.get_columns(t)]
    print(f"{t}: {cols}")
# 컬럼명이 아래 가정과 다르면 여기 출력을 보고 알려 주세요.
# 가정: idx_weight_hist(variant, D, impl, 종목코드, weight), idx_candidate(종목코드, 종목명),
#       fdr_kr_ticker(종목코드, 종목명, 시가총액, 산업, 종목구분), kor_price(날짜, 종가, 거래량, 종목코드)

#%% 2. 함수: 25% 캡 비중 (Day 2의 calculate_capped_weight 와 같은 규칙)
def calculate_capped_weight(mcap, cap=0.25):
    # 시총 비중에서 cap 을 넘는 종목은 cap 으로 고정하고, 남은 비중을 나머지에 시총 비례로 나눈다.
    # 새로 넘는 종목이 없을 때까지 반복한다.
    mcap = pd.Series(mcap, dtype=float)
    n = len(mcap)
    if n == 0:
        return mcap
    if cap * n < 1 - 1e-12:
        # 종목 수가 너무 적어 캡을 지킬 수 없으면 균등배분 (Day 4에서 4개 미만일 때 쓴 방식)
        return pd.Series(1.0 / n, index=mcap.index)
    w = mcap / mcap.sum()
    fixed = pd.Series(False, index=mcap.index)
    while True:
        over = (w > cap + 1e-12) & (~fixed)
        if not over.any():
            break
        fixed |= over
        w[fixed] = cap
        rest = 1.0 - cap * fixed.sum()
        free = ~fixed
        w[free] = mcap[free] / mcap[free].sum() * rest
    return w

#%% 3. 주식 지수 A 의 최신 비중
wh = pd.read_sql(f"SELECT * FROM idx_weight_hist WHERE variant = '{VARIANT_A}'", engine)
wh["D"] = pd.to_datetime(wh["D"])
wh["impl"] = pd.to_datetime(wh["impl"])
D_last = wh["D"].max()
IMPL = wh.loc[wh["D"] == D_last, "impl"].iloc[0]
A_w = wh[wh["D"] == D_last].set_index("종목코드")["weight"].astype(float)
print("최신 결정일 D:", D_last.date(), "/ 반영일:", IMPL.date(), "/ A 종목 수:", len(A_w), "/ 비중 합:", round(A_w.sum(), 6))

cand = pd.read_sql("SELECT 종목코드, 종목명 FROM idx_candidate", engine)
name_map = dict(zip(cand["종목코드"], cand["종목명"]))

#%% 4. 에너지주 바스켓 후보와 가격 읽기
fdr = pd.read_sql("SELECT * FROM fdr_kr_ticker", engine)
en = fdr[fdr["산업"].isin(EN_INDUSTRY)].copy()
if "종목구분" in en.columns:
    en = en[en["종목구분"] == "보통주"]
print("에너지 후보 종목 수:", len(en))   # Day 4 보고서에는 17개로 적혀 있다. 다르면 EN_INDUSTRY 를 점검
print(en["산업"].value_counts())
for c, nm in zip(en["종목코드"], en["종목명"]):
    name_map.setdefault(c, nm)

codes = sorted(set(A_w.index) | set(en["종목코드"]))
code_in = ",".join(f"'{c}'" for c in codes)
px = pd.read_sql(
    f"SELECT 날짜, 종목코드, 종가, 거래량 FROM kor_price WHERE 종목코드 IN ({code_in})", engine
)
px["날짜"] = pd.to_datetime(px["날짜"])
close = px.pivot(index="날짜", columns="종목코드", values="종가").sort_index()
vol = px.pivot(index="날짜", columns="종목코드", values="거래량").sort_index()
print("가격 기간:", close.index.min().date(), "~", close.index.max().date())

#%% 5. 에너지 바스켓 구성 (결정일 D_last 기준)
# 시총: 현재 시총 x (보정가격 / 마지막 보정가격). 일 등락 +-31% 초과일은 수익률 0 으로 둔 보정가격 (Day 2와 같은 방식)
ret = close.pct_change()
ret = ret.mask(ret.abs() > 0.31, 0.0)
adj = (1 + ret.fillna(0)).cumprod()
adv63 = (close * vol).rolling(63, min_periods=60).mean()

en = en.set_index("종목코드")
mcap_now = en["시가총액"].astype(float)
print("시가총액 단위 점검 (중앙값):", f"{mcap_now.median():,.0f}", "<- 원 단위면 수천억~수조 단위 숫자여야 함")

rows = []
for c in en.index:
    if c not in close.columns or pd.isna(close.at[D_last, c]):
        continue                                   # 결정일에 거래되지 않은 종목은 제외
    m = mcap_now[c] * adj.at[D_last, c] / adj[c].dropna().iloc[-1]
    rows.append((c, m, adv63.at[D_last, c]))
en_tbl = pd.DataFrame(rows, columns=["종목코드", "시총D", "ADV63"]).set_index("종목코드")
en_pick = en_tbl[(en_tbl["시총D"] >= EN_MCAP_MIN) & (en_tbl["ADV63"] >= EN_ADV_MIN)]
print("에너지 바스켓 편입 종목 수:", len(en_pick))

EN_w = calculate_capped_weight(en_pick["시총D"], cap=CAP)
print(EN_w.rename(index=name_map).sort_values(ascending=False))

#%% 6. 결합 비중 (B 20%) 과 규정 점검
B_w = (A_w * W_A).add(EN_w * W_EN, fill_value=0.0)
overlap = sorted(set(A_w.index) & set(EN_w.index))
print("A와 에너지 바스켓에 겹치는 종목:", [name_map.get(c, c) for c in overlap] or "없음")

chk = pd.DataFrame({
    "항목": ["종목 수", "최대 종목 비중", "비중 합"],
    "값": [len(B_w), B_w.max(), B_w.sum()],
    "기준": [f">= {MIN_STOCKS}", f"<= {MAX_WEIGHT:.0%}", "1.0"],
    "판정": ["통과" if len(B_w) >= MIN_STOCKS else "미달",
             "통과" if B_w.max() <= MAX_WEIGHT else "초과",
             "통과" if abs(B_w.sum() - 1) < 1e-9 else "확인"],
})
print(chk)

#%% 7. 구성종목표(PDF) 만들기
# 기준가: 반영일 직전 거래일 종가 (Day 3의 P_ref 규칙). 반영일이 가격 데이터보다 뒤면 마지막 거래일 종가를 쓴다.
pre = close.index[close.index < IMPL]
REF_DATE = pre.max() if len(pre) else close.index.max()
if IMPL > close.index.max():
    REF_DATE = close.index.max()
    print("반영일이 가격 데이터보다 뒤라서 마지막 거래일을 기준가로 씁니다:", REF_DATE.date())
print("기준가 날짜:", REF_DATE.date())

price = close.loc[REF_DATE, B_w.index]
cu_value = NAV_PER_SHARE * CU_SHARES                       # CU 1개의 금액
pdf = pd.DataFrame({"종목명": [name_map.get(c, c) for c in B_w.index],
                    "목표비중": B_w.values,
                    "A비중": A_w.reindex(B_w.index).fillna(0).values * W_A,
                    "에너지비중": EN_w.reindex(B_w.index).fillna(0).values * W_EN,
                    "기준가": price.values}, index=B_w.index)
pdf["CU당_주수"] = np.floor(pdf["목표비중"] * cu_value / pdf["기준가"]).astype(int)
pdf["CU당_금액"] = pdf["CU당_주수"] * pdf["기준가"]
cash = cu_value - pdf["CU당_금액"].sum()
pdf["실제비중"] = pdf["CU당_금액"] / cu_value
pdf = pdf.sort_values("목표비중", ascending=False)
print(pdf)
print(f"CU 1개 금액 {cu_value:,.0f}원 / 현금(잔여) {cash:,.0f}원 ({cash / cu_value:.3%})")

#%% 8. 유동성 점검 (AUM 기준 보유금액 대비 거래대금)
adv_ref = adv63.loc[REF_DATE, B_w.index]
liq = pd.DataFrame({"종목명": pdf["종목명"],
                    "보유금액(억)": (B_w * AUM_WON / 1e8).reindex(pdf.index),
                    "ADV63(억)": (adv_ref / 1e8).reindex(pdf.index)})
liq["참여율"] = liq["보유금액(억)"] / liq["ADV63(억)"]
liq["정리일수"] = liq["참여율"] / PART_RATE
print(f"AUM {AUM_WON / 1e8:,.0f}억 원 기준")
print(liq.sort_values("정리일수", ascending=False))
print("가장 빡빡한 종목:", liq["정리일수"].idxmax(), "->", name_map.get(liq["정리일수"].idxmax()),
      f"{liq['정리일수'].max():.2f}일")

#%% 9. 이전 구성과 비교한 리밸런싱 주문표
new = pd.DataFrame({"D": D_last, "종목코드": B_w.index, "weight": B_w.values})
try:
    prev_all = pd.read_sql("SELECT * FROM idx_etf_pdf", engine)
    prev_all["D"] = pd.to_datetime(prev_all["D"])
    prev_D = prev_all.loc[prev_all["D"] < D_last, "D"].max()
    prev = prev_all[prev_all["D"] == prev_D].set_index("종목코드")["weight"] if pd.notna(prev_D) else None
except Exception:
    prev = None                                  # 테이블이 아직 없으면 처음 구성이다

if prev is None:
    print("이전 구성이 없어서 처음 구성으로 저장합니다.")
else:
    diff = pd.DataFrame({"이전": prev, "신규": B_w}).fillna(0.0)
    diff["변화"] = diff["신규"] - diff["이전"]
    diff["종목명"] = [name_map.get(c, c) for c in diff.index]
    print(diff.sort_values("변화"))
    print("편도 회전율:", round(diff["변화"].clip(lower=0).sum(), 4))

#%% 10. DB 저장과 파일 저장
# 같은 결정일 D 가 이미 있으면 지우고 다시 넣는다.
with engine.begin() as con:
    if "idx_etf_pdf" in inspect(engine).get_table_names():
        con.execute(text("DELETE FROM idx_etf_pdf WHERE D = :d"), {"d": D_last.strftime("%Y-%m-%d")})
new.to_sql("idx_etf_pdf", engine, if_exists="append", index=False)

out_dir = os.path.join(os.path.expanduser("~"), "etf_pdf")
os.makedirs(out_dir, exist_ok=True)
fn = os.path.join(out_dir, f"B20_PDF_{D_last.strftime('%Y%m%d')}.csv")
pdf.to_csv(fn, encoding="utf-8-sig")
print("저장:", fn)
# csv 는 .gitignore 에 들어 있어서 GitHub 에는 올라가지 않는다.

#%% 셀 11: B 20% 구간 수익률 (최근 1년·3년, 이 ETF를 샀다면)
import numpy as np
import pandas as pd

# 지수 A 일별 레벨 (idx_level: 날짜, 지수, variant)
lv = pd.read_sql("SELECT * FROM idx_level", engine)
lv["날짜"] = pd.to_datetime(lv["날짜"])
A_lv = lv[lv["variant"] == "E_quota_buffer"].set_index("날짜")["지수"].astype(float).sort_index()

# 에너지 바스켓 3종목: 종목명으로 코드를 찾는다 (fdr_kr_ticker)
EN_NAMES = ["S-Oil", "SK이노베이션", "한국가스공사"]
tk = pd.read_sql("SELECT 종목코드, 종목명 FROM fdr_kr_ticker", engine)
en_codes = {}
for nm in EN_NAMES:
    hit = tk[tk["종목명"] == nm]["종목코드"].unique().tolist()
    assert len(hit) == 1, f"{nm} 코드 조회 결과: {hit} (종목명 확인 필요)"
    en_codes[nm] = hit[0]
print("에너지 바스켓 코드:", en_codes)

codes_sql = ",".join(f"'{c}'" for c in en_codes.values())
px = pd.read_sql(f"SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({codes_sql})", engine)
px["날짜"] = pd.to_datetime(px["날짜"])
px = px.pivot(index="날짜", columns="종목코드", values="종가").astype(float).sort_index()
px = px[list(en_codes.values())].dropna()


# 분기 리셋 결합: 분기 첫 거래일에 목표 비중으로 맞추고, 분기 중에는 비중이 흘러가게 둔다.
# 각 분기 구간의 시작 기준은 직전 구간의 마지막 종가다.
def quarter_reset(levels, weights):
    levels = levels.dropna()
    q = levels.index.to_period("Q")
    out = pd.Series(index=levels.index, dtype=float)
    v0 = 1.0
    prev_row = None
    for _, seg in levels.groupby(q):
        base = prev_row if prev_row is not None else seg.iloc[0]
        rel = seg / base                      # 구간 시작 대비 상대 수준
        val = v0 * (rel * pd.Series(weights)).sum(axis=1)
        out.loc[seg.index] = val.values
        v0 = val.iloc[-1]
        prev_row = seg.iloc[-1]
    return out

# 에너지 바스켓: 3종목 동일가중, 분기 리셋
w_en = {c: 1 / len(en_codes) for c in en_codes.values()}
EN_lv = quarter_reset(px, w_en)

# B 20% = 지수 A 80% + 에너지 바스켓 20%, 분기 리셋
both = pd.concat({"A": A_lv, "EN": EN_lv}, axis=1).dropna()
B_lv = quarter_reset(both, {"A": 0.8, "EN": 0.2})

# KOSPI 비교용 (tv_futures_price: Date, Close, Symbol)
kp = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'KOSPI'", engine)
kp["Date"] = pd.to_datetime(kp["Date"])
K_lv = kp.set_index("Date")["Close"].astype(float).sort_index()

lv_all = pd.concat({"지수 A": A_lv, "B 20%": B_lv, "KOSPI": K_lv}, axis=1).dropna()
end = lv_all.index[-1]
print("기간:", lv_all.index[0].date(), "~", end.date())

INVEST = 10_000_000     # 가정: 투자금 1,000만 원
FEE = 0.005             # 가정: 연 총보수 0.5% (실제 상품 보수 아님)

rows = []
for label, years in [("최근 1년", 1), ("최근 3년", 3), ("전체", None)]:
    start = lv_all.index[0] if years is None else end - pd.DateOffset(years=years)
    seg = lv_all[lv_all.index >= start]
    n_year = (seg.index[-1] - seg.index[0]).days / 365.25
    for col in lv_all.columns:
        s = seg[col]
        tot = s.iloc[-1] / s.iloc[0] - 1
        cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / n_year) - 1
        vol = s.pct_change().std() * np.sqrt(252)
        mdd = (s / s.cummax() - 1).min()
        after_fee = INVEST * (1 + tot) * (1 - FEE) ** n_year
        rows.append([label, col, seg.index[0].date(), round(tot * 100, 1), round(cagr * 100, 1),
                     round(vol * 100, 1), round(mdd * 100, 1), int(INVEST * (1 + tot)), int(after_fee)])

res = pd.DataFrame(rows, columns=["구간", "구분", "시작일", "누적(%)", "연환산(%)",
                                  "변동성(%)", "최대낙폭(%)", "1천만원→(원)", "보수차감 후(원)"])
print(res.to_string(index=False))

# 보고서 값과 대조: A 32.3/39.4/-47.3, B 28.7/33.5/-37.5, KOSPI 17.2/30.7/-39.1
print("\n[보고서 대조] 전체 구간 값이 위 숫자와 크게 다르면 알려 주세요.")

res.to_csv(r"C:\Users\arlo0\etf_pdf\B20_period_returns.csv", index=False, encoding="utf-8-sig")