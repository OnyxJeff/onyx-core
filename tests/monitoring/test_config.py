"""Offline config-only tests: no network, SSH, task, or filesystem writes outside temp fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "windows" / "monitoring" / "OnyxMonitorConfig.py"
EXAMPLE = ROOT / "windows" / "monitoring" / "monitoring.development.example.json"
spec = importlib.util.spec_from_file_location("OnyxMonitorConfig", MODULE)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = config_module.load_config(EXAMPLE)

    def changed(self, path, value):
        data = copy.deepcopy(self.example)
        target = data
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        return data

    def rejected(self, path, value):
        with self.assertRaises(config_module.ConfigError):
            config_module.validate_config(self.changed(path, value))

    def test_valid_reference_config(self):
        self.assertEqual(self.example["windows"]["receiver_ip"], "192.168.137.167")
        self.assertEqual(self.example["repair_action"], "None")

    def test_no_production_profile(self):
        self.rejected(["profile"], "production")

    def test_no_repairs(self):
        self.rejected(["repair_action"], "RestartSharedAccess")
        self.rejected(["read_only"], False)

    def test_no_production_or_arbitrary_state(self):
        self.rejected(["state_dir"], r"%LOCALAPPDATA%\OnyxCore\Monitoring")
        self.rejected(["state_dir"], r"D:\other")

    def test_no_unapproved_ssh_identity(self):
        self.rejected(["pi", "monitor_key_path"], r"%USERPROFILE%\.ssh\id_rsa")

    def test_requires_real_python_binary_path(self):
        self.rejected(["runtime", "python_executable"], "python")
        self.rejected(["runtime", "python_executable"], r"C:\Users\x\WindowsApps\python.exe")

    def test_invalid_network(self):
        self.rejected(["windows", "gateway_ip"], "not-an-ip")
        self.rejected(["windows", "receiver_ip"], "192.168.137.1")
        self.rejected(["windows", "receiver_port"], True)

    def test_bounds_and_unknown_settings(self):
        self.rejected(["monitoring_interval_seconds"], 10)
        self.rejected(["timeouts", "ssh_seconds"], 100)
        self.rejected(["automatic_repair"], True)

    def test_invalid_json_duplicate_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaises(config_module.ConfigError):
                config_module.load_config(path)

    def test_oversize_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversize.json"
            path.write_text(" " * 16385, encoding="utf-8")
            with self.assertRaises(config_module.ConfigError):
                config_module.load_config(path)

    def test_json_roundtrip(self):
        data = json.loads(json.dumps(self.example))
        self.assertEqual(config_module.validate_config(data)["profile"], "development")


if __name__ == "__main__":
    unittest.main()
