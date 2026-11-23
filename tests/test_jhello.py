import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jhello as h


class T(unittest.TestCase):
    def test_saudacao(self):
        self.assertEqual(h.saudacao(8, "Jacob"), "Bom dia, Jacob")
        self.assertEqual(h.saudacao(15), "Boa tarde")
        self.assertEqual(h.saudacao(2), "Boa noite")

    def test_cmdline(self):
        self.assertEqual(h.app_do_cmdline(["python3", "/x/JCode.py", "a"]), "JCode.py")
        self.assertIsNone(h.app_do_cmdline(["vim", "JCode.py.bak"]))
        self.assertIsNone(h.app_do_cmdline(["python3", "/x/JBar.py"]))

    def test_novos(self):
        self.assertEqual(h.novos({1: "JCode.py"}, {1: "JCode.py", 2: "JFiles.py", 3: "JFiles.py"}), ["JFiles.py"])
        self.assertEqual(h.novos({}, {}), [])


if __name__ == "__main__":
    unittest.main()
