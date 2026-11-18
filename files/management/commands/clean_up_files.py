from django.core.management.base import BaseCommand
from django.utils import timezone

from files.services import FileService


class Command(BaseCommand):
    help = "Delete files nobody uses from MinIO and the database (D-17). Run every hour."

    def handle(self, *args, **options):
        marked, removed = FileService.clean_up(timezone.now())
        self.stdout.write(f"Marked {marked} files unused, removed {removed}.")
