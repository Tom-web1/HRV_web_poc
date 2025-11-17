# app.py
from flask import Flask, render_template, request, make_response
from weasyprint import HTML

from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

# ====== 暫存最近一次分析結果，給 /export_pdf 用 ======
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

        # 暫存供 /export_pdf 使用
        last_row = row
        last_quad_img_b64 = quad_img_b64
        last_advice = advice

        # 直接顯示 HTML 報告頁
        return render_template(
            "report.html",
            row=row,
            quad_img_b64=quad_img_b64,
            advice=advice,
        )

    # GET：顯示首頁上傳頁
    return render_template("index.html")


@app.route("/export_pdf")
def export_pdf():
    """
    使用 WeasyPrint 將同一份 report.html 渲染成 PDF，並提供下載。
    必須先在首頁完成一次分析，才有 last_row 可以用。
    """
    if last_row is None:
        return "請先完成一次 HRV 分析，再下載 PDF 報告。", 400

    # 用和畫面相同的模板產生 HTML 字串
    html_str = render_template(
        "report.html",
        row=last_row,
        quad_img_b64=last_quad_img_b64,
        advice=last_advice,
    )

    # WeasyPrint 轉 PDF；base_url 讓它找得到 /static 裡的字型與 CSS
    pdf_bytes = HTML(
        string=html_str,
        base_url=request.url_root
    ).write_pdf()

    # 檔名：HRV_REPORT_<Name>.pdf
    name = last_row.get("Name") or "Unknown"
    filename = f"HRV_REPORT_{name}.pdf"

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


if __name__ == "__main__":
    # 本機開發用；在 Render 上會用 gunicorn 啟動
    app.run(debug=True)


