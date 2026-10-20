import unittest,tomllib
from pathlib import Path
from qianji_agent import __version__
class ReleaseVersionTests(unittest.TestCase):
 def test_runtime_and_distribution_versions_match(self):
  p=Path(__file__).resolve().parents[1]/'pyproject.toml'
  self.assertEqual(__version__,tomllib.loads(p.read_text())['project']['version'])
