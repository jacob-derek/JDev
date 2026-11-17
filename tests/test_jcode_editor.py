"""Testes das funções puras novas do JCode: limpeza ao salvar, Tab no fim da linha e mapa."""
import unittest

from tests import _paths  # noqa: F401
import JCode


class TestLimparEspacos(unittest.TestCase):
    def test_remove_espacos_e_tabs_finais(self):
        novo, n = JCode.limpar_espacos_finais("a = 1  \nb\t\n\nc")
        self.assertEqual(novo, "a = 1\nb\n\nc")
        self.assertEqual(n, 2)

    def test_sem_mudanca(self):
        self.assertEqual(JCode.limpar_espacos_finais("a\n  b\n"), ("a\n  b\n", 0))

    def test_linha_so_com_espacos_vira_vazia(self):
        self.assertEqual(JCode.limpar_espacos_finais("x\n    \ny"), ("x\n\ny", 1))

    def test_poupa_linha_do_cursor_dentro_da_indentacao(self):
        # acabou de dar Enter depois de "if x:": o cursor está na coluna 4 da linha "    "
        novo, n = JCode.limpar_espacos_finais("if x:\n    ", 1, 4)
        self.assertEqual((novo, n), ("if x:\n    ", 0))

    def test_linha_do_cursor_com_cursor_no_codigo_e_limpa(self):
        novo, n = JCode.limpar_espacos_finais("abc   ", 0, 2)
        self.assertEqual((novo, n), ("abc", 1))

    def test_nao_mexe_na_quantidade_de_linhas(self):
        texto = "a  \n\n\n  \nb  \n"
        novo, _ = JCode.limpar_espacos_finais(texto)
        self.assertEqual(novo.count("\n"), texto.count("\n"))


class TestTabNoFimDaLinha(unittest.TestCase):
    def test_ignora_no_fim_de_linha_com_codigo(self):
        self.assertTrue(JCode.tab_ignorar("x = 1", 5))
        self.assertTrue(JCode.tab_ignorar("    return x  ", 15))   # só espaços depois do cursor

    def test_indenta_em_linha_vazia_ou_so_espacos(self):
        self.assertFalse(JCode.tab_ignorar("", 0))
        self.assertFalse(JCode.tab_ignorar("    ", 4))

    def test_indenta_no_meio_da_linha(self):
        self.assertFalse(JCode.tab_ignorar("x = 1", 1))
        self.assertFalse(JCode.tab_ignorar("x = 1", 0))

    def test_coluna_fora_do_intervalo(self):
        self.assertTrue(JCode.tab_ignorar("x", 99))


class TestMapa(unittest.TestCase):
    def test_perfil_marca_onde_ha_texto(self):
        # 3 caracteres por ponto: "abc" ocupa só o ponto 0; "abcdef" os pontos 0 e 1
        self.assertEqual(JCode.perfil_linhas("abc\nabcdef\n\n   ", px=8, chars=3), [0b1, 0b11, 0, 0])

    def test_perfil_respeita_indentacao(self):
        self.assertEqual(JCode.perfil_linhas("      x", px=8, chars=3), [0b100])

    def test_perfil_corta_linhas_longas(self):
        self.assertEqual(JCode.perfil_linhas("x" * 500, px=4, chars=3), [0b1111])

    def test_mapa_um_ponto_por_linha_em_arquivo_pequeno(self):
        perfil = JCode.perfil_linhas("a\n\n\nb", px=4, chars=3)   # 4 linhas = 1 linha de braille
        linhas = JCode.montar_mapa(perfil, altura=10, colunas=2)
        self.assertEqual(len(linhas), 1)
        texto, a, b = linhas[0]
        self.assertEqual((a, b), (0, 4))
        # ponto (linha 0, coluna 0) = 0x01 e ponto (linha 3, coluna 0) = 0x40
        self.assertEqual(texto, chr(0x2800 + 0x41) + " ")

    def test_mapa_arquivo_grande_cabe_na_altura(self):
        perfil = [0b1] * 1000
        linhas = JCode.montar_mapa(perfil, altura=10, colunas=2)
        self.assertEqual(len(linhas), 10)
        self.assertEqual(linhas[0][1], 0)
        self.assertEqual(linhas[-1][2], 1000)
        # intervalos contíguos, sem buracos nem sobreposição
        for (_, _, fim), (_, ini, _) in zip(linhas, linhas[1:], strict=False):
            self.assertEqual(fim, ini)

    def test_mapa_vazio(self):
        self.assertEqual(JCode.montar_mapa([], 10), [])
        self.assertEqual(JCode.montar_mapa([1], 0), [])

    def test_analise_inclui_perfil(self):
        res = JCode.analisar_documento("def f():\n    return 1\n", ".py", set(), 0)
        self.assertEqual(len(res.perfil), 3)
        self.assertGreater(res.perfil[0], 0)

    def test_analise_arquivo_gigante_sem_perfil(self):
        res = JCode.analisar_documento("x" * (JCode.LIMITE_ANALISE_CHARS + 1), ".txt", set())
        self.assertIsNone(res.perfil)

    def test_estilos_do_mapa_usam_a_paleta(self):
        est = JCode.estilo_mapa({"pygments.comment": "#111111", "header": "#ffffff bold bg:#222222"})
        self.assertEqual(est["minimap"], "#111111")
        self.assertEqual(est["minimap.view"], "bg:#222222")

    def test_estilos_do_mapa_tem_fallback(self):
        est = JCode.estilo_mapa({})
        for chave in ("minimap", "minimap.def", "minimap.cursor", "minimap.erro", "minimap.view"):
            self.assertIn(chave, est)


if __name__ == "__main__":
    unittest.main()
