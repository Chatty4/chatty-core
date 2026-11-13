"""D-18 at POST /files: programs and installers are refused by name and declared type."""

import pytest

from files.models import File
from files.services import BLOCKED_EXTENSIONS, BLOCKED_TYPES
from tests.helpers import post_file

pytestmark = pytest.mark.django_db(transaction=True)


async def post_attachment(client, auth, team, filename: str, mime: str = "application/pdf"):
    return await post_file(
        client, auth, purpose="attachment", team_id=str(team.id), filename=filename, mime=mime
    )


async def assert_refused(response) -> None:
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "type_not_allowed"
    assert await File.objects.acount() == 0


@pytest.mark.parametrize("extension", sorted(BLOCKED_EXTENSIONS))
async def test_blocked_extension(async_client, auth, team, extension):
    response = await post_attachment(async_client, auth, team, f"setup{extension}")

    await assert_refused(response)


@pytest.mark.parametrize(
    "filename",
    [
        "SETUP.EXE",  # any case
        "Setup.Msi",
        "setup.exe.",  # Windows drops trailing dots and spaces, so these still run
        "setup.exe . .",
        "report.pdf.exe",  # only the last extension counts
        "invoice\u202efdp.exe",  # shows as "invoiceexe.pdf"; cleaned to "invoicefdp.exe"
    ],
)
async def test_blocked_extension_in_disguise(async_client, auth, team, filename):
    response = await post_attachment(async_client, auth, team, filename)

    await assert_refused(response)


@pytest.mark.parametrize("mime", sorted(BLOCKED_TYPES))
async def test_blocked_type(async_client, auth, team, mime):
    response = await post_attachment(async_client, auth, team, "tool.bin", mime)

    await assert_refused(response)


@pytest.mark.parametrize(
    "mime",
    [
        "Application/X-MSDownload",  # any case
        "application/x-msdownload; charset=binary",  # parameters don't hide the type
        " application/x-msdownload ",
    ],
)
async def test_blocked_type_in_disguise(async_client, auth, team, mime):
    response = await post_attachment(async_client, auth, team, "tool.bin", mime)

    await assert_refused(response)


@pytest.mark.parametrize("purpose", ["avatar", "team_icon"])
async def test_image_purposes_are_checked_too(async_client, auth, team, purpose):
    team_id = str(team.id) if purpose == "team_icon" else None
    response = await post_file(
        async_client, auth, purpose=purpose, team_id=team_id, filename="photo.exe"
    )

    await assert_refused(response)


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("script.js", "text/javascript"),  # code shared in chat stays allowed (D-18)
        ("deploy.sh", "application/x-sh"),
        ("main.py", "text/x-python"),
        ("archive.zip", "application/zip"),
        ("notes.exe.txt", "text/plain"),  # .exe isn't the last extension
        ("executive-summary.pdf", "application/pdf"),
    ],
)
async def test_other_files_are_allowed(async_client, auth, team, filename, mime):
    response = await post_attachment(async_client, auth, team, filename, mime)

    assert response.status_code == 201
