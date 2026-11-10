"""M1 Step 4 offline guard tests. Never invokes collector top-level or opens sockets."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "windows/networking/Collect-OnyxRecoveryEvidence.ps1"


class CollectorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = COLLECTOR.read_text(encoding="utf-8-sig")

    def test_explicit_live_opt_in(self):
        self.assertIn("[switch]$LiveReadOnly", self.source)
        self.assertIn("if (-not $LiveReadOnly)", self.source)
        self.assertLess(self.source.index("if (-not $LiveReadOnly)"),
                        self.source.index("function Invoke-OnyxBoundedSsh"))

    def test_restricted_development_worktree_only(self):
        self.assertIn("feature/v0.7.0-monitoring", self.source)
        self.assertIn("onyx-core-v070", self.source)
        self.assertNotIn("feature/v0.6.0-reliability", self.source)
        self.assertNotIn("OnyxCore-v060-Development", self.source)

    def test_validated_config_and_isolated_history(self):
        self.assertIn("$Validator --check $ResolvedConfigPath", self.source)
        self.assertIn("$Config.state_dir", self.source)
        self.assertIn("$HistoryPath = Join-Path $HistoryDirectory 'recovery-observations.json'", self.source)
        self.assertIn("Only the approved development configuration file", self.source)

    def test_probes_use_validated_config(self):
        for value in ("-AdapterName $AdapterName", "-GatewayIP $GatewayIP",
                      "-ReceiverIP $ReceiverIP", "-ReceiverPort $ReceiverPort",
                      "-TimeoutMs $ReceiverTimeoutMs", "$UpstreamInterface",
                      "$SshTimeoutSeconds", "$MonitorKeyPath"):
            with self.subTest(value=value):
                self.assertIn(value, self.source)
        self.assertIn("& $PythonExecutable $DecisionEngine", self.source)

    def test_ssh_restrictions_remain(self):
        for flag in ("BatchMode=yes", "StrictHostKeyChecking=yes",
                     "IdentitiesOnly=yes", "PreferredAuthentications=publickey",
                     "NumberOfPasswordPrompts=0", "PasswordAuthentication=no",
                     "KbdInteractiveAuthentication=no", "-T', '-n'", "onyxcore-monitor"):
            with self.subTest(flag=flag):
                self.assertIn(flag, self.source)

    def test_history_bounds_and_no_repair(self):
        for requirement in ("$MaxHistoryAgeSeconds = 300", "$MaxObservations = 12",
                            "$MaxHistoryBytes = 262144", "repair_action = 'None'",
                            "Local\\OnyxCoreV070RecoveryEvidence"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.source)


if __name__ == "__main__":
    unittest.main()
