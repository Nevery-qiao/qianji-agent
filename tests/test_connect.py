import unittest
from qianji_agent.connect import recommend
class ConnectTests(unittest.TestCase):
 def test_unknown_does_not_guess_location(self):self.assertEqual(recommend('unknown','http','yes')['state'],'needs_information')
 def test_same_mac_stdio(self):self.assertEqual(recommend('same-mac','stdio','yes')['route'],'local_stdio')
 def test_cloud_url_requires_mac(self):
  self.assertEqual(recommend('cloud','http','yes')['route'],'remote_readonly')
  self.assertEqual(recommend('cloud','http','no')['state'],'blocked')
 def test_cloud_stdio_not_mac_shell(self):self.assertEqual(recommend('cloud','stdio','yes')['state'],'blocked')
 def test_cloud_write_not_opened(self):self.assertEqual(recommend('cloud','http','yes','write')['state'],'blocked')
 def test_no_mcp_local_is_limited_cli(self):self.assertEqual(recommend('same-mac','none','yes')['route'],'limited_local_cli')
