# hrv_core.py
# HRV XML 解析 + 陰陽虛實體質判讀（依 v4 邏輯）
# 含：Kuo(1999) TP 基準、TP_Q（能量效率）、D′ 加權距離、Healthy Zone 橢圓

import math
import os
import io
import base64
import re
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# ========= 字型設定 =========
_BASE_DIR = os.path.dirname(__file__)

FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Bold.ttf"),
    os.path.join(_BASE_DIR, "static", "NotoSansTC-Black.ttf"),
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/PingFang TC.ttc",
    "C:/Windows/Fonts/msjh.ttc",
]

_FONT_PROP = None

def _get_font_prop():
    global _FONT_PROP
    if _FONT_PROP is not None:
        return _FONT_PROP

    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                _FONT_PROP = fm.FontProperties(fname=path)
                print(f"[Font] Using font: {path}")
                return _FONT_PROP
            except Exception:
                continue

    _FONT_PROP = fm.FontProperties()
    print("[Font] Using default font")
    return _FONT_PROP


# ========= 年齡 × 性別 TP 基準（Kuo 1999, lnTP） =========
TP_BASE = {
    "男": [
        (29, 6.8, 0.5),
        (39, 6.5, 0.5),
        (49, 6.2, 0.6),
        (59, 5.8, 0.6),
        (69, 5.5, 0.7),
        (200, 5.2, 0.7),
    ],
    "女": [
        (29, 6.6, 0.5),
        (39, 6.4, 0.5),
        (49, 6.0, 0.5),
        (59, 5.6, 0.5),
        (69, 5.2, 0.5),
        (200, 4.9, 0.5),
    ],
}

def get_tp_mu_sigma(age, sex):
    """
    回傳 (mu, sigma) 供 lnTP 參考用。
    """
    sex = (sex or "").strip()
    if sex not in TP_BASE:
        sex = "男"

    for max_age, mu, sigma in TP_BASE[sex]:
        if age <= max_age:
            return float(mu), float(sigma)

    # 理論上不會走到這裡
    return 6.0, 0.5


def get_healthy_zone(age, sex):
    """
    保留矩形版 Healthy Zone 邊界（如有其他用途可用）：
    lnTP 在 (μ ± 1σ)，ln(LF/HF) 在 (-0.5, 0.5)
    """
    mu_lnTP, sigma_lnTP = get_tp_mu_sigma(age, sex)
    return (
        mu_lnTP - sigma_lnTP,
        mu_lnTP + sigma_lnTP,
        -0.5,
        0.5,
    )


# ========= 安全工具 =========
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default

def safe_ln(x):
    x = safe_float(x, default=float("nan"))
    if not isinstance(x, (int, float)):
        return float("nan")
    if x <= 0:
        return float("nan")
    return math.log(x)


# ========= TP_Q（能量效率）與 D′（加權距離） =========
def tp_quality(tp, lf, hf, vl):
    """
    v4 定義的 TP_Q（能量效率）：
    TPQ = TP * (LF + HF) / (LF + HF + VL)
    """
    tp = safe_float(tp, default=float("nan"))
    lf = safe_float(lf, default=float("nan"))
    hf = safe_float(hf, default=float("nan"))
    vl = safe_float(vl, default=float("nan"))

    if any(math.isnan(v) for v in (tp, lf, hf, vl)):
        return float("nan")

    denom = lf + hf + vl
    if denom <= 0:
        return float("nan")

    eff = (lf + hf) / denom
    return tp * eff


def compute_weighted_distance(ln_ratio, ln_tpq, age, sex, w1=0.6, w2=0.4):
    """
    D′（加權距離），依 v4：
    - ln_ratio = ln(LF/HF)
    - ln_tpq   = ln(TPQ)
    - mu       = lnTP 年齡基準
    D′ = sqrt( w1 * ln_ratio^2 + w2 * (ln_tpq - mu)^2 )
    """
    mu, _ = get_tp_mu_sigma(age, sex)
    if any(math.isnan(v) for v in (ln_ratio, ln_tpq, mu)):
        return float("nan")

    dx = ln_ratio
    dy = ln_tpq - mu
    return round(math.sqrt(w1 * dx * dx + w2 * dy * dy), 2)


# ========= XML 清理 =========
def _extract_patient_xml(xml_text):
    s = (xml_text or "").strip()
    if not s:
        return ""

    if "<Patient" in s:
        m = re.search(r"<Patient\b[^>]*\/>", s)
        if m:
            return m.group(0)
        return s

    if s.startswith("Patient "):
        return "<" + s

    return s


# ========= 體質分類（依 μ 切虛實） =========
def classify_constitution(ln_tp, ln_ratio, sex=None, age=None):
    """
    使用 Kuo(1999) μ 當能量基準：
      lnTP >= μ → 實
      lnTP <  μ → 虛
    搭配 ln(LF/HF) 判斷陰陽：
      ln(LF/HF) >= 0 → 陽
      ln(LF/HF) <  0 → 陰
    """
    if math.isnan(ln_tp) or math.isnan(ln_ratio):
        return "資料不足"

    age = age or 40
    sex = sex or "男"
    mu, _ = get_tp_mu_sigma(age, sex)

    if ln_tp >= mu and ln_ratio >= 0:
        return "陽實型"
    if ln_tp >= mu and ln_ratio < 0:
        return "陰實型"
    if ln_tp < mu and ln_ratio >= 0:
        return "陽虛型"
    return "陰虛型"


# ========= 體質建議（純文字） =========
def get_constitution_advice(c):
    c = (c or "").strip()

    if c == "陽實型":
        return (
            "【陽實型】交感神經偏強、能量偏高，容易處在「火力全開」的狀態。\n"
            "常見：亢奮、易怒、睡眠淺、血壓偏高、肩頸緊繃。\n"
            "建議：安排固定的放鬆練習（呼吸、伸展、正念），"
            "減少熬夜與過度刺激（咖啡、能量飲），留意血壓與三高風險。"
        )

    if c == "陽虛型":
        return (
            "【陽虛型】交感神經主導但能量不足，好比「油門踩著卻沒油」。\n"
            "常見：畏寒、手腳冰冷、容易疲勞、下午提不起勁。\n"
            "建議：規律、溫和的運動（快走、輕重量訓練），"
            "適度補充蛋白質與熱量，白天多接觸自然光，調整作息讓身體有恢復空間。"
        )

    if c == "陰實型":
        return (
            "【陰實型】副交感偏強但能量高，身體偏向「能量堆積但代謝偏慢」。\n"
            "常見：水腫、體重容易上升、餐後愛睏、代謝指標偏高。\n"
            "建議：控制精緻澱粉與晚餐份量，增加日間活動量與心肺運動，"
            "讓堆積的能量被有效利用，改善代謝與體重。"
        )

    if c == "陰虛型":
        return (
            "【陰虛型】副交感與能量都偏低，好比長期「透支」後卻沒有好好充電。\n"
            "常見：睡眠品質差、容易心悸與焦慮、早上起床不易恢復精神。\n"
            "建議：優先修復睡眠（固定就寢時間、睡前放鬆儀式），"
            "避免過度勉強加班與熬夜，循序漸進地增加緩和運動與營養補給。"
        )

    return "資料不足，暫時無法完整判讀體質類型。"


# ========= 體質說明 HTML（你指定的版本） =========
def get_constitution_explain_html():
    """
    回傳一段固定的 HTML 說明（依照 Tom 指定版本，勿改動文字）。
    """
    return """
<ul style="margin:8px 0 0 18px; line-height:1.6">
  <li><b>陽實型</b>（右上）：TP 高、ln(LF/HF) &gt; 0 ⇒ 交感旺、能量充足。表現：亢奮、易怒、睡淺、血壓偏高。建議：放鬆訓練、調息降火、避免過度刺激。</li>
  <li><b>陽虛型</b>（右下）：TP 低、ln(LF/HF) &gt; 0 ⇒ 交感主導但能量不足。表現：畏寒、手足冷、易疲。建議：補氣助陽、規律運動、白天光照。</li>
  <li><b>陰實型</b>（左上）：TP 高、ln(LF/HF) &lt; 0 ⇒ 副交感偏強、代謝遲緩。表現：倦怠、胃納差、濕重。建議：健脾化濕、促循環、晚間早睡。</li>
  <li><b>陰虛型</b>（左下）：TP 低、ln(LF/HF) &lt; 0 ⇒ 陰津不足、虛熱內擾。表現：口乾、盜汗、心煩、失眠。建議：滋陰清熱、節制熬夜與刺激。</li>
  <li><b>Healthy Zone</b>（綠色橢圓）：|ln(LF/HF)| ≤ 0.5 且 ln(TP) 落在年齡均值 μ 附近（±0.5）。距離此區越近，代表「能量適中且陰陽協調」。</li>
</ul>
    """.strip()


# ========= 主解析：parse_hrv_xml_to_row =========
def parse_hrv_xml_to_row(xml_text):
    xml_clean = _extract_patient_xml(xml_text)
    if not xml_clean:
        raise ValueError("XML 內容為空")

    root = ET.fromstring(xml_clean)
    if root.tag != "Patient":
        root = root.find(".//Patient")
        if root is None:
            raise ValueError("找不到 <Patient> 節點")

    attr = root.attrib

    # --- 基本欄位 ---
    name = attr.get("Name", "")
    sex = attr.get("Sex", "")
    pid = attr.get("ID", "")
    height = safe_float(attr.get("Height", 0.0))
    weight = safe_float(attr.get("Weight", 0.0))
    age = safe_int(attr.get("Age", 0))
    test_date = attr.get("TestDate", "")

    hr = safe_int(attr.get("HR", 0))
    sd = safe_float(attr.get("SD", 0.0))
    rv = safe_float(attr.get("RV", 0.0))
    er = safe_int(attr.get("ER", 0))
    n = safe_int(attr.get("N", 0))

    tp = safe_float(attr.get("TP", 0.0))
    vl = safe_float(attr.get("VL", 0.0))
    lf = safe_float(attr.get("LF", 0.0))
    hf = safe_float(attr.get("HF", 0.0))
    nn = safe_int(attr.get("NN", 0))
    balance = safe_float(attr.get("Balance", 0.0))

    # --- ln 值 ---
    ln_tp = safe_ln(tp)
    ln_ratio = safe_ln(lf / hf) if hf > 0 else float("nan")  # ln(LF/HF)

    # --- TP_Q（能量效率）---
    tp_q = tp_quality(tp, lf, hf, vl)
    ln_tpq = safe_ln(tp_q)

    # --- BMI ---
    height_m = height / 100 if height > 5 else height
    bmi = weight / (height_m ** 2) if height_m > 0 else float("nan")

    if bmi < 18.5:
        bmi_status = "體重過輕"
    elif bmi < 23:
        bmi_status = "正常"
    elif bmi < 25:
        bmi_status = "過重（前期）"
    elif bmi < 30:
        bmi_status = "肥胖（中度）"
    else:
        bmi_status = "肥胖（重度）"

    # --- ANS Age ---
    ans_age_min = safe_int(attr.get("ANSAgeMIN", 0))
    ans_age_max = safe_int(attr.get("ANSAgeMAX", 0))

    if ans_age_min > 0 and ans_age_max > 0:
        ans_age = round((ans_age_min + ans_age_max) / 2)
    else:
        ans_age = float("nan")

    # --- ANS Age Diff ---
    ans_age_diff = ans_age - age if not math.isnan(ans_age) else float("nan")

    # --- 體質分類 ---
    constitution = classify_constitution(ln_tp, ln_ratio, sex, age)

    # --- Healthy Zone 距離 D′ ---
    d_prime = compute_weighted_distance(ln_ratio, ln_tpq, age, sex)

    row = {
        "Name": name,
        "Sex": sex,
        "ID": pid,
        "Height": round(height, 2),
        "Weight": round(weight, 2),
        "Age": age,
        "TestDate": test_date,
        "HR": hr,
        "SD": round(sd, 2),
        "RV": round(rv, 2),
        "ER": er,
        "N": n,
        "TP": round(tp, 2),
        "VL": round(vl, 2),
        "LF": round(lf, 2),
        "HF": round(hf, 2),
        "NN": nn,
        "Balance": round(balance, 2),

        "ln_TP": round(ln_tp, 2) if not math.isnan(ln_tp) else float("nan"),
        "ln_LF_HF": round(ln_ratio, 2) if not math.isnan(ln_ratio) else float("nan"),

        # TP_Q 與 lnTPQ
        "TP_Q": round(tp_q, 2) if not math.isnan(tp_q) else float("nan"),
        "ln_TPQ": round(ln_tpq, 2) if not math.isnan(ln_tpq) else float("nan"),

        "Constitution": constitution,

        "BMI": round(bmi, 2) if not math.isnan(bmi) else float("nan"),
        "BMI_Status": bmi_status,
        "ANS_Age": ans_age,
        "ANS_Age_Diff": ans_age_diff,

        "Healthy_Dprime": d_prime,
    }

    return row


# ========= 整體解讀 Summary =========
def build_overall_summary(row):
    """
    用數據講故事：體質 + TP_Q + Healthy Zone 距離 + BMI + ANS Age。
    """
    name = str(row.get("Name", "")).strip() or "受測者"
    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", "") or "")

    constitution = str(row.get("Constitution", "") or "資料不足")

    ln_tp = safe_float(row.get("ln_TP"), default=float("nan"))
    ln_ratio = safe_float(row.get("ln_LF_HF"), default=float("nan"))
    tp_q = row.get("TP_Q")
    ln_tpq = safe_float(row.get("ln_TPQ"), default=float("nan"))
    bmi = row.get("BMI")
    bmi_status = row.get("BMI_Status", "")
    ans_age = row.get("ANS_Age")
    ans_age_diff = row.get("ANS_Age_Diff")
    d_prime = row.get("Healthy_Dprime")

    mu, sigma = get_tp_mu_sigma(age, sex)

    parts = []

    # 基本介紹
    parts.append(f"{name}（{sex}，約 {age} 歲）本次自律神經量測結果如下：")

    # 體質類型
    parts.append(f"依據 ln(TP) 與 ln(LF/HF) 座標判定，目前傾向於「{constitution}」。")

    # 能量效率 TP_Q（使用 lnTPQ 與 μ 來判斷高低）
    if not math.isnan(ln_tpq) and not math.isnan(mu):
        diff = ln_tpq - mu
        if abs(diff) < 0.3:
            desc = "可用能量大致落在同齡族群的平均範圍"
        elif diff > 0:
            desc = "可用能量（TP_Q）明顯高於同齡族群"
        else:
            desc = "可用能量（TP_Q）相對同齡族群偏低"
        parts.append(
            f"以 ln(TPQ) 與年齡基準 μ={mu:.2f} 比較，顯示{desc}。"
        )

    # Healthy Zone 距離 D′
    if d_prime is not None and not math.isnan(d_prime):
        if d_prime < 1:
            dist_desc = "非常接近"
        elif d_prime < 2:
            dist_desc = "略偏離"
        else:
            dist_desc = "明顯偏離"
        parts.append(
            f"相對『Healthy Zone』（|ln(LF/HF)|≤0.5 且 ln(TP)≈μ±0.5）的加權距離 D′ 約為 {d_prime}，"
            f"代表當前狀態{dist_desc}健康基準區。"
        )

    # BMI
    if bmi is not None and not math.isnan(bmi):
        parts.append(f"BMI 約為 {bmi}（{bmi_status}）。")

    # ANS Age
    if ans_age is not None and not math.isnan(ans_age):
        if ans_age_diff is None or math.isnan(ans_age_diff):
            parts.append(f"ANS 年齡推估約為 {ans_age} 歲。")
        else:
            if ans_age_diff > 0:
                diff_desc = f"約大 {abs(ans_age_diff)} 歲"
                direction = "自律神經負擔偏高或恢復不足"
            elif ans_age_diff < 0:
                diff_desc = f"約小 {abs(ans_age_diff)} 歲"
                direction = "自律神經彈性較佳，恢復能力較好"
            else:
                diff_desc = "與實際年齡相近"
                direction = "整體負荷與年齡匹配"
            parts.append(
                f"ANS 年齡約為 {ans_age} 歲，與實際年齡相比 {diff_desc}，顯示{direction}。"
            )

    return " ".join(parts)


# ========= 四象限圖（X=ln(LF/HF), Y=lnTP, 橢圓 Healthy Zone） =========
def generate_quadrant_plot_base64(row):
    # X = ln(LF/HF)；Y = ln(TP)
    x = safe_float(row.get("ln_LF_HF"), default=float("nan"))
    y = safe_float(row.get("ln_TP"), default=float("nan"))

    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", "") or "")

    mu, sigma = get_tp_mu_sigma(age, sex)
    font_prop = _get_font_prop()

    # === 設定安全座標範圍（仿 v4 簡化版） ===
    if not math.isnan(mu):
        y_min, y_max = mu - 2.5, mu + 2.5
    else:
        y_min, y_max = math.log(50), math.log(5000)  # 約 3.9 ~ 8.5

    x_min, x_max = -3.5, 3.5

    if not math.isnan(y):
        if y < y_min: y_min = y - 0.3
        if y > y_max: y_max = y + 0.3
    if not math.isnan(x):
        if x < x_min: x_min = x - 0.3
        if x > x_max: x_max = x + 0.3

    plt.figure(figsize=(5, 5), dpi=120)
    ax = plt.gca()

    # ---- 四象限底色（虛實 × 陰陽）----
    # 上方（實） / 下方（虛），右側（陽）/左側（陰）
    if not math.isnan(mu):
        ax.fill_betweenx([mu, y_max], 0, x_max, color="#FFE5B4", alpha=0.35, zorder=1)  # 右上：陽實
        ax.fill_betweenx([y_min, mu], 0, x_max, color="#BFD7EA", alpha=0.35, zorder=1)  # 右下：陽虛
        ax.fill_betweenx([mu, y_max], x_min, 0, color="#FFB6B9", alpha=0.35, zorder=1)  # 左上：陰實
        ax.fill_betweenx([y_min, mu], x_min, 0, color="#C5D8A4", alpha=0.35, zorder=1)  # 左下：陰虛

    # ---- 軸線 / 基準線 ----
    ax.axvline(0, color="black", lw=0.8, zorder=2)  # 陰 / 陽 分界
    if not math.isnan(mu) and not math.isnan(sigma):
        ax.axhspan(mu - sigma, mu + sigma, color="#9CA3AF", alpha=0.18, zorder=2)
        ax.axhline(mu, color="#6B7280", ls="--", lw=1, zorder=3)

    # ---- Healthy Zone 橢圓 ----
    if not math.isnan(mu):
        theta = [t * math.pi / 180.0 for t in range(0, 361)]
        hx = [0.5 * math.cos(t) for t in theta]       # X 半徑 0.5（lnLF/HF）
        hy = [mu + 0.5 * math.sin(t) for t in theta]  # Y 半徑 0.5（lnTP）
        ax.fill(hx, hy, color="#90EE90", alpha=0.25, zorder=4)
        ax.text(
            0,
            mu + 0.6,
            "Healthy Zone",
            ha="center",
            va="bottom",
            fontproperties=font_prop,
            fontsize=9,
            color="green",
        )

    # ---- 測量點 ----
    ax.scatter(x, y, s=120, color="#e63946", edgecolor="white", linewidth=1.8, zorder=10)
    ax.scatter(x, y, s=50, color="#00FF00", zorder=11)
    ax.text(
        x + 0.1,
        y + 0.1,
        " 測量點",
        color="#1e3a8a",
        fontproperties=font_prop,
        fontsize=10,
        va="center",
        zorder=12,
    )

    # ---- 象限標籤 ----
    labels = [
        (1.5, mu + 1.5, "陽實型"),  # 右上
        (1.5, mu - 1.5, "陽虛型"),  # 右下
        (-1.5, mu - 1.5, "陰虛型"), # 左下
        (-1.5, mu + 1.5, "陰實型"), # 左上
    ]
    for lx, ly, t in labels:
        ax.text(
            lx,
            ly,
            t,
            fontproperties=font_prop,
            alpha=0.8,
            fontsize=9,
        )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_xlabel("ln(LF/HF)（陰 ←→ 陽）", fontproperties=font_prop)
    ax.set_ylabel("ln(TP)（虛 ←→ 實）", fontproperties=font_prop)

    ax.grid(alpha=0.25)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("utf-8")

