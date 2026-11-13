import io
import zipfile

import pytest
from PIL import Image

from files import checks


def image_bytes(fmt: str, size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.effect_noise(size, 64).convert("RGB").save(buffer, fmt)
    return buffer.getvalue()


def zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")  # what a .docx looks like
    return buffer.getvalue()


ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 57
# A DOS header whose last 4 bytes (0x3C) point to the "PE" header right after it, at 0x40.
WINDOWS = b"MZ" + b"\x00" * 58 + (0x40).to_bytes(4, "little") + b"PE\0\0" + b"\x00" * 64


# --- detect_image_mime ---


@pytest.mark.parametrize(
    ("fmt", "mime"),
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")],
)
def test_detects_each_image_type(fmt, mime):
    assert checks.detect_image_mime(image_bytes(fmt)) == mime


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
@pytest.mark.parametrize("kept", [0.5, 0.9, 0.99])
def test_cut_off_image_is_not_an_image(fmt, kept):
    data = image_bytes(fmt, (256, 256))

    assert checks.detect_image_mime(data[: int(len(data) * kept)]) is None


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj",
        b"just some text, not an image",
        b"",
        WINDOWS,
    ],
)
def test_other_bytes_are_not_an_image(data):
    assert checks.detect_image_mime(data) is None


def test_image_types_avatars_cant_have_are_not_an_image():
    assert checks.detect_image_mime(image_bytes("BMP")) is None
    assert checks.detect_image_mime(image_bytes("TIFF")) is None


def test_image_with_too_many_pixels_is_refused(monkeypatch):
    monkeypatch.setattr(checks, "MAX_IMAGE_PIXELS", 64 * 64 - 1)

    assert checks.detect_image_mime(image_bytes("PNG")) is None


def test_decompression_bomb_is_refused(monkeypatch):
    # Pillow warns above its limit and raises above twice the limit; both mean "not an image"
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 64 * 64 - 1)
    assert checks.detect_image_mime(image_bytes("PNG")) is None

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    assert checks.detect_image_mime(image_bytes("PNG")) is None


# --- is_program ---


@pytest.mark.parametrize(
    "start",
    [
        WINDOWS,
        ELF,
        b"\xfe\xed\xfa\xce" + b"\x00" * 28,  # macOS, 32-bit
        b"\xcf\xfa\xed\xfe" + b"\x00" * 28,  # macOS, 64-bit, little-endian
        b"\xca\xfe\xba\xbe" + b"\x00" * 28,  # macOS, several architectures
    ],
)
def test_programs(start):
    assert checks.is_program(start)


@pytest.mark.parametrize(
    "start",
    [
        b"%PDF-1.7\n",
        b"just some text",
        b"",
        b"MZ",  # too short to be a Windows program
        b"MZ, Mazowieckie;1,2,3\n" * 10,  # text that starts with MZ: no PE header
        WINDOWS.replace(b"PE\0\0", b"XX\0\0"),  # a DOS header that points nowhere
    ],
)
def test_not_programs(start):
    assert not checks.is_program(start)


def test_documents_archives_and_images_are_not_programs():
    assert not checks.is_program(zip_bytes())  # .docx, .xlsx, .zip
    assert not checks.is_program(image_bytes("PNG"))
