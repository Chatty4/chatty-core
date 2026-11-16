"""users/0002_avatar_file and teams/0002_icon_file: ids that point at no file become NULL, the
others stay, and the columns keep their data."""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from teams.models import Team
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("users", "0001_initial"), ("teams", "0001_initial"), ("files", "0001_initial")]


def migrate(targets) -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(targets or executor.loader.graph.leaf_nodes())


def test_missing_ids_become_null_and_real_ones_stay():
    migrate(BEFORE)
    try:
        old = MigrationExecutor(connection).loader.project_state(BEFORE).apps
        OldUser, OldTeam, OldFile = (
            old.get_model("users", "User"),
            old.get_model("teams", "Team"),
            old.get_model("files", "File"),
        )
        ana = OldUser.objects.create(email="ana@example.com", display_name="Ana")
        file = OldFile.objects.create(
            owner=ana,
            purpose="avatar",
            object_key="avatars/a/b",
            filename="me.png",
            mime="image/png",
            size=5,
            upload_expires_at=timezone.now(),
        )
        OldUser.objects.filter(id=ana.id).update(avatar_id=file.id)
        bob = OldUser.objects.create(
            email="bob@example.com", display_name="Bob", avatar_id=uuid.uuid4()
        )
        kept = OldTeam.objects.create(name="Backend", icon_id=file.id)
        dropped = OldTeam.objects.create(name="Design", icon_id=uuid.uuid4())
    finally:
        migrate(None)

    assert User.objects.get(id=ana.id).avatar_id == file.id
    assert User.objects.get(id=bob.id).avatar_id is None
    assert Team.objects.get(id=kept.id).icon_id == file.id
    assert Team.objects.get(id=dropped.id).icon_id is None
