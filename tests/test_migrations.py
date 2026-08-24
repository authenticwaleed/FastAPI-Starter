"""Phase 4 acceptance: Alembic configuration and revision history.

Applying migrations is exercised with the CLI against the real database.
These tests guard the parts that break quietly: a committed connection URL,
and a history that has silently grown a second head.
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))


def test_alembic_ini_does_not_contain_a_connection_url() -> None:
    text = (PROJECT_ROOT / "alembic.ini").read_text()

    # Commented-out lines are fine; an active setting would commit credentials.
    assert not re.search(r"^sqlalchemy\.url\s*=\s*\S", text, re.MULTILINE)


def test_revision_history_has_exactly_one_head() -> None:
    # Two heads mean two migrations claim to be the latest, and `upgrade head`
    # stops working until they are merged.
    assert len(_script_directory().get_heads()) == 1


def test_every_revision_can_upgrade_and_downgrade() -> None:
    revisions = list(_script_directory().walk_revisions())

    assert revisions, "no migrations found"

    for revision in revisions:
        source = Path(revision.path).read_text()

        assert "def upgrade()" in source, revision.revision
        assert "def downgrade()" in source, revision.revision
        assert "pass" not in source.split("def downgrade()")[1], revision.revision


def test_users_table_is_created_by_a_migration() -> None:
    sources = "".join(
        Path(revision.path).read_text()
        for revision in _script_directory().walk_revisions()
    )

    assert "create_table('users'" in sources
