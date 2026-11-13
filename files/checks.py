import io
import warnings

import filetype
from PIL import Image

# Pillow's format name for each image type avatars and team icons may have.
IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
# Decoding needs memory for every pixel, and a 2 MB file can claim to be 50,000 x 50,000.
MAX_IMAGE_PIXELS = 25_000_000  # 5000 x 5000

# D-18: what filetype calls Windows and Linux programs.
PROGRAM_TYPES = {"application/x-msdownload", "application/x-executable"}
# filetype doesn't know macOS programs (Mach-O): their first 4 bytes, both byte orders, and the
# "fat" binary with several architectures.
MACH_O_STARTS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}


def detect_image_mime(data: bytes) -> str | None:
    """The image type of data, or None if it isn't a whole PNG, JPEG, WebP or GIF image."""
    try:
        with warnings.catch_warnings():
            # Pillow only warns about a decompression bomb below twice its own limit
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=list(IMAGE_FORMATS)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    return None
                image.load()
                return IMAGE_FORMATS.get(image.format or "")
    except (
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return None


def is_program(start: bytes) -> bool:
    """True if the first bytes of a file are a Windows, Linux or macOS program (D-18)."""
    kind = filetype.guess_mime(start)
    if kind == "application/x-msdownload":
        # filetype only looks at "MZ", which a text file can start with too
        return _has_pe_header(start)
    return kind in PROGRAM_TYPES or start[:4] in MACH_O_STARTS


def _has_pe_header(start: bytes) -> bool:
    """A Windows program: its DOS header points (at byte 0x3C) to the "PE" header."""
    if len(start) < 0x40:
        return False
    offset = int.from_bytes(start[0x3C:0x40], "little")
    return start[offset : offset + 4] == b"PE\0\0"
