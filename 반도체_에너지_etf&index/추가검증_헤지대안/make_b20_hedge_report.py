#%% 0. 설정
# B20 추가 검증 보고서 (PDF + Word): 에너지 바스켓 20% 를 현금 20% 또는 미국 석유 메이저(XOM·CVX) 20% 로 바꾸면?
# 기간·규칙은 B20 보고서(2026-10-18 작성, 데이터 2026-10-16 까지)와 같게 둔다. 그 뒤 데이터는 쓰지 않는다.
# DB 는 읽기만 한다. 계산은 B20_vs_현금20_비교.py, B20_미국석유주_비교.py 와 같다.
import os
import sys
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "jobapp"))
from jobkit.htmlpdf import Doc

OUT = os.path.join(HERE, "추가검증_헤지대안")
os.makedirs(OUT, exist_ok=True)
END = pd.Timestamp("2026-10-16")          # B20 보고서 마지막 데이터일
VARIANT_A = "E_quota_buffer"
EN_NAMES = ["S-Oil", "SK이노베이션", "한국가스공사"]
US_TICKERS = ["XOM", "CVX"]
CASH_RATE = 0.03

engine = create_engine(
    f"mysql+pymysql://{os.environ.get('DB_USER', 'root')}:{quote_plus(os.environ['DB_PW'])}@127.0.0.1/stock_db?charset=utf8mb4")
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

#%% 1. 데이터
lv = pd.read_sql("SELECT * FROM idx_level", engine)
lv["날짜"] = pd.to_datetime(lv["날짜"])
A_lv = lv[lv["variant"] == VARIANT_A].set_index("날짜")["지수"].astype(float).sort_index().loc[:END]

tk = pd.read_sql("SELECT 종목코드, 종목명 FROM fdr_kr_ticker", engine)
en_codes = []
for nm in EN_NAMES:
    hit = tk[tk["종목명"] == nm]["종목코드"].unique().tolist()
    assert len(hit) == 1, f"{nm}: {hit}"
    en_codes.append(hit[0])
kr = pd.read_sql("SELECT 날짜, 종목코드, 종가 FROM kor_price WHERE 종목코드 IN ({})".format(
    ",".join(f"'{c}'" for c in en_codes)), engine)
kr["날짜"] = pd.to_datetime(kr["날짜"])
kr = kr.pivot(index="날짜", columns="종목코드", values="종가").astype(float).sort_index()[en_codes].dropna().loc[:END]

us = pd.read_sql("SELECT 날짜, 티커, 종가 FROM us_price WHERE 티커 IN ({})".format(
    ",".join(f"'{t}'" for t in US_TICKERS)), engine)
us["날짜"] = pd.to_datetime(us["날짜"])
us = us.pivot(index="날짜", columns="티커", values="종가").astype(float).sort_index()[US_TICKERS].dropna()

fx = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'USDKRW'", engine)
fx["Date"] = pd.to_datetime(fx["Date"])
fx = fx.set_index("Date")["Close"].astype(float).sort_index()

kp = pd.read_sql("SELECT Date, Close FROM tv_futures_price WHERE Symbol = 'KOSPI'", engine)
kp["Date"] = pd.to_datetime(kp["Date"])
K_lv = kp.set_index("Date")["Close"].astype(float).sort_index().loc[:END]

days_kr = A_lv.index
us_on_kr = us.reindex(us.index.union(days_kr)).ffill().shift(1).reindex(days_kr)   # 미국 종가는 다음 한국 거래일에 반영
fx_on_kr = fx.reindex(fx.index.union(days_kr)).ffill().reindex(days_kr)


def quarter_reset(levels, weights):
    levels = levels.dropna()
    q = levels.index.to_period("Q")
    out = pd.Series(index=levels.index, dtype=float)
    v0, prev_row = 1.0, None
    for _, seg in levels.groupby(q):
        base = prev_row if prev_row is not None else seg.iloc[0]
        val = v0 * ((seg / base) * pd.Series(weights)).sum(axis=1)
        out.loc[seg.index] = val.values
        v0, prev_row = val.iloc[-1], seg.iloc[-1]
    return out


EN_kr = quarter_reset(kr, {c: 1 / 3 for c in en_codes})
EN_us = quarter_reset(us_on_kr.mul(fx_on_kr, axis=0), {t: 0.5 for t in US_TICKERS})
EN_ush = quarter_reset(us_on_kr, {t: 0.5 for t in US_TICKERS})
base = pd.concat({"A": A_lv, "KR": EN_kr, "US": EN_us, "USH": EN_ush, "KOSPI": K_lv}, axis=1).dropna()
dd_days = (base.index - base.index[0]).days.values
base["CASH"] = (1 + CASH_RATE) ** (dd_days / 365.25)
base["CASH0"] = 1.0

S = pd.DataFrame({
    "지수 A": base["A"],
    "B20 (A80 + 국내 에너지20)": quarter_reset(base[["A", "KR"]], {"A": .8, "KR": .2}),
    "A80 + 현금20 (연 3%)": quarter_reset(base[["A", "CASH"]], {"A": .8, "CASH": .2}),
    "A80 + 현금20 (연 0%)": quarter_reset(base[["A", "CASH0"]], {"A": .8, "CASH0": .2}),
    "A80 + 미국 석유20 (환노출)": quarter_reset(base[["A", "US"]], {"A": .8, "US": .2}),
    "A80 + 미국 석유20 (환헤지)": quarter_reset(base[["A", "USH"]], {"A": .8, "USH": .2}),
    "A80 + 국내10 + 미국10": quarter_reset(base[["A", "KR", "US"]], {"A": .8, "KR": .1, "US": .1}),
    "KOSPI": base["KOSPI"],
})
S = S / S.iloc[0] * 1000
print("기간:", S.index[0].date(), "~", S.index[-1].date(), len(S), "거래일")


def stats(s, a):
    r, ra = s.pct_change().dropna(), a.pct_change().dropna()
    n = (s.index[-1] - s.index[0]).days / 365.25
    tot = s.iloc[-1] / s.iloc[0] - 1
    cagr = (1 + tot) ** (1 / n) - 1
    vol = r.std() * np.sqrt(252)
    down = ra < 0
    return dict(cagr=cagr, vol=vol, mdd=(s / s.cummax() - 1).min(), rv=cagr / vol,
                dc=r[down].mean() / ra[down].mean(), te=(r - ra).std() * np.sqrt(252))


ST = {k: stats(S[k], S["지수 A"]) for k in S.columns}
S1 = S[S.index >= S.index[-1] - pd.DateOffset(years=1)]
ST1 = {k: stats(S1[k], S1["지수 A"]) for k in S.columns}
a = S["지수 A"]
trough = (a / a.cummax() - 1).idxmin()
peak = a.loc[:trough].idxmax()
win = {k: S[k].loc[trough] / S[k].loc[peak] - 1 for k in S.columns}
leg = {"국내 에너지 3종목": base["KR"], "미국 석유(원화)": base["US"], "미국 석유(달러)": base["USH"]}
leg_w = {k: v.loc[trough] / v.loc[peak] - 1 for k, v in leg.items()}
fx_w = fx_on_kr.loc[trough] / fx_on_kr.loc[peak] - 1
R = base[["A", "KR", "US", "USH"]].pct_change().dropna()
corr_kr, corr_us = R["A"].corr(R["KR"]), R["A"].corr(R["US"])
corr_fx_us = R["US"].corr(fx_on_kr.reindex(R.index).pct_change())

#%% 2. 그림
COL = {"지수 A": "#9aa3b5", "B20 (A80 + 국내 에너지20)": "#2f5bd3", "A80 + 현금20 (연 3%)": "#c2410c",
       "A80 + 미국 석유20 (환노출)": "#0f9d58", "KOSPI": "#d0d5df"}
fig, ax = plt.subplots(figsize=(8, 3.2), dpi=200)
for k, c in COL.items():
    ax.plot(S.index, S[k], color=c, lw=1.6 if "B20" in k else 1.1, label=k)
ax.axvspan(peak, trough, color="#fde68a", alpha=.35, lw=0)
ax.set_ylabel("지수 (2022-04-04 = 1,000)", fontsize=8); ax.tick_params(labelsize=7.5)
ax.legend(fontsize=7, frameon=False, ncol=2, loc="upper left")
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
plt.tight_layout(); FIG1 = os.path.join(OUT, "fig_levels.png"); plt.savefig(FIG1); plt.close()

keys = ["지수 A", "A80 + 현금20 (연 3%)", "A80 + 미국 석유20 (환노출)", "A80 + 국내10 + 미국10",
        "A80 + 미국 석유20 (환헤지)", "B20 (A80 + 국내 에너지20)"]
fig, ax = plt.subplots(figsize=(8, 2.6), dpi=200)
vals = [win[k] * 100 for k in keys]
bars = ax.barh(range(len(keys)), vals, color=["#9aa3b5", "#c2410c", "#0f9d58", "#7fb89a", "#0b6b3c", "#2f5bd3"])
ax.set_yticks(range(len(keys))); ax.set_yticklabels(keys, fontsize=7.5)
for b, v in zip(bars, vals):
    ax.text(v + 0.8, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", ha="left", fontsize=7.5, color="white", fontweight="bold")
ax.set_xlim(-50, 0); ax.tick_params(axis="x", labelsize=7.5)
for s in ["top", "right"]:
    ax.spines[s].set_visible(False)
plt.tight_layout(); FIG2 = os.path.join(OUT, "fig_drawdown_window.png"); plt.savefig(FIG2); plt.close()

#%% 3. 보고서
P = lambda x: f"{x * 100:.1f}%"
SP = lambda x: f"{x * 100:+.1f}%"
B, C3, UO, UH, MX = ("B20 (A80 + 국내 에너지20)", "A80 + 현금20 (연 3%)", "A80 + 미국 석유20 (환노출)",
                     "A80 + 미국 석유20 (환헤지)", "A80 + 국내10 + 미국10")

d = Doc("B20 헤지 자산 대안 비교", running="ETF SOLUTION LAB · B20 ADDITIONAL TEST · 2026-10")
d.hero("ETF PRODUCT · 추가 검증",
       "에너지 20% 대신 현금이나 미국 석유주라면?",
       "B20(지수 A 80% + 국내 에너지주 20%)의 헤지 자산을 바꿔 같은 조건으로 비교",
       ["기간 2022-04-04 ~ 2026-10-16", "분기 리셋 · 가격지수", "B20 보고서와 같은 데이터", "작성 송호빈"])
d.kpis([(P(ST[B]["mdd"]), "B20 최대 낙폭"), (P(ST[C3]["mdd"]), "현금 20% 최대 낙폭"),
        (P(ST[UO]["mdd"]), "미국 석유 20% 최대 낙폭 (환노출)"), (SP(fx_w), "낙폭 구간 원/달러 변화")])

d.sec("요약")
d.ul([
    f"B20은 수익을 높이는 상품이 아니라 **지수 A의 큰 낙폭을 줄이는 상품**이다. 그렇다면 \"현금 20%로도 되지 않나\"와 \"해외 에너지 대형주가 낫지 않나\"를 확인해야 한다.",
    f"**현금 20%**: 평소 변동성은 가장 낮다({P(ST[C3]['vol'])}). 그러나 지수 A가 {P(win['지수 A'])} 빠진 구간에서 {P(win[C3])}로, B20({P(win[B])})보다 덜 막았다. 연수익도 {P(ST[C3]['cagr'])}로 B20({P(ST[B]['cagr'])})보다 낮다.",
    f"**미국 석유 메이저(XOM·CVX) 20%**: 지수 A와 상관이 {corr_us:.2f}로 거의 없어 평소 위험 대비 수익은 가장 좋다({ST[UO]['rv']:.2f}). 그러나 낙폭 구간에 원/달러가 {SP(fx_w)} 움직여(원화 강세) 원화 기준 방어가 약해졌다({P(win[UO])}).",
    "결론: **큰 하락을 막는다는 B20의 목적에는 국내 에너지가 가장 맞다.** 미국 석유주는 유동성이 좋지만 세제·괴리율·환율 문제가 더해진다.",
])

d.sec("왜 검증했나")
d.p("B20 보고서는 지수 A(국내 AI·반도체·전력 10종목)에 국내 에너지주 3종목(S-Oil, SK이노베이션, 한국가스공사)을 20% 섞어 "
    "최대 낙폭을 줄였다. 그런데 비교 대상이 지수 A 100%뿐이었다. 지수 A 비중을 80%로 낮추기만 해도 낙폭은 줄어든다. "
    "그래서 **같은 20%를 다른 자산에 넣었을 때**와 비교해야 에너지를 넣은 이유가 선다.")
d.table([["질문", "비교안", "확인할 것"],
         ["에너지 대신 현금이면?", "A 80% + 현금 20% (연 0%·3%)", "낙폭이 비슷하게 줄면 에너지의 의미가 약하다"],
         ["국내 대신 해외 에너지 대형주면?", "A 80% + XOM·CVX 20% (환노출·환헤지)", "유동성 문제(가스공사)를 풀면서 방어도 되는가"],
         ["둘을 섞으면?", "A 80% + 국내 10% + 미국 10%", "중간 해법이 있는가"]],
        widths=[26, 36, 38])

d.sec("방법")
d.table([["항목", "내용"],
         ["기간", "2022-04-04 ~ 2026-10-16 (B20 보고서와 같음, 1,109 거래일)"],
         ["지수 A", "stock_db idx_level, variant E_quota_buffer (B20 보고서와 같은 값)"],
         ["결합 규칙", "분기 첫 거래일에 목표 비중으로 리셋, 분기 중에는 비중이 흘러감 (B20과 같음)"],
         ["국내 에너지", "S-Oil·SK이노베이션·한국가스공사 동일가중, 분기 리셋, kor_price 종가"],
         ["미국 석유", "엑슨모빌(XOM)·셰브론(CVX) 동일가중, us_price 종가(배당 제외). 미국 종가는 한국 장 뒤에 나오므로 다음 한국 거래일에 반영"],
         ["환율", "USD/KRW (tv_futures_price). 환노출 = 원화 환산, 환헤지 = 달러 수익률 그대로(헤지 비용 미반영)"],
         ["현금", "연 3%와 0% 두 가지 가정 (실제 금리 시계열 아님)"],
         ["공통", "가격지수(배당 제외), 보수·거래비용·세금 미반영"]],
        widths=[16, 84])
d.box("note", "B20 숫자", f"이 보고서의 B20 값(연 {P(ST[B]['cagr'])}, 변동성 {P(ST[B]['vol'])}, 최대 낙폭 {P(ST[B]['mdd'])})은 "
      "B20 보고서 5장의 재구성 값과 같다. 4장 Day 4 백테스트 값(28.7%, 33.5%, -37.5%)과의 차이는 B20 보고서에 원인 미확인으로 적혀 있다. "
      "모든 비교안을 같은 방식으로 계산해야 하므로 여기서는 재구성 방식을 쓴다.")

d.sec("결과", "전체 기간", page_break=True)
order = ["지수 A", B, C3, "A80 + 현금20 (연 0%)", UO, UH, MX, "KOSPI"]
rows = [["안", "연수익", "변동성", "최대 낙폭", "수익/변동성", "하락일 참여율"]]
for k in order:
    s = ST[k]
    rows.append([k, P(s["cagr"]), P(s["vol"]), P(s["mdd"]), f"{s['rv']:.2f}", f"{s['dc']:.2f}"])
d.table(rows, align="lrrrrr", hl=(1,), widths=[34, 12, 12, 13, 14, 15])
d.p("하락일 참여율 = 지수 A가 떨어진 날 각 안의 평균 수익률 ÷ 지수 A의 평균 수익률. 낮을수록 평소 하락을 덜 탄다.")
d.img(FIG1, "그림 1. 누적 지수 (2022-04-04 = 1,000). 노란 구간은 지수 A 최대 낙폭 구간", 96)
d.h3("최근 1년 (2025-10-16 ~ 2026-10-16)")
rows = [["안", "연수익", "변동성", "최대 낙폭", "수익/변동성"]]
for k in ["지수 A", B, C3, UO, UH]:
    s = ST1[k]
    rows.append([k, P(s["cagr"]), P(s["vol"]), P(s["mdd"]), f"{s['rv']:.2f}"])
d.table(rows, align="lrrrr", hl=(1,), widths=[40, 15, 15, 15, 15])

d.sec("큰 하락 구간에서 무엇이 버텼나", f"{peak.date()} ~ {trough.date()}")
d.img(FIG2, f"그림 2. 지수 A 최대 낙폭 구간({peak.date()} ~ {trough.date()})의 각 안 수익률", 92)
d.table([["헤지 자산 (단독)", "같은 구간 수익률"],
         *[[k, SP(v)] for k, v in leg_w.items()],
         ["원/달러 환율", SP(fx_w)]], align="lr", widths=[60, 40])
d.ul([
    f"현금은 낙폭을 정확히 비중만큼만 줄인다. 국내 에너지는 같은 구간에 **{SP(leg_w['국내 에너지 3종목'])}** 올라서 그 이상을 막았다.",
    f"미국 석유도 달러 기준으로는 {SP(leg_w['미국 석유(달러)'])} 올랐다. 그러나 원/달러가 {SP(fx_w)} 움직여 원화 기준으로는 {SP(leg_w['미국 석유(원화)'])}에 그쳤다.",
    f"일간 상관: 지수 A와 국내 에너지 {corr_kr:.2f}, 지수 A와 미국 석유 {corr_us:.2f}. 미국 석유(원화)와 환율 {corr_fx_us:.2f}. "
    "평소엔 미국 석유가 더 분산되지만, 위기 때는 **환율이 헤지 효과를 깎는다**.",
])

d.sec("상품으로 만들 때")
d.table([["점검 항목", "국내 에너지 (B20)", "미국 석유 메이저"],
         ["유동성", "한국가스공사가 병목. 500억 규모에서 정리 3.02일 (B20 보고서 7장)", "거래대금이 매우 커서 병목이 사라짐 (거래대금 수치 확인 필요)"],
         ["세제", "국내주식형 유지", "해외주식 편입 시 국내주식형 분류가 유지되는지 확인 필요"],
         ["NAV·괴리율", "한국 장중 실시간 가격으로 LP 헤지", "미국 장이 닫혀 있어 장중 iNAV 추정. LP 헤지가 어려워 괴리율 확대 가능"],
         ["환율", "없음", "환노출: 위기 때 원화 강세로 방어 약화 / 환헤지: 헤지 비용"],
         ["목적 적합성", "큰 하락 방어가 가장 큼", "평소 분산은 좋지만 큰 하락 방어는 약함"]],
        widths=[16, 40, 44])
d.box("key", "결론", "B20의 목적(AI 업황이 꺾일 때 낙폭 축소)에는 국내 에너지가 맞다. 가스공사 유동성 문제는 해외로 바꾸기보다 "
      "**유동성 캡(종목 비중 ≤ 하루 거래대금 × 참여율 ÷ 운용 규모)** 이나 국내 대체 종목으로 푸는 것이 낫다.")

d.sec("한계와 다음 검증")
d.ul([
    "표본 4년 반 안에 큰 하락이 사실상 한 번이다. **2022년 하반기 반도체 하락기만 떼어** 같은 비교를 다시 한다.",
    "현금은 고정 금리 가정이다. CD91 금리 시계열(stock_db cd91_rate)로 바꿔 다시 계산한다.",
    "환헤지 비용(한미 금리차)을 반영하면 환헤지안의 수익이 낮아진다.",
    "가스공사를 유동성 캡으로 묶거나 다른 종목으로 바꾸면 헤지 효과가 달라지므로 백테스트를 다시 돌린다.",
])
d.foot("자료: stock_db (idx_level, kor_price, us_price, tv_futures_price, fdr_kr_ticker). 학습·포트폴리오 목적이며 실제 상품이나 투자 권유가 아니다. "
       "코드: B20_vs_현금20_비교.py, B20_미국석유주_비교.py, make_b20_hedge_report.py")

pdf = d.save(os.path.join(OUT, "B20_헤지자산_대안비교.pdf"))
pd.DataFrame(ST).T.to_csv(os.path.join(OUT, "B20_헤지대안_지표_전체.csv"), encoding="utf-8-sig")
print("저장:", pdf, "+ .docx")
