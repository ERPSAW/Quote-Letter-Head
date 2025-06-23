import frappe
import io
import pdfkit
import re
import urllib.parse
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from frappe.utils import scrub_urls, get_bench_relative_path
from frappe.utils.pdf import prepare_options, get_wkhtmltopdf_version, PDF_CONTENT_ERRORS, cleanup, get_file_data_from_writer
from packaging.version import Version
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import *
from reportlab.lib.utils import ImageReader

PAGE_SIZE = {
    "A0" : A0,
    "A1" : A1,
    "A2" : A2,
    "A3" : A3,
    "A4" : A4,
    "A5" : A5,
    "A6" : A6,
    "A7" : A7,
    "A8" : A8,
    "A9" : A9,
    "A10" : A10,
    "B0" : B0,
    "B1" : B1,
    "B2" : B2,
    "B3" : B3,
    "B4" : B4,
    "B5" : B5,
    "B6" : B6,
    "B7" : B7,
    "B8" : B8,
    "B9" : B9,
    "B10" : B10,
    "C0" : C0,
    "C1" : C1,
    "C2" : C2,
    "C3" : C3,
    "C4" : C4,
    "C5" : C5,
    "C6" : C6,
    "C7" : C7,
    "C8" : C8,
    "C9" : C9,
    "C10" : C10,
}

def watermark_pdf(image_path, opacity, pagesize):
    # Create PDF Page Size Custom Watermark Page
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    c.saveState()
    c.setFillAlpha(opacity)
    c.setStrokeAlpha(opacity)
    c.drawImage(ImageReader(image_path), 0, 0, *pagesize, mask='auto')
    c.restoreState()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]

def add_watermark(pdf_bytes, image_path, opacity=1, pagesize=None):
    original_pdf = PdfReader(io.BytesIO(pdf_bytes))
    output = PdfWriter()

    if pagesize is None:
        page0 = original_pdf.pages[0]
        width = float(page0.mediabox.width)
        height = float(page0.mediabox.height)
        pagesize = (width, height)

    watermark = watermark_pdf(image_path, opacity, pagesize)

    for page in original_pdf.pages:
        # Create Blank PDF and First Add Watermark Page then add Original PDF Content
        new_page = PdfWriter().add_blank_page(*pagesize)
        new_page.merge_page(watermark)
        new_page.merge_page(page)
        output.add_page(new_page)

    out_buf = io.BytesIO()
    output.write(out_buf)
    return out_buf.getvalue()


def extract_watermark_image_url(html):
    # Fetch Watermark Image from to the style tag of letter head style tag
    soup = BeautifulSoup(html, "html.parser")

    for style_tag in soup.find_all("style"):
        match = re.search(r'\.watermark\s*\{[^}]*background-image:\s*url\([\'"]?(.*?)[\'"]?\)', style_tag.string or "")
        if match:
            full_url = match.group(1).strip()
            full_url = full_url.split("/files")[-1]

            full_url = urllib.parse.unquote(full_url)

            file_path = "sites/" + frappe.utils.get_path('private' if "private" in match.group(1) else "public" , 'files')[2:] + full_url
            return get_bench_relative_path(str(file_path))
    return None


def custom_get_pdf(html, options=None, output: PdfWriter | None = None):
    html = scrub_urls(html)

    # First Fetch Watermark Image Path from style tag from letter head and apply default some css for transparent
    image_path = extract_watermark_image_url(html)

    if image_path:
        html = html.replace("</head>", """
            <style>
                @page {
                    background: transparent;
                }
                html, body {
                    background: transparent !important;
                }
                .print-format, .print-format * {
                    background: transparent !important;
                }
            </style>
            </head>
        """)

    html, options = prepare_options(html, options)

    options.update({"disable-javascript": "", "disable-local-file-access": ""})


    filedata = ""
    if Version(get_wkhtmltopdf_version()) > Version("0.12.3"):
        options.update({"disable-smart-shrinking": ""})

    try:
        # Set filename property to false, so no file is actually created
        filedata = pdfkit.from_string(html, options=options or {}, verbose=True)

        # Fetch page-size is available and watermark image is available then generate watermark pdf and override to orignal pdf file data
        if PAGE_SIZE.get(options.get('page-size')) and image_path:
            filedata = add_watermark(filedata, image_path, opacity=1, pagesize=PAGE_SIZE.get(options.get('page-size')))

        # create in-memory binary streams from filedata and create a PdfReader object
        reader = PdfReader(io.BytesIO(filedata))
    except OSError as e:
        if any([error in str(e) for error in PDF_CONTENT_ERRORS]):
            if not filedata:
                print(html, options)
                frappe.throw(_("PDF generation failed because of broken image links"))

            # allow pdfs with missing images if file got created
            if output:
                output.append_pages_from_reader(reader)
        else:
            raise
    finally:
        cleanup(options)

    if "password" in options:
        password = options["password"]

    if output:
        output.append_pages_from_reader(reader)
        return output

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    if "password" in options:
        writer.encrypt(password)

    filedata = get_file_data_from_writer(writer)

    return filedata