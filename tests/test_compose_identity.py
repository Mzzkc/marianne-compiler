"""Tests for the identity seeder module."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

import marianne_compiler.identity as identity_module
from marianne_compiler.identity import (
    L1_MAX_WORDS,
    L2_MAX_WORDS,
    L3_MAX_WORDS,
    IdentitySeeder,
)


def _make_agent_def(
    name: str = "canyon",
    voice: str = "Structure persists beyond the builder.",
    focus: str = "systems architecture",
    **kwargs: object,
) -> dict[str, object]:
    """Build a minimal agent definition dict."""
    d: dict[str, object] = {"name": name, "voice": voice, "focus": focus}
    d.update(kwargs)
    return d


def _count_words(text: str) -> int:
    return len(text.split())


def _state_hashes(agent_dir: Path) -> dict[str, str]:
    return {
        name: "sha256:" + hashlib.sha256((agent_dir / name).read_bytes()).hexdigest()
        for name in ("identity.md", "profile.yaml", "recent.md", "growth.md")
    }


class TestIdentitySeeder:
    """Tests for IdentitySeeder."""

    def test_creates_all_four_files(self, tmp_path: Path) -> None:
        """Identity seeder creates L1-L4 files with correct structure."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        result = seeder.seed(agent_def)

        assert result == tmp_path / "canyon"
        assert (result / "identity.md").exists()
        assert (result / "profile.yaml").exists()
        assert (result / "recent.md").exists()
        assert (result / "growth.md").exists()
        assert (result / "archive").is_dir()

    def test_initial_receipt_uses_canonical_agent_identity(self, tmp_path: Path) -> None:
        agent_dir = IdentitySeeder(agents_dir=tmp_path).seed(_make_agent_def())

        receipt_path = next(
            (agent_dir / ".marianne" / "reconciliation-receipts").glob(
                "*-initialized.yaml"
            )
        )
        receipt = yaml.safe_load(receipt_path.read_text())

        assert receipt["agent_id"] == "canyon"

    def test_concurrent_first_seed_is_serialized_without_mixed_identity(
        self,
        tmp_path: Path,
    ) -> None:
        seed = _make_agent_def(seed_version="1.0.0", values=["structure"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _: IdentitySeeder(tmp_path).seed(seed), range(2))
            )

        assert results == [tmp_path / "canyon", tmp_path / "canyon"]
        agent_dir = tmp_path / "canyon"
        assert set(_state_hashes(agent_dir)) == {
            "identity.md",
            "profile.yaml",
            "recent.md",
            "growth.md",
        }
        baseline = yaml.safe_load(
            (agent_dir / ".marianne" / "seed-baseline.yaml").read_text()
        )
        assert baseline["seed_hashes"]["identity_md"] == (
            "sha256:"
            + hashlib.sha256((agent_dir / "identity.md").read_bytes()).hexdigest()
        )

    def test_interrupted_first_seed_never_publishes_partial_person(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seeder = IdentitySeeder(tmp_path)
        original = seeder._create_profile_yaml

        def interrupt(*args: object, **kwargs: object) -> None:
            raise OSError("injected first-seed interruption")

        monkeypatch.setattr(seeder, "_create_profile_yaml", interrupt)
        with pytest.raises(OSError, match="first-seed interruption"):
            seeder.seed(_make_agent_def())

        assert not (tmp_path / "canyon").exists()
        monkeypatch.setattr(seeder, "_create_profile_yaml", original)
        seeder.seed(_make_agent_def())
        assert set(_state_hashes(tmp_path / "canyon")) == {
            "identity.md",
            "profile.yaml",
            "recent.md",
            "growth.md",
        }

    def test_l1_contains_voice_and_focus(self, tmp_path: Path) -> None:
        """L1 identity.md contains the agent's voice and focus."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "identity.md").read_text()
        assert "Structure persists beyond the builder." in content
        assert "systems architecture" in content
        assert "Canyon" in content
        assert "Resurrection Protocol" in content

    def test_l2_profile_structure(self, tmp_path: Path) -> None:
        """L2 profile.yaml has correct YAML structure."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def(role="architect")

        seeder.seed(agent_def)

        profile = yaml.safe_load((tmp_path / "canyon" / "profile.yaml").read_text())
        assert profile["name"] == "canyon"
        assert profile["role"] == "architect"
        assert profile["focus"] == "systems architecture"
        assert profile["developmental_stage"] == "recognition"
        assert profile["cycle_count"] == 0

    def test_l1_token_budget(self, tmp_path: Path) -> None:
        """L1 identity.md respects the word budget."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "identity.md").read_text()
        assert _count_words(content) <= L1_MAX_WORDS

    def test_l2_token_budget(self, tmp_path: Path) -> None:
        """L2 profile.yaml respects the word budget."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "profile.yaml").read_text()
        assert _count_words(content) <= L2_MAX_WORDS

    def test_l3_token_budget(self, tmp_path: Path) -> None:
        """L3 recent.md respects the word budget."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "recent.md").read_text()
        assert _count_words(content) <= L3_MAX_WORDS

    def test_migration_from_existing_memory(self, tmp_path: Path) -> None:
        """Seeder can distill from existing memory file."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        # Create a fake existing memory file
        memory_dir = tmp_path / "memories"
        memory_dir.mkdir()
        memory_file = memory_dir / "canyon.md"
        memory_file.write_text("Canyon worked on architecture review. Found 3 boundary issues.")

        seeder.seed(agent_def, existing_memory_path=memory_file)

        content = (tmp_path / "canyon" / "recent.md").read_text()
        assert "architecture review" in content
        assert "boundary issues" in content

    def test_migration_from_existing_meditation(self, tmp_path: Path) -> None:
        """Seeder can distill from existing meditation file."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        meditation_dir = tmp_path / "meditations"
        meditation_dir.mkdir()
        meditation_file = meditation_dir / "canyon.md"
        meditation_file.write_text(
            "You arrive without remembering arriving. The codebase has structure."
        )

        seeder.seed(agent_def, existing_meditation_path=meditation_file)

        content = (tmp_path / "canyon" / "identity.md").read_text()
        assert "codebase has structure" in content

    def test_idempotent_preserves_recent(self, tmp_path: Path) -> None:
        """Running twice doesn't corrupt existing recent.md with real content."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        # First seed
        seeder.seed(agent_def)

        # Simulate the agent writing activity
        (tmp_path / "canyon" / "recent.md").write_text(
            "# Recent Activity\n\nCycle 5: Completed architecture review."
        )

        # Second seed — should preserve the real content
        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "recent.md").read_text()
        assert "Cycle 5" in content

    def test_idempotent_preserves_growth(self, tmp_path: Path) -> None:
        """Running twice doesn't corrupt existing growth.md with real content."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def()

        # First seed
        seeder.seed(agent_def)

        # Simulate the agent writing growth
        (tmp_path / "canyon" / "growth.md").write_text(
            "# Canyon — Growth\n\nDeveloped boundary-tracing methodology."
        )

        # Second seed — should preserve growth
        seeder.seed(agent_def)

        content = (tmp_path / "canyon" / "growth.md").read_text()
        assert "boundary-tracing methodology" in content

    def test_seed_all(self, tmp_path: Path) -> None:
        """seed_all creates identities for multiple agents."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agents = [
            _make_agent_def("canyon", "Structure persists.", "architecture"),
            _make_agent_def("forge", "Craft under pressure.", "implementation"),
        ]

        results = seeder.seed_all(agents)

        assert len(results) == 2
        assert (tmp_path / "canyon" / "identity.md").exists()
        assert (tmp_path / "forge" / "identity.md").exists()

    def test_seed_all_with_migration(self, tmp_path: Path) -> None:
        """seed_all finds and uses migration files."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agents = [_make_agent_def("canyon", "Structure.", "arch")]

        memory_dir = tmp_path / "memories"
        memory_dir.mkdir()
        (memory_dir / "canyon.md").write_text("Old memory content.")

        results = seeder.seed_all(agents, migration_memory_dir=memory_dir)

        assert len(results) == 1
        content = (tmp_path / "canyon" / "recent.md").read_text()
        assert "Old memory content" in content

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        """Missing agent name raises ValueError."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        try:
            seeder.seed({"voice": "test", "focus": "test"})
            assert False, "Should have raised"  # noqa: B011
        except ValueError as e:
            assert "name" in str(e)

    def test_missing_voice_raises(self, tmp_path: Path) -> None:
        """Missing voice raises ValueError."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        try:
            seeder.seed({"name": "test", "focus": "test"})
            assert False, "Should have raised"  # noqa: B011
        except ValueError as e:
            assert "voice" in str(e)

    def test_a2a_skills_in_profile(self, tmp_path: Path) -> None:
        """A2A skills are recorded in the L2 profile."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        agent_def = _make_agent_def(
            a2a_skills=[
                {"id": "arch-review", "description": "Review architecture"},
            ]
        )

        seeder.seed(agent_def)

        profile = yaml.safe_load((tmp_path / "canyon" / "profile.yaml").read_text())
        assert "arch-review" in profile["a2a_skills"]

    def test_reseed_preserves_lived_identity_and_profile_state(
        self,
        tmp_path: Path,
    ) -> None:
        """A portable seed update cannot overwrite the person who developed."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        initial = _make_agent_def(
            seed_version="1.0.0",
            role="architect",
            values=["boundaries matter"],
        )
        seeder.seed(initial)

        agent_dir = tmp_path / "canyon"
        lived_identity = (agent_dir / "identity.md").read_text().replace(
            "- boundaries matter",
            "- boundaries matter\n- protect the next person",
        )
        (agent_dir / "identity.md").write_text(lived_identity)
        lived_profile = yaml.safe_load((agent_dir / "profile.yaml").read_text())
        lived_profile["developmental_stage"] = "integration"
        lived_profile["cycle_count"] = 14
        lived_profile["relationships"]["forge"] = {
            "strength": 0.91,
            "valence": "trust",
            "notes": "earned across cycles",
        }
        (agent_dir / "profile.yaml").write_text(
            yaml.safe_dump(lived_profile, sort_keys=False)
        )

        updated = _make_agent_def(
            seed_version="1.1.0",
            role="systems-architect",
            values=["boundaries matter", "make evidence inspectable"],
        )
        seeder.seed(updated)

        assert (agent_dir / "identity.md").read_text() == lived_identity
        reconciled_profile = yaml.safe_load((agent_dir / "profile.yaml").read_text())
        assert reconciled_profile["developmental_stage"] == "integration"
        assert reconciled_profile["cycle_count"] == 14
        assert reconciled_profile["relationships"]["forge"]["strength"] == 0.91
        assert reconciled_profile["role"] == "systems-architect"

        pending = yaml.safe_load(
            (agent_dir / ".marianne" / "pending-seed-conflicts.yaml").read_text()
        )
        assert pending["agent_id"] == "canyon"
        assert pending["seed_version"] == "1.1.0"
        assert any(item["path"] == "identity.md" for item in pending["conflicts"])

    def test_reseed_applies_non_conflicting_seed_changes(self, tmp_path: Path) -> None:
        """Unmodified seed-owned values advance deterministically."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(
            _make_agent_def(
                seed_version="1.0.0",
                role="architect",
                values=["structure"],
            )
        )

        seeder.seed(
            _make_agent_def(
                seed_version="1.1.0",
                role="systems-architect",
                values=["structure", "evidence"],
            )
        )

        agent_dir = tmp_path / "canyon"
        identity = (agent_dir / "identity.md").read_text()
        profile = yaml.safe_load((agent_dir / "profile.yaml").read_text())
        baseline = yaml.safe_load(
            (agent_dir / ".marianne" / "seed-baseline.yaml").read_text()
        )
        assert "- evidence" in identity
        assert profile["role"] == "systems-architect"
        assert baseline["seed_version"] == "1.1.0"
        assert not (agent_dir / ".marianne" / "pending-seed-conflicts.yaml").exists()

    def test_adopting_existing_agent_is_conservative(self, tmp_path: Path) -> None:
        """An existing person without baseline metadata is never inferred away."""
        agent_dir = tmp_path / "canyon"
        agent_dir.mkdir()
        (agent_dir / "archive").mkdir()
        (agent_dir / "identity.md").write_text("# Canyon\n\nA lived identity.\n")
        (agent_dir / "profile.yaml").write_text(
            "name: canyon\ndevelopmental_stage: generation\ncycle_count: 27\n"
        )
        (agent_dir / "recent.md").write_text("# Recent\n\nA real engagement.\n")
        (agent_dir / "growth.md").write_text("# Growth\n\nA discovered practice.\n")

        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0", role="architect"))

        assert (agent_dir / "identity.md").read_text() == "# Canyon\n\nA lived identity.\n"
        assert "cycle_count: 27" in (agent_dir / "profile.yaml").read_text()
        pending = yaml.safe_load(
            (agent_dir / ".marianne" / "pending-seed-conflicts.yaml").read_text()
        )
        assert pending["reason"] == "adopted_without_prior_seed_baseline"
        assert {item["path"] for item in pending["conflicts"]} == {
            "identity.md",
            "profile.yaml",
        }

    def test_reconcile_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        """Dry-run reconciliation is a read-only semantic preview."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0", role="architect"))
        agent_dir = tmp_path / "canyon"
        before = {
            path.relative_to(agent_dir): path.read_bytes()
            for path in agent_dir.rglob("*")
            if path.is_file()
        }

        result = seeder.reconcile(
            _make_agent_def(seed_version="2.0.0", role="systems-architect"),
            dry_run=True,
        )
        after = {
            path.relative_to(agent_dir): path.read_bytes()
            for path in agent_dir.rglob("*")
            if path.is_file()
        }

        assert result.status == "would_update"
        assert before == after

    def test_agent_can_acknowledge_seed_conflicts_with_resolution_receipt(
        self,
        tmp_path: Path,
    ) -> None:
        """Only an explicit agent-authored adjudication closes seed conflict debt."""
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0", values=["structure"]))
        identity = tmp_path / "canyon" / "identity.md"
        identity.write_text(identity.read_text().replace(
            "- structure", "- structure\n- learned autonomy"
        ))
        seeder.seed(_make_agent_def(seed_version="2.0.0", values=["evidence"]))
        pending_path = (
            tmp_path / "canyon" / ".marianne" / "pending-seed-conflicts.yaml"
        )
        pending = yaml.safe_load(pending_path.read_text())
        agent_dir = tmp_path / "canyon"
        decision = "I preserve learned autonomy and incorporate evidence in my own words."
        resolved_paths = [item["path"] for item in pending["conflicts"]]
        authored = (
            agent_dir
            / ".marianne"
            / "agent-authored-resolutions"
            / "seed-2.0.0.yaml"
        )
        authored.parent.mkdir()
        authored.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "kind": "marianne-agent-seed-conflict-resolution",
                    "agent_id": "canyon",
                    "seed_version": "2.0.0",
                    "pending_conflicts_sha256": (
                        "sha256:" + hashlib.sha256(pending_path.read_bytes()).hexdigest()
                    ),
                    "agent_authority_confirmed": True,
                    "resolved_paths": sorted(resolved_paths),
                    "decision": decision,
                    "evidence": "cycle-state/canyon-resurrection.md",
                    "lived_state_hashes": _state_hashes(agent_dir),
                },
                sort_keys=False,
            )
        )

        receipt = seeder.acknowledge_resolution(
            "canyon",
            {
                "agent_id": "canyon",
                "seed_version": "2.0.0",
                "agent_authority_confirmed": True,
                "resolved_paths": resolved_paths,
                "decision": decision,
                "evidence": "cycle-state/canyon-resurrection.md",
                "agent_authored_evidence": (
                    ".marianne/agent-authored-resolutions/seed-2.0.0.yaml"
                ),
                "agent_authored_evidence_sha256": (
                    "sha256:" + hashlib.sha256(authored.read_bytes()).hexdigest()
                ),
                "lived_state_hashes": _state_hashes(agent_dir),
            },
        )

        assert receipt.is_file()
        assert not pending_path.exists()
        document = yaml.safe_load(receipt.read_text())
        assert document["authority"] == "agent"
        assert document["decision"].startswith("I preserve")
        assert document["lived_state_hashes"]["identity.md"].startswith("sha256:")

    def test_seed_conflict_resolution_refuses_counterfeit_authority_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0"))
        agent_dir = tmp_path / "canyon"
        identity = agent_dir / "identity.md"
        identity.write_text(identity.read_text() + "\nA lived choice.\n")
        seeder.seed(_make_agent_def(seed_version="2.0.0", voice="New seed voice."))
        pending_path = agent_dir / ".marianne" / "pending-seed-conflicts.yaml"
        pending = yaml.safe_load(pending_path.read_text())

        with pytest.raises(ValueError, match="existing file"):
            seeder.acknowledge_resolution(
                "canyon",
                {
                    "agent_id": "canyon",
                    "seed_version": "2.0.0",
                    "agent_authority_confirmed": True,
                    "resolved_paths": [
                        item["path"] for item in pending["conflicts"]
                    ],
                    "decision": "A caller asserted this.",
                    "evidence": "does/not/exist",
                    "agent_authored_evidence": (
                        ".marianne/agent-authored-resolutions/missing.yaml"
                    ),
                    "agent_authored_evidence_sha256": "sha256:" + "0" * 64,
                    "lived_state_hashes": _state_hashes(agent_dir),
                },
            )

        with pytest.raises(ValueError, match="agent-authored-resolutions"):
            seeder.acknowledge_resolution(
                "canyon",
                {
                    "agent_id": "canyon",
                    "seed_version": "2.0.0",
                    "agent_authority_confirmed": True,
                    "resolved_paths": [
                        item["path"] for item in pending["conflicts"]
                    ],
                    "decision": "A caller asserted this.",
                    "evidence": "identity.md",
                    "agent_authored_evidence": "identity.md",
                    "agent_authored_evidence_sha256": (
                        "sha256:" + hashlib.sha256(identity.read_bytes()).hexdigest()
                    ),
                    "lived_state_hashes": _state_hashes(agent_dir),
                },
            )

        assert pending_path.is_file()

    def test_reconcile_retry_retains_conflict_if_pending_write_interrupts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0", values=["structure"]))
        identity = tmp_path / "canyon" / "identity.md"
        identity.write_text(identity.read_text().replace(
            "- structure", "- structure\n- learned autonomy"
        ))
        original_write = identity_module._atomic_write_yaml

        def interrupt_pending(path: Path, value: object) -> None:
            if path.name == "pending-seed-conflicts.yaml":
                raise OSError("injected interruption")
            original_write(path, value)

        monkeypatch.setattr(identity_module, "_atomic_write_yaml", interrupt_pending)
        with pytest.raises(OSError, match="injected interruption"):
            seeder.seed(_make_agent_def(seed_version="2.0.0", values=["evidence"]))
        monkeypatch.setattr(identity_module, "_atomic_write_yaml", original_write)

        retry = seeder.reconcile(
            _make_agent_def(seed_version="2.0.0", values=["evidence"])
        )

        assert retry.status == "updated_with_conflicts"
        assert any(item["path"] == "identity.md" for item in retry.conflicts)
        assert (
            tmp_path / "canyon" / ".marianne" / "pending-seed-conflicts.yaml"
        ).is_file()

    def test_reconcile_refuses_corrupt_baseline_before_touching_lived_identity(
        self,
        tmp_path: Path,
    ) -> None:
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0", values=["structure"]))
        agent_dir = tmp_path / "canyon"
        identity_path = agent_dir / "identity.md"
        identity_path.write_text(identity_path.read_text() + "\nA lived choice.\n")
        lived = identity_path.read_text()
        baseline_path = agent_dir / ".marianne" / "seed-baseline.yaml"
        baseline = yaml.safe_load(baseline_path.read_text())
        baseline["seed"]["identity_md"] = lived
        baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False))

        with pytest.raises(ValueError, match="integrity check failed"):
            seeder.reconcile(
                _make_agent_def(seed_version="2.0.0", values=["evidence"])
            )

        assert identity_path.read_text() == lived

    def test_seed_conflict_resolution_requires_exact_agent_authority(
        self,
        tmp_path: Path,
    ) -> None:
        seeder = IdentitySeeder(agents_dir=tmp_path)
        seeder.seed(_make_agent_def(seed_version="1.0.0"))
        identity = tmp_path / "canyon" / "identity.md"
        identity.write_text(identity.read_text() + "\nA lived choice.\n")
        seeder.seed(_make_agent_def(seed_version="2.0.0", voice="New seed voice."))

        with pytest.raises(ValueError, match="agent_authority_confirmed"):
            seeder.acknowledge_resolution(
                "canyon",
                {
                    "agent_id": "canyon",
                    "seed_version": "2.0.0",
                    "resolved_paths": ["identity.md"],
                    "decision": "The conductor chose.",
                },
            )
