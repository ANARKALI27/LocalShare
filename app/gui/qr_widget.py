"""
Generates a QR code image for the current share address, so a phone
can scan it instead of someone typing an IP address by hand.

Uses the "qrcode" package (with its optional PIL backend) to build a
PNG in memory, then hands that PNG straight to Qt as a QPixmap — no
temp files on disk.
"""
from __future__ import annotations

import io

from PySide6.QtGui import QPixmap


def generate_qr_pixmap(data: str, box_size: int = 6) -> QPixmap | None:
    """
    Returns a QPixmap of a QR code encoding `data`, or None if the
    "qrcode" package isn't installed (caller should handle this
    gracefully — e.g. hide the QR section rather than crash).
    """
    try:
        import qrcode
    except ImportError:
        return None

    qr = qrcode.QRCode(
        version=None,  # let the library pick the smallest version that fits the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    png_bytes = buffer.getvalue()

    pixmap = QPixmap()
    pixmap.loadFromData(png_bytes, "PNG")
    return pixmap if not pixmap.isNull() else None
