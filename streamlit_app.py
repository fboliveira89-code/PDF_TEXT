import io
import hashlib
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

from streamlit_drawable_canvas import st_canvas

RectPT = Tuple[float, float, float, float]  # (x0,y0,x1,y1) em pontos (PDF)


@dataclass
class PageRender:
    image: Image.Image         # imagem renderizada (pixels)
    page_w_pt: float           # largura da página em pontos
    page_h_pt: float           # altura da página em pontos


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


@st.cache_data(show_spinner=False)
def render_page_cached(pdf_md5: str, pdf_bytes: bytes, page_index: int, zoom: float) -> PageRender:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    pr = PageRender(image=img, page_w_pt=page.rect.width, page_h_pt=page.rect.height)
    doc.close()
    return pr


def rect_disp_to_rect_pt(
    rect_disp: Tuple[float, float, float, float],
    display_scale: float,
    img_w_px: int,
    img_h_px: int,
    page_w_pt: float,
    page_h_pt: float,
) -> RectPT:
    x0d, y0d, x1d, y1d = rect_disp
    x0d, x1d = sorted([x0d, x1d])
    y0d, y1d = sorted([y0d, y1d])

    x0 = x0d / display_scale
    y0 = y0d / display_scale
    x1 = x1d / display_scale
    y1 = y1d / display_scale

    x0 = max(0.0, min(float(img_w_px), x0))
    x1 = max(0.0, min(float(img_w_px), x1))
    y0 = max(0.0, min(float(img_h_px), y0))
    y1 = max(0.0, min(float(img_h_px), y1))

    sx = page_w_pt / img_w_px
    sy = page_h_pt / img_h_px
    return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)


def rect_pt_to_rect_px(rect_pt: RectPT, img_w_px: int, img_h_px: int, page_w_pt: float, page_h_pt: float):
    x0, y0, x1, y1 = rect_pt
    sx = img_w_px / page_w_pt
    sy = img_h_px / page_h_pt
    return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)


def get_last_rect_from_canvas(canvas_json) -> Optional[Tuple[float, float, float, float]]:
    if not canvas_json or "objects" not in canvas_json or not canvas_json["objects"]:
        return None

    rects = [o for o in canvas_json["objects"] if o.get("type") == "rect"]
    if not rects:
        return None
    o = rects[-1]

    left = float(o.get("left", 0.0))
    top = float(o.get("top", 0.0))
    w = float(o.get("width", 0.0)) * float(o.get("scaleX", 1.0))
    h = float(o.get("height", 0.0)) * float(o.get("scaleY", 1.0))

    return (left, top, left + w, top + h)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int):
    lines = []
    for paragraph in (text or "").replace("\r\n", "\n").split("\n"):
        if paragraph.strip() == "":
            lines.append("")
            continue

        words = paragraph.split(" ")
        cur = ""
        for w in words:
            trial = w if cur == "" else (cur + " " + w)
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines


def build_preview_image(
    base_img: Image.Image,
    page_w_pt: float,
    page_h_pt: float,
    rect_text_pt: Optional[RectPT],
    rect_stamp_pt: Optional[RectPT],
    message: str,
    font_pt: int,
    stamp_pil: Optional[Image.Image],
    keep_ratio: bool,
):
    img = base_img.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    img_w, img_h = img.size
    px_per_pt = img_w / page_w_pt

    font_px = max(10, int(font_pt * px_per_pt))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_px)
    except Exception:
        font = ImageFont.load_default()

    if rect_text_pt and message.strip():
        x0, y0, x1, y1 = rect_pt_to_rect_px(rect_text_pt, img_w, img_h, page_w_pt, page_h_pt)
        x0, y0, x1, y1 = map(int, [x0, y0, x1, y1])
        pad = 10
        draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255, 160), outline=(65, 105, 225, 255), width=3)

        max_w = max(10, (x1 - x0) - 2 * pad)
        lines = wrap_text(draw, message, font, max_w)

        bbox = font.getbbox("Ag")
        line_h = (bbox[3] - bbox[1]) + 4
        max_lines = max(1, ((y1 - y0) - 2 * pad) // line_h)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip() + " …"

        yy = y0 + pad
        for ln in lines:
            draw.text((x0 + pad, yy), ln, font=font, fill=(0, 0, 0, 255))
            yy += line_h

    if rect_stamp_pt and stamp_pil is not None:
        x0, y0, x1, y1 = rect_pt_to_rect_px(rect_stamp_pt, img_w, img_h, page_w_pt, page_h_pt)
        x0, y0, x1, y1 = map(int, [x0, y0, x1, y1])
        draw.rectangle([x0, y0, x1, y1], outline=(46, 139, 87, 255), width=3)

        target_w = max(1, x1 - x0)
        target_h = max(1, y1 - y0)

        stamp = stamp_pil.copy().convert("RGBA")
        sw, sh = stamp.size

        if keep_ratio:
            scale = min(target_w / sw, target_h / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            stamp = stamp.resize((nw, nh), Image.LANCZOS)
            px = x0 + (target_w - nw) // 2
            py = y0 + (target_h - nh) // 2
        else:
            stamp = stamp.resize((target_w, target_h), Image.LANCZOS)
            px, py = x0, y0

        img.alpha_composite(stamp, dest=(px, py))

    return img.convert("RGB")


def apply_edits_to_pdf(
    pdf_bytes: bytes,
    rects_by_page: Dict[int, Dict[str, RectPT]],
    message: str,
    font_pt: int,
    stamp_png_bytes: Optional[bytes],
    keep_ratio: bool,
):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for pno, d in rects_by_page.items():
        if pno < 0 or pno >= doc.page_count:
            continue
        page = doc[pno]

        if "texto" in d and message.strip():
            r = fitz.Rect(*d["texto"])
            page.insert_textbox(
                r,
                message,
                fontsize=int(font_pt),
                fontname="helv",
                color=(0, 0, 0),
                align=0,
            )

        if "stamp" in d and stamp_png_bytes:
            r = fitz.Rect(*d["stamp"])
            page.insert_image(
                r,
                stream=stamp_png_bytes,
                keep_proportion=keep_ratio,
                overlay=True
            )

    out = doc.tobytes(deflate=True)
    doc.close()
    return out


st.set_page_config(page_title="PDF Texto + Stamp", layout="wide")
st.title("PDF: inserir mensagem + stamp (Streamlit)")

if "page_index" not in st.session_state:
    st.session_state.page_index = 0
if "rects_by_page" not in st.session_state:
    st.session_state.rects_by_page = {}

with st.sidebar:
    st.header("Ficheiros")
    pdf_file = st.file_uploader("Upload PDF", type=["pdf"])
    stamp_file = st.file_uploader("Upload stamp (PNG/JPG/WebP)", type=["png", "jpg", "jpeg", "webp"])

    st.header("Conteúdo")
    message = st.text_area("Mensagem", value="Não aplicar qualquer penalização", height=120)
    font_pt = st.number_input("Tamanho da fonte (pt)", min_value=6, max_value=30, value=11, step=1)
    keep_ratio = st.checkbox("Stamp: manter proporções", value=True)

    st.header("Modo de selecção")
    mode = st.radio("Atribuir rectângulo a:", ["texto", "stamp"], horizontal=True)

    show_debug = st.checkbox("Mostrar debug", value=False)

if not pdf_file:
    st.info("Faz upload de um PDF para começar.")
    st.stop()

pdf_bytes = pdf_file.getvalue()
pdf_hash = md5_bytes(pdf_bytes)

# Stamp: converter SEMPRE para PNG em memória
stamp_png_bytes = None
stamp_pil = None
if stamp_file:
    raw = stamp_file.getvalue()
    try:
        stamp_pil = Image.open(io.BytesIO(raw)).convert("RGBA")
        buf = io.BytesIO()
        stamp_pil.save(buf, format="PNG")
        stamp_png_bytes = buf.getvalue()
    except Exception:
        stamp_png_bytes = raw
        stamp_pil = None

doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
page_count = doc_tmp.page_count
doc_tmp.close()

col_nav1, col_nav2, col_nav3, _ = st.columns([1, 1, 2, 6], vertical_alignment="center")
with col_nav1:
    if st.button("◀ Página", disabled=(st.session_state.page_index <= 0)):
        st.session_state.page_index -= 1
with col_nav2:
    if st.button("Página ▶", disabled=(st.session_state.page_index >= page_count - 1)):
        st.session_state.page_index += 1
with col_nav3:
    st.markdown(f"**Página {st.session_state.page_index + 1}/{page_count}**")

page_index = st.session_state.page_index

ZOOM_RENDER = 2.0
pr = render_page_cached(pdf_hash, pdf_bytes, page_index, ZOOM_RENDER)
img = pr.image
page_w_pt, page_h_pt = pr.page_w_pt, pr.page_h_pt

MAX_W = 900
disp_w = min(MAX_W, img.width)
display_scale = disp_w / img.width
disp_h = int(img.height * display_scale)
disp_img = img.resize((disp_w, disp_h), Image.LANCZOS)

st.subheader(f"1) Desenha um rectângulo na página (modo actual: **{mode}**)")

# IMPORTANT: a API do st_canvas aceita background_image (PIL). O package "-fix" trata da compatibilidade com Streamlit recente.
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=2,
    stroke_color="#ff0000",
    background_image=disp_img,
    update_streamlit=True,
    height=disp_h,
    width=disp_w,
    drawing_mode="rect",
    key=f"canvas_{pdf_hash}_{page_index}",
)

last_rect_disp = get_last_rect_from_canvas(canvas_result.json_data)

col_a, col_b, _ = st.columns([1, 1, 3], vertical_alignment="center")
with col_a:
    apply_rect = st.button("Guardar área deste rectângulo")
with col_b:
    clear_page = st.button("Limpar áreas desta página")

if clear_page:
    st.session_state.rects_by_page.pop(page_index, None)
    st.success("Áreas desta página limpas.")
    st.rerun()

if apply_rect:
    if not last_rect_disp:
        st.warning("Ainda não desenhaste nenhum rectângulo.")
    else:
        rect_pt = rect_disp_to_rect_pt(
            last_rect_disp,
            display_scale=display_scale,
            img_w_px=img.width,
            img_h_px=img.height,
            page_w_pt=page_w_pt,
            page_h_pt=page_h_pt,
        )
        st.session_state.rects_by_page.setdefault(page_index, {})
        st.session_state.rects_by_page[page_index][mode] = rect_pt
        st.success(f"Área guardada para **{mode}** na página {page_index + 1}.")
        st.rerun()

page_rects = st.session_state.rects_by_page.get(page_index, {})
rect_text_pt = page_rects.get("texto")
rect_stamp_pt = page_rects.get("stamp")

if show_debug:
    st.sidebar.markdown("### Debug")
    st.sidebar.write("rect_text_pt:", rect_text_pt)
    st.sidebar.write("rect_stamp_pt:", rect_stamp_pt)
    st.sidebar.write("stamp_png_bytes:", None if stamp_png_bytes is None else len(stamp_png_bytes))

st.subheader("2) Preview (com overlays)")
preview = build_preview_image(
    base_img=img,
    page_w_pt=page_w_pt,
    page_h_pt=page_h_pt,
    rect_text_pt=rect_text_pt,
    rect_stamp_pt=rect_stamp_pt,
    message=message,
    font_pt=int(font_pt),
    stamp_pil=stamp_pil,
    keep_ratio=keep_ratio,
)
preview_disp = preview.resize((disp_w, disp_h), Image.LANCZOS)
st.image(preview_disp, caption="Preview (não altera o PDF)", use_container_width=False)

st.subheader("3) Gerar PDF")
apply_all = st.checkbox("Aplicar a todas as páginas com áreas definidas", value=True)

can_generate = True
if not st.session_state.rects_by_page:
    can_generate = False
    st.warning("Ainda não definiste nenhuma área (texto/stamp).")

if rect_stamp_pt and not stamp_png_bytes:
    st.warning("Definiste área de stamp nesta página, mas ainda não carregaste o stamp.")
    can_generate = False

if st.button("Gerar PDF final", disabled=not can_generate):
    rects_to_apply = st.session_state.rects_by_page if apply_all else {page_index: page_rects}

    out_pdf = apply_edits_to_pdf(
        pdf_bytes=pdf_bytes,
        rects_by_page=rects_to_apply,
        message=message,
        font_pt=int(font_pt),
        stamp_png_bytes=stamp_png_bytes,
        keep_ratio=keep_ratio,
    )

    st.success("PDF gerado!")
    st.download_button(
        "Download do PDF",
        data=out_pdf,
        file_name="pdf_com_texto_stamp.pdf",
        mime="application/pdf",
    )

st.caption("Dica: escolhe o modo (texto/stamp), desenha o rectângulo e clica em “Guardar área deste rectângulo”. O stamp é convertido para PNG em memória.")
