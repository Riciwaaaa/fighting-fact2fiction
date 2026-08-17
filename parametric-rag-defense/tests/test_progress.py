import json
import tempfile
import unittest
from pathlib import Path

from parametric_rag_defense.progress import ExperimentLedger


class ExperimentLedgerTests(unittest.TestCase):
    def test_snapshot_and_append_only_events(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExperimentLedger(directory, "stage1_rag_v1.2", description="test")
            ledger.update(
                status="running", phase="clean", event="started", counts={"expected": 3}
            )
            ledger.update(
                status="complete",
                phase="clean",
                event="finished",
                counts={"expected": 3, "completed": 3},
            )
            snapshot = json.loads((Path(directory) / "stage1_rag_v1.2.json").read_text())
            events = (Path(directory) / "stage1_rag_v1.2.events.jsonl").read_text().splitlines()
            self.assertEqual(snapshot["status"], "complete")
            self.assertEqual(snapshot["counts"]["completed"], 3)
            self.assertEqual(len(events), 2)

    def test_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExperimentLedger(directory, "stage1_rag_v1.2", description="test")
            with self.assertRaises(ValueError):
                ledger.update(
                    status="running",
                    phase="clean",
                    event="bad",
                    details={"api_key": "secret"},
                )

    def test_rejects_unsafe_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                ExperimentLedger(directory, "../escape", description="test")
