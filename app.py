# app.py
import io
import base64

from flask import Flask, render_template, request, send_file
import matplotlib
matplotlib.use("Agg")  # 伺服器環境用無頭 backend
import matplotlib.pyplot as plt

from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
    _get_font_prop,   # 拿同一套中文字型來畫 JPG 報告
)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

# ====== 暫存最近一次分析結果，給 /export_jpg 用 ======
last_row = None
last_quad_img_b64 = None
last_advice = None


@app.route("/health")
def health():
    """給 Render 或監控用的健康檢查端點。"""
    return "OK", 200


@app.route("/", methods=["GET", "POST"])
def index():
    global last_row, last_quad_img_b64, last_advice

    if request.method == "POST":
        xml_file = request.files.get("xml_file")
        xml_text = request.form.get("xml_text", "").strip()

        # 使用者沒有提供任何東西
        if not xml_file and not xml_text:
            return render_template("index.html", error="請上傳 XML 檔案或貼上 XML 內容。")

        # 若有上傳檔案，優先採用檔案內容
        if xml_file:
            xml_bytes = xml_file.read()
            xml_text = xml_bytes.decode("utf-8", errors="ignore")

        # 解析 XML → HRV 指標 row
        try:
            row = parse_hrv_xml_to_row(xml_text)
        except Exception as e:
            return render_template("index.html", error=f"XML 解析失敗：{e}")

        # 四象限圖（base64）與體質建議
        quad_img_b64 = generate_quadrant_plot_base64(row)
        advice = get_constitution_advice(row.get("Constitution", ""))

        # 暫存供 /export_jpg 使用
        last_row = row
        last_quad_img_b64 = quad_img_b64
        last_advice = advice

        # ⭐ 前端網頁版：沿用你原本的 report.html（含 Bootstrap）
        return render_template(
            "report.html",
            row=row,
            quad_img_b64=quad_img_b64,
            advice=advice,
        )

    # GET：顯示首頁上傳頁
    return render_template("index.html")


def _generate_report_jpg(row: dict, quad_img_b64: str, advice: str) -> bytes:
    """
    把單一受測者的 HRV 報告畫成一張 JPG 圖檔（A4 比例）。
    回傳：JPG 的二進位 bytes。
    """
    # A4 約 8.27 x 11.69 英吋，這邊用 8 x 11.3，dpi=150
    fig = plt.figure(figsize=(8, 11.3), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    font_prop = _get_font_prop()

    # ===== 標題 =====
    fig.text(
        0.5, 0.96,
        "HRV 自律神經體質分析報告",
        ha="center", va="center",
        fontsize=18,
        fontproperties=font_prop
    )

    # ===== 一、基本資料 =====
    y = 0.90
    line_h = 0.03

    fig.text(0.05, y, "一、基本資料", ha="left", va="center",
             fontsize=12, fontproperties=font_prop)
    y -= line_h

    name = row.get("Name", "")
    sex = row.get("Sex", "")
    age = row.get("Age", "")
    test_date = row.get("TestDate", "")

    fig.text(0.07, y, f"姓名：{name}", ha="left", va="center",
             fontsize=10, fontproperties=font_prop)
    fig.text(0.35, y, f"性別：{sex}", ha="left", va="center",
             fontsize=10, fontproperties=font_prop)
    fig.text(0.55, y, f"年齡：{age}", ha="left", va="center",
             fontsize=10, fontproperties=font_prop)
    fig.text(0.75, y, f"測量日期：{test_date}", ha="left", va="center",
             fontsize=10, fontproperties=font_prop)
    y -= line_h * 1.4

    # ===== 二、HRV 指標摘要 =====
    fig.text(0.05, y, "二、HRV 指標摘要", ha="left", va="center",
             fontsize=12, fontproperties=font_prop)
    y -= line_h * 1.1

    # 簡易表格：HR / SD / RV / TP / LF / HF / ln(LF/HF) / ln(TP) / TP_Q
    cols = ["HR", "SD", "RV", "TP", "LF", "HF", "ln_LF_HF", "ln_TP", "TP_Q"]
    col_labels = [
        "HR", "SD", "RV", "TP", "LF", "HF",
        "ln(LF/HF)", "ln(TP)", "TP_Q"
    ]
    values = [row.get(c, "") for c in cols]

    table_data = [col_labels, [str(v) for v in values]]

    table_ax = fig.add_axes([0.05, y - 0.16, 0.90, 0.14])
    table_ax.axis("off")
    table = table_ax.table(
        cellText=table_data,
        colLabels=None,
        loc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)

    # 標頭灰底
    for j in range(len(col_labels)):
        cell = table[(0, j)]
        cell.set_facecolor("#eeeeee")

    # 調整每欄寬
    n_cols = len(col_labels)
    for j in range(n_cols):
        table.auto_set_column_width(j)

    y -= 0.20

    # ===== 三、體質判讀 =====
    fig.text(0.05, y, "三、體質判讀（陰陽虛實）", ha="left", va="center",
             fontsize=12, fontproperties=font_prop)
    y -= line_h

    constitution = row.get("Constitution", "")
    fig.text(
        0.07, y,
        f"體質分類：{constitution}",
        ha="left", va="center",
        fontsize=11, color="#c0392b",
        fontproperties=font_prop,
    )
    y -= line_h * 0.8

    # 建議文字（自動換行，粗略處理）
    wrapped = []
    max_chars = 25  # 每行 25 個中文左右
    for line in (advice or "").split("\n"):
        line = line.strip()
        if not line:
            wrapped.append("")
            continue
        while len(line) > max_chars:
            wrapped.append(line[:max_chars])
            line = line[max_chars:]
        if line:
            wrapped.append(line)

    for line in wrapped:
        fig.text(
            0.07, y,
            line,
            ha="left", va="top",
            fontsize=9,
            fontproperties=font_prop
        )
        y -= 0.018
        if y < 0.40:  # 避免蓋到圖
            break

    # ===== 四、ln(LF/HF) × ln(TP) 四象限圖 =====
    fig.text(0.05, 0.38, "四、ln(LF/HF) × ln(TP) 四象限圖",
             ha="left", va="center",
             fontsize=12, fontproperties=font_prop)

    fig.text(
        0.05, 0.35,
        "X 軸：ln(TP)（虛 → 實） · Y 軸：ln(LF/HF)（陰 → 陽）\n"
        "綠色區域為根據 Kuo(1999) 設定之年齡 × 性別健康參考範圍。",
        ha="left", va="top",
        fontsize=8,
        fontproperties=font_prop,
    )

    # 把原本 base64 的四象限圖嵌進來
    try:
        img_bytes = base64.b64decode(quad_img_b64)
        img_buf = io.BytesIO(img_bytes)
        quad_img = plt.imread(img_buf, format="png")

        img_ax = fig.add_axes([0.10, 0.05, 0.80, 0.26])
        img_ax.imshow(quad_img)
        img_ax.axis("off")
    except Exception:
        # 萬一讀圖失敗，就忽略
        pass

    # ===== 輸出成 JPG bytes =====
    out_buf = io.BytesIO()
    fig.savefig(out_buf, format="jpeg", dpi=150, bbox_inches="tight")
    plt.close(fig)
    out_buf.seek(0)
    return out_buf.read()


@app.route("/export_jpg")
def export_jpg():
    """
    把最近一次分析結果，輸出成一張 JPG 報告圖。
    """
    if last_row is None:
        return "請先完成一次 HRV 分析，再下載 JPG 報告。", 400

    jpg_bytes = _generate_report_jpg(last_row, last_quad_img_b64, last_advice)

    name = last_row.get("Name") or "Unknown"
    filename = f"HRV_REPORT_{name}.jpg"

    buf = io.BytesIO(jpg_bytes)
    buf.seek(0)

    # Flask 3.x 的 send_file + download_name 會自動處理 Unicode 檔名
    return send_file(
        buf,
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=filename
    )


if __name__ == "__main__":
    # 本機開發用；在 Render 上會用 gunicorn 啟動
    app.run(debug=True)
