from flask import Flask, render_template, request, make_response
from hrv_core import (
    parse_hrv_xml_to_row,
    generate_quadrant_plot_base64,
    get_constitution_advice,
)
from xhtml2pdf import pisa
import io

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates"
)

# 用來暫存最近一次產生的 HTML 報告
latest_pdf_html = None


@app.route("/health")
def health():
    return "OK", 200


@app.route("/", methods=["GET", "POST"])
def index():
    global latest_pdf_html

    if request.method == "POST":
        xml_file = request.files.get("xml_file")
        xml_text = request.form.get("xml_text", "").strip()

        if not xml_file and not xml_text:
            return render_template("index.html", error="請上傳 XML 檔案或貼上 XML 內容。")

        if xml_file:
            xml_bytes = xml_file.read()
            xml_text = xml_bytes.decode("utf-8", errors="ignore")

        try:
            row = parse_hrv_xml_to_row(xml_text)
        except Exception as e:
            return render_template("index.html", error=f"XML 解析失敗：{e}")

        quad_img_b64 = generate_quadrant_plot_base64(row)
        advice = get_constitution_advice(row.get("Constitution", ""))

        # 先把報告 render 成 HTML 字串，存起來給 PDF 用
        html = render_template(
            "report.html",
            row=row,
            quad_img_b64=quad_img_b64,
            advice=advice,
        )
        latest_pdf_html = html

        # 直接把 HTML 回傳給瀏覽器顯示
        return html

    # GET：顯示首頁上傳畫面
    return render_template("index.html")


@app.route("/export_pdf")
def export_pdf():
    """
    使用 xhtml2pdf 將最近一次產生的報告 HTML 轉成 PDF。
    """
    global latest_pdf_html
    if not latest_pdf_html:
        return "請先完成一次 HRV 分析，再下載 PDF 報告。", 400

    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        latest_pdf_html,
        dest=pdf_buffer,
        encoding="utf-8",
    )

    if pisa_status.err:
        return "PDF 產生失敗，請稍後再試。", 500

    pdf_buffer.seek(0)
    response = make_response(pdf_buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=HRV_Report.pdf"
    return response


if __name__ == "__main__":
    app.run(debug=True)

