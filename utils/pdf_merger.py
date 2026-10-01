import os
from io import BytesIO

from PIL import Image
from pypdf import PdfWriter

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PDF_EXTENSION = ".pdf"
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {PDF_EXTENSION}


def is_supported_document(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS


def _image_to_pdf_buffer(path: str) -> BytesIO:
    image = Image.open(path)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    else:
        image = image.convert("RGB")

    buffer = BytesIO()
    image.save(buffer, format="PDF")
    buffer.seek(0)
    return buffer


def merge_documents(file_paths: list[str], output_path: str) -> None:
    if not file_paths:
        raise ValueError("Nenhum arquivo para unir.")

    writer = PdfWriter()
    buffers: list[BytesIO] = []
    try:
        for path in file_paths:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Arquivo não encontrado: {path}")

            ext = os.path.splitext(path)[1].lower()
            if ext == PDF_EXTENSION:
                writer.append(path)
            elif ext in IMAGE_EXTENSIONS:
                buffer = _image_to_pdf_buffer(path)
                buffers.append(buffer)
                writer.append(buffer)
            else:
                raise ValueError(f"Formato não suportado: {os.path.basename(path)}")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        writer.write(output_path)
    finally:
        writer.close()
        for buffer in buffers:
            buffer.close()
