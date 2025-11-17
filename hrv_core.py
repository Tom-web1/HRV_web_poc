# hrv_core.py
# HRV XML 解析 + 陰陽虛實體質判讀 + 四象限圖（含 Kuo(1999) TP 基準 Healthy Zone）
# + BMI / ANS Age / ANS Age Diff 判讀整合版
# + 體質說明 HTML + Healthy Zone 距離 D′ + 整體解讀

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
import matplotlib.patches as patches


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


# ========= 年齡 × 性別 TP 基準（Kuo 1999） =========
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
    x = safe_float(x)
    if x <= 0:
        return float("nan")
    return math.log(x)


# ========= TP 參考基準 =========
def get_tp_mu_sigma(age, sex):
    sex = (sex or "").strip()
    if sex not in TP_BASE:
        sex = "男"

    for max_age, mu, sigma in TP_BASE[sex]:
        if age <= max_age:
            return mu, sigma

    # 理論上不會走到這裡
    return 6.0, 0.5


# ========= Healthy Zone =========
def get_healthy_zone(age, sex):
    """
    回傳：lnTP_min, lnTP_max, lnLFHF_min, lnLFHF_max
    X 軸：lnTP 在 (μ ± 1σ)
    Y 軸：ln(LF/HF) 在 (-0.5, 0.5)
    """
    mu_lnTP, sigma_lnTP = get_tp_mu_sigma(age, sex)
    return (
        mu_lnTP - sigma_lnTP,
        mu_lnTP + sigma_lnTP,
        -0.5,
        0.5,
    )


def compute_healthy_distance(ln_tp, ln_ratio, age, sex):
    """
    計算相對 Healthy Zone 中心的加權距離 D′：
    - X 軸：lnTP 以 μ, σ 標準化 → z_tp
    - Y 軸：ln(LF/HF) 以 0 為中心，0.5 為一個單位 → z_ratio
    D′ = sqrt(z_tp^2 + z_ratio^2)
    數值越小代表越接近「健康基準區」。
    """
    if math.isnan(ln_tp) or math.isnan(ln_ratio):
        return float("nan")

    mu, sigma = get_tp_mu_sigma(age, sex)
    if sigma <= 0:
        return float("nan")

    z_tp = (ln_tp - mu) / sigma
    # 以 0 為中心，0.5 為一個單位（大約是你原本設定的 Health Zone 高度）
    z_ratio = ln_ratio / 0.5 if 0.5 != 0 else float("nan")

    if math.isnan(z_ratio):
        return float("nan")

    return round(math.sqrt(z_tp**2 + z_ratio**2), 2)


# ========= XML 清理 =========
def _extract_patient_xml(xml_text):
    s = (xml_text or "").strip()
    if not s:
        return ""

    # 已含有 <Patient ... /> 或 <Patient> ... </Patient>
    if "<Patient" in s:
        m = re.search(r"<Patient\b[^>]*\/>", s)
        if m:
            return m.group(0)
        return s

    # 有些機器輸出是 "Patient Name=..."
    if s.startswith("Patient "):
        return "<" + s

    return s


# ========= 陰陽虛實分類 =========
def classify_constitution(ln_tp, ln_ratio):
    """
    X 軸：ln(TP)（虛 ←→ 實）
    Y 軸：ln(LF/HF)（陰 ←→ 陽）

    四象限：
      右上：陽實型（lnTP 高 & lnLF/HF > 0）
      右下：陽虛型（lnTP 低 & lnLF/HF > 0）
      左上：陰實型（lnTP 高 & lnLF/HF < 0）
      左下：陰虛型（lnTP 低 & lnLF/HF < 0）
    """
    if math.isnan(ln_tp) or math.isnan(ln_ratio):
        return "資料不足"

    # 門檻值可之後依你實務經驗再微調
    if ln_tp >= 6 and ln_ratio >= 0:
        return "陽實型"
    if ln_tp < 6 and ln_ratio >= 0:
        return "陽虛型"
    if ln_tp >= 6 and ln_ratio < 0:
        return "陰實型"
    return "陰虛型"


# ========= 體質建議（短版，純文字給報告用） =========
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


# ========= 體質說明 HTML（給前端直接塞進模板的「核心解釋」） =========
def get_constitution_explain_html():
    """
    回傳一段固定的 HTML 說明，保留你之前 v1.4 那種「有靈魂」的描述。
    """
    return """
<h3>📝 體質說明</h3>
<ul style="margin:8px 0 0 18px; line-height:1.6">
  <li><b>陽實型</b>（右上）：TP 高、ln(LF/HF) > 0 ⇒ 交感旺、能量充足。<br>
      表現：亢奮、易怒、睡淺、血壓偏高、肩頸緊繃。<br>
      建議：放鬆訓練、調息降火、減少熬夜與過度刺激。</li>
  <li><b>陽虛型</b>（右下）：TP 低、ln(LF/HF) > 0 ⇒ 交感主導但能量不足。<br>
      表現：畏寒、手足冰冷、容易疲勞、下午精神下滑。<br>
      建議：補氣助陽、規律運動、白天光照、充足睡眠。</li>
  <li><b>陰實型</b>（左上）：TP 高、ln(LF/HF) &lt; 0 ⇒ 副交感偏強、代謝遲緩。<br>
      表現：水腫、體重易上升、餐後愛睏、代謝指標偏高。<br>
      建議：調整飲食結構、增加日間活動量與心肺運動。</li>
  <li><b>陰虛型</b>（左下）：TP 低、ln(LF/HF) &lt; 0 ⇒ 能量與修復都偏低。<br>
      表現：睡眠品質差、易心悸焦慮、恢復力差、容易覺得虛弱。<br>
      建議：優先修復睡眠、建立規律作息、以溫和運動循序進步。</li>
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
    height = safe_float(attr.get("Height", 0))
    weight = safe_float(attr.get("Weight", 0))
    age = safe_int(attr.get("Age", 0))
    test_date = attr.get("TestDate", "")

    hr = safe_int(attr.get("HR", 0))
    sd = safe_float(attr.get("SD", 0))
    rv = safe_float(attr.get("RV", 0))
    er = safe_int(attr.get("ER", 0))
    n = safe_int(attr.get("N", 0))

    tp = safe_float(attr.get("TP", 0))
    vl = safe_float(attr.get("VL", 0))
    lf = safe_float(attr.get("LF", 0))
    hf = safe_float(attr.get("HF", 0))
    nn = safe_int(attr.get("NN", 0))
    balance = safe_float(attr.get("Balance", 0))

    # --- ln values ---
    ln_tp = safe_ln(tp)
    ln_ratio = safe_ln(lf / hf) if hf > 0 else float("nan")

    # --- TP_Q (能量效率) ---
    mu, sigma = get_tp_mu_sigma(age, sex)
    tp_q = (ln_tp - mu) / sigma if sigma > 0 and not math.isnan(ln_tp) else float("nan")

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
    constitution = classify_constitution(ln_tp, ln_ratio)

    # --- Healthy Zone 距離 ---
    d_prime = compute_healthy_distance(ln_tp, ln_ratio, age, sex)

    # --- 組裝 row ---
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
        "TP_Q": round(tp_q, 2) if not math.isnan(tp_q) else float("nan"),

        "Constitution": constitution,

        "BMI": round(bmi, 2) if not math.isnan(bmi) else float("nan"),
        "BMI_Status": bmi_status,
        "ANS_Age": ans_age,
        "ANS_Age_Diff": ans_age_diff,

        "Healthy_Dprime": d_prime,
    }

    return row


# ========= 整體解讀（給報告用的一段 summary） =========
def build_overall_summary(row):
    """
    輸出一段中文 summary，可以直接丟到 HTML 模板中顯示。
    """
    name = str(row.get("Name", "")).strip() or "受測者"
    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", "") or "")
    constitution = str(row.get("Constitution", "") or "資料不足")

    ln_tp = safe_float(row.get("ln_TP"))
    ln_ratio = safe_float(row.get("ln_LF_HF"))
    tp_q = row.get("TP_Q")
    bmi = row.get("BMI")
    bmi_status = row.get("BMI_Status", "")
    ans_age = row.get("ANS_Age")
    ans_age_diff = row.get("ANS_Age_Diff")
    d_prime = row.get("Healthy_Dprime")

    parts = []

    # 基本資訊
    parts.append(f"{name}（{sex}，約 {age} 歲）本次自律神經量測結果如下：")

    # 體質類型
    parts.append(f"依據 ln(TP) 與 ln(LF/HF) 座標判定，目前傾向於「{constitution}」。")

    # 能量效率 TP_Q
    if not (tp_q is None or math.isnan(tp_q)):
        if abs(tp_q) < 1:
            desc = "接近年齡與性別的平均能量水準"
        elif tp_q > 0:
            desc = "整體能量較同齡族群偏高"
        else:
            desc = "整體能量較同齡族群偏低"
        parts.append(
            f"ln(TP) 相對 Kuo(1999) 基準的 z 值（TP_Q）約為 {tp_q}，大致顯示{desc}。"
        )

    # Healthy Zone 距離
    if not (d_prime is None or math.isnan(d_prime)):
        if d_prime < 1:
            dist_desc = "非常接近"
        elif d_prime < 2:
            dist_desc = "略偏離"
        else:
            dist_desc = "明顯偏離"

        parts.append(
            f"相對『Healthy Zone』中心的加權距離 D′ 約為 {d_prime}，代表目前狀態{dist_desc}健康基準區。"
        )

    # BMI
    if not (bmi is None or math.isnan(bmi)):
        parts.append(f"BMI 約為 {bmi}（{bmi_status}）。")

    # ANS Age
    if not (ans_age is None or math.isnan(ans_age)):
        if ans_age_diff is None or math.isnan(ans_age_diff):
            parts.append(f"ANS 年齡推估約為 {ans_age} 歲。")
        else:
            if ans_age_diff > 0:
                diff_desc = f"約大 {abs(ans_age_diff)} 歲"
                direction = "自律神經負擔偏高或恢復不足"
            elif ans_age_diff < 0:
                diff_desc = f"約小 {abs(ans_age_diff)} 歲"
                direction = "自律神經彈性較佳"
            else:
                diff_desc = "與實際年齡相近"
                direction = "整體負荷與年齡匹配"

            parts.append(
                f"ANS 年齡約為 {ans_age} 歲，與實際年齡相比 {diff_desc}，"
                f"顯示{direction}。"
            )

    return " ".join(parts)


# ========= 四象限圖 =========
def generate_quadrant_plot_base64(row):
    x = safe_float(row.get("ln_TP"))
    y = safe_float(row.get("ln_LF_HF"))

    age = safe_int(row.get("Age", 0))
    sex = str(row.get("Sex", ""))

    font_prop = _get_font_prop()

    plt.figure(figsize=(5, 5), dpi=120)
    ax = plt.gca()

    # --- 分界線（虛實 & 陰陽）---
    ax.axvline(6.0, color="gray", linestyle="--", linewidth=1)
    ax.axhline(0.0, color="gray", linestyle="--", linewidth=1)

    # --- Healthy Zone ---
    hx_min, hx_max, hy_min, hy_max = get_healthy_zone(age, sex)
    rect = patches.Rectangle(
        (hx_min, hy_min),
        hx_max - hx_min,
        hy_max - hy_min,
        edgecolor="green",
        facecolor="green",
        alpha=0.2,
        linewidth=1.2,
    )
    ax.add_patch(rect)
    ax.text(
        (hx_min + hx_max) / 2,
        hy_max + 0.1,
        "Healthy Zone",
        ha="center",
        va="bottom",
        fontproperties=font_prop,
        fontsize=9,
        color="green",
    )

    # --- 測量點 ---
    ax.scatter(x, y, s=80, color="red", zorder=3)
    ax.text(
        x,
        y,
        " 測量點",
        color="red",
        fontproperties=font_prop,
        fontsize=10,
        va="center",
    )

    # --- 四象限標籤 ---
    labels = [
        (6.8, 0.8, "陽實型"),
        (5.2, 0.8, "陽虛型"),
        (5.2, -0.8, "陰虛型"),
        (6.8, -0.8, "陰實型"),
    ]
    for lx, ly, t in labels:
        ax.text(
            lx,
            ly,
            t,
            fontproperties=font_prop,
            alpha=0.7,
            fontsize=9,
        )

    ax.set_xlabel("ln(TP)（虛 → 實）", fontproperties=font_prop)
    ax.set_ylabel("ln(LF/HF)（陰 → 陽）", fontproperties=font_prop)

    ax.grid(alpha=0.3)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("utf-8")
