import unittest
from datetime import date

from jpopup import grade_mes, mouse_para_percentual, limitar_popup


class TestLogicaPopup(unittest.TestCase):
    def test_grade_42_dias_domingo_inicio(self):
        grade = grade_mes(2026, 11, date(2026, 11, 21))
        self.assertEqual(len(grade), 6)
        self.assertTrue(all(len(semana) == 7 for semana in grade))
        self.assertEqual(grade[0][0][0], 1)  # novembro de 2026 começa domingo
        self.assertEqual(grade[2][6], [21, True, True])

    def test_grade_mostra_adjacent(self):
        grade = grade_mes(2025, 2, date(2025, 2, 1))
        self.assertFalse(grade[0][0][1])
        self.assertTrue(any(not dia[1] for semana in grade for dia in semana))

    def test_slider_percentual_limites(self):
        self.assertEqual(mouse_para_percentual(0, 204), 0)
        self.assertEqual(mouse_para_percentual(102, 204), 50)
        self.assertEqual(mouse_para_percentual(204, 204), 100)
        self.assertEqual(mouse_para_percentual(-10, 204), 0)
        self.assertEqual(mouse_para_percentual(20, 0), 0)

    def test_popup_preso_na_tela(self):
        self.assertEqual(limitar_popup(900, 700, 300, 250, 1000, 800, 700), (700, 450))
        self.assertEqual(limitar_popup(-50, -20, 300, 250, 1000, 800, -20), (0, 0))


if __name__ == "__main__":
    unittest.main()
