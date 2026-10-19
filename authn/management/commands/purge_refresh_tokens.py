from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from authn.repositories import RefreshTokenRepository


class Command(BaseCommand):
    help = "Delete expired or revoked refresh tokens older than N days."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Purge tokens older than this many days (expires_at or revoked_at, default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the count without deleting.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be >= 1")

        cutoff = timezone.now() - timedelta(days=days)

        if options["dry_run"]:
            count = RefreshTokenRepository.count_old(cutoff)
            self.stdout.write(f"Would delete {count} rows (--dry-run).")
        else:
            count = RefreshTokenRepository.purge_old(cutoff)
            self.stdout.write(f"Deleted {count} rows.")
