"""Testes do núcleo do JToast (sem Tk e sem D-Bus)."""
import json
import os
import tempfile
import unittest

from tests import _paths  # noqa: F401
import JToast
from JToast import Gerente


class TestLimparTexto(unittest.TestCase):
    def test_tira_tags_e_entidades(self):
        self.assertEqual(JToast.limpar_texto("<b>oi</b> &amp; <i>tchau</i>", 50), "oi & tchau")

    def test_remove_controles_e_corta_linhas(self):
        self.assertEqual(JToast.limpar_texto("a\x00b\x1b[31m\nc\n\nd", 50, linhas=2), "ab[31m\nc")

    def test_limite_com_reticencias(self):
        self.assertEqual(JToast.limpar_texto("abcdefghij", 5), "abcd…")

    def test_tipos_estranhos(self):
        self.assertEqual(JToast.limpar_texto(None, 10), "")
        self.assertEqual(JToast.limpar_texto(123, 10), "123")


class TestGerente(unittest.TestCase):
    def test_ids_crescem_e_comecam_em_1(self):
        g = Gerente()
        self.assertEqual([g.notificar("a", 0, "x", "", 1, -1, 0) for _ in range(3)], [1, 2, 3])

    def test_substituir_mantem_id_e_sobe_versao(self):
        g = Gerente()
        nid = g.notificar("a", 0, "um", "", 1, -1, 0)
        self.assertEqual(g.notificar("a", nid, "dois", "", 1, -1, 5), nid)
        n = g.visiveis()[0]
        self.assertEqual((n.resumo, n.versao, g.total()), ("dois", 1, 1))

    def test_substituir_id_inexistente_cria_novo(self):
        g = Gerente()
        self.assertEqual(g.notificar("a", 99, "x", "", 1, -1, 0), 1)

    def test_expiracao_por_urgencia(self):
        g = Gerente()
        g.notificar("a", 0, "baixa", "", 0, -1, 0)      # 4 s
        g.notificar("a", 0, "normal", "", 1, -1, 0)     # 6 s
        g.notificar("a", 0, "critica", "", 2, -1, 0)    # nunca
        self.assertEqual(g.expirar(4.1), [1])
        self.assertEqual(g.expirar(6.1), [2])
        self.assertEqual(g.expirar(10_000), [])
        self.assertEqual(g.total(), 1)

    def test_timeout_explicito_e_zero(self):
        g = Gerente()
        g.notificar("a", 0, "curta", "", 1, 1000, 0)
        g.notificar("a", 0, "fica", "", 1, 0, 0)
        self.assertEqual(g.expirar(1.5), [1])
        self.assertEqual(g.total(), 1)

    def test_timeout_gigante_e_limitado(self):
        g = Gerente()
        g.notificar("a", 0, "x", "", 1, 10 ** 9, 0)
        self.assertEqual(g.expirar(JToast.ESPERA_MAXIMA + 1), [1])

    def test_visiveis_mais_novas_primeiro_e_limite(self):
        g = Gerente(max_visiveis=3)
        for i in range(6):
            g.notificar("a", 0, f"n{i}", "", 1, -1, float(i))
        self.assertEqual([n.resumo for n in g.visiveis()], ["n5", "n4", "n3"])
        self.assertEqual(g.total(), 6)

    def test_fechar_registra_sinal(self):
        g = Gerente()
        nid = g.notificar("a", 0, "x", "", 1, -1, 0)
        self.assertTrue(g.fechar(nid, JToast.MOTIVO_CLIQUE))
        self.assertFalse(g.fechar(nid))
        self.assertEqual(g.pegar_fechadas(), [(nid, JToast.MOTIVO_CLIQUE)])
        self.assertEqual(g.pegar_fechadas(), [])

    def test_expirar_tambem_vira_sinal(self):
        g = Gerente()
        g.notificar("a", 0, "x", "", 1, 1000, 0)
        g.expirar(2)
        self.assertEqual(g.pegar_fechadas(), [(1, JToast.MOTIVO_EXPIROU)])

    def test_enxurrada_descarta_o_excesso(self):
        g = Gerente(enxurrada=(5, 2.0))
        ids = [g.notificar("spam", 0, "x", "", 1, -1, 0.0) for _ in range(50)]
        self.assertEqual(g.total(), 5)
        self.assertEqual(ids[-1], ids[4])                 # devolve um id válido, sem criar outro
        self.assertEqual(g.notificar("outro", 0, "x", "", 1, -1, 0.0), 6)   # outro app não é afetado
        self.assertEqual(g.notificar("spam", 0, "x", "", 1, -1, 3.0), 7)    # passada a janela, volta

    def test_teto_de_guardadas(self):
        g = Gerente(max_guardadas=10, enxurrada=(10 ** 6, 1.0))
        for i in range(100):
            g.notificar(f"app{i}", 0, "x", "", 2, -1, float(i))
        self.assertEqual(g.total(), 10)

    def test_texto_vazio_vira_aviso(self):
        g = Gerente()
        g.notificar("a", 0, "", "", 1, -1, 0)
        self.assertEqual(g.visiveis()[0].resumo, "(sem texto)")

    def test_urgencia_invalida_vira_normal(self):
        g = Gerente()
        g.notificar("a", 0, "x", "", 77, -1, 0)
        self.assertEqual(g.visiveis()[0].urgencia, 1)

    def test_entradas_hostis_nao_quebram(self):
        g = Gerente()
        g.notificar("a" * 10_000, 0, "<script>" + "x" * 10_000, "\x00" * 5000 + "y" * 5000, 1, "lixo", 0)
        n = g.visiveis()[0]
        self.assertLessEqual(len(n.resumo), JToast.LIMITE_RESUMO)
        self.assertLessEqual(len(n.corpo), JToast.LIMITE_CORPO)


class TestMonitor(unittest.TestCase):
    SAIDA = ("Screen 0: minimum 8 x 8, current 3200 x 1065, maximum 32767 x 32767\n"
             "HDMI-1 connected primary 1600x900+0+0 (normal left inverted right x axis y axis) 0mm x 0mm\n"
             "VGA-1 connected 1600x900+1600+0 (normal left inverted right x axis y axis) 0mm x 0mm\n")

    def test_acha_o_primario(self):
        self.assertEqual(JToast.parse_monitor(self.SAIDA), (0, 0, 1600, 900))

    def test_sem_primario_usa_o_primeiro(self):
        self.assertEqual(JToast.parse_monitor(self.SAIDA.replace(" primary", "")), (0, 0, 1600, 900))

    def test_sem_nada(self):
        self.assertIsNone(JToast.parse_monitor(""))
        self.assertIsNone(JToast.parse_monitor(None))


class TestDespachar(unittest.TestCase):
    def test_notify(self):
        g = Gerente()
        corpo = ("app", 0, "", "Título", "Corpo", [], {"urgency": ("y", 2)}, -1)
        self.assertEqual(JToast.despachar(g, JToast.NOME_BUS, "Notify", corpo), ("u", (1,)))
        self.assertEqual(g.visiveis()[0].urgencia, 2)

    def test_notify_sem_interface(self):
        g = Gerente()
        corpo = ("app", 0, "", "T", "", [], {}, -1)
        self.assertEqual(JToast.despachar(g, None, "Notify", corpo)[0], "u")

    def test_notify_malformado(self):
        with self.assertRaises(ValueError):
            JToast.despachar(Gerente(), JToast.NOME_BUS, "Notify", ("so", "dois"))
        with self.assertRaises(ValueError):
            JToast.despachar(Gerente(), JToast.NOME_BUS, "Notify", ("a", [], "", "t", "", [], {}, -1))

    def test_close(self):
        g = Gerente()
        nid = g.notificar("a", 0, "x", "", 1, -1, 0)
        self.assertEqual(JToast.despachar(g, JToast.NOME_BUS, "CloseNotification", (nid,)), ("", ()))
        self.assertEqual(g.total(), 0)
        with self.assertRaises(ValueError):
            JToast.despachar(g, JToast.NOME_BUS, "CloseNotification", ())

    def test_informacoes_do_servidor(self):
        sig, vals = JToast.despachar(Gerente(), JToast.NOME_BUS, "GetServerInformation", ())
        self.assertEqual((sig, vals[0], vals[3]), ("ssss", "JToast", "1.2"))

    def test_capacidades_e_introspeccao(self):
        self.assertEqual(JToast.despachar(Gerente(), JToast.NOME_BUS, "GetCapabilities", ())[0], "as")
        sig, (xml,) = JToast.despachar(Gerente(), "org.freedesktop.DBus.Introspectable", "Introspect", ())
        self.assertEqual(sig, "s")
        self.assertIn("NotificationClosed", xml)

    def test_metodo_desconhecido(self):
        with self.assertRaises(LookupError):
            JToast.despachar(Gerente(), JToast.NOME_BUS, "Explodir", ())


class TestEstado(unittest.TestCase):
    def test_escreve_json_atomico(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "sub", "jtoast-state.json")
            JToast.escrever_estado(3, caminho)
            with open(caminho, encoding="utf-8") as f:
                dados = json.load(f)
            self.assertEqual((dados["count"], dados["pid"]), (3, os.getpid()))
            self.assertEqual(os.listdir(os.path.dirname(caminho)), ["jtoast-state.json"])

    def test_nao_levanta_em_caminho_ruim(self):
        JToast.escrever_estado(1, "/proc/nao/existe/x.json")


if __name__ == "__main__":
    unittest.main()
