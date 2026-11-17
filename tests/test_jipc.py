"""jipc: cliente/servidor locais (sockets em 127.0.0.1)."""
import os
import queue
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jipc  # noqa: E402


class TestForaDoJDesk(unittest.TestCase):
    def test_sem_variaveis_tudo_vira_no_op(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(jipc.disponivel())
            self.assertFalse(jipc.enviar({"cmd": "x"}))
            self.assertFalse(jipc.Receptor("a", lambda m: None).iniciar())

    def test_porta_invalida_nao_levanta(self):
        with mock.patch.dict(os.environ, {"JDESK_SOCK": "lixo", "JDESK_TOKEN": "t"}, clear=True):
            self.assertFalse(jipc.disponivel())


class TestServidor(unittest.TestCase):
    def setUp(self):
        self.s = jipc.Servidor()
        self.s.iniciar()
        self.addCleanup(self.s.fechar)
        env = mock.patch.dict(os.environ, {**self.s.env(), "JDESK_WS": "1", "JDESK_PANE": "t"})
        env.start()
        self.addCleanup(env.stop)

    def _atender_um(self, ok=True):
        def run():
            try:
                msg, conn = self.s.fila.get(timeout=3)
                self.s.responder(conn, ok)
            except queue.Empty:
                pass
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def test_enviar_recebe_ok(self):
        self._atender_um()
        self.assertTrue(jipc.enviar({"cmd": "ping"}, timeout=2))

    def test_token_errado_derruba_a_conexao(self):
        with socket.create_connection(("127.0.0.1", self.s.porta), timeout=2) as c:
            c.sendall(b'{"cmd":"x","token":"errado"}\n')
            c.settimeout(2)
            self.assertEqual(c.recv(10), b"")
        self.assertTrue(self.s.fila.empty())

    def test_json_invalido_nao_derruba_o_servidor(self):
        with socket.create_connection(("127.0.0.1", self.s.porta), timeout=2) as c:
            c.sendall(b"nao e json\n")
        self._atender_um()
        self.assertTrue(jipc.enviar({"cmd": "ping"}, timeout=2))

    def test_receptor_recebe_mensagens(self):
        got = queue.Queue()
        r = jipc.Receptor("alvo", got.put)
        self.assertTrue(r.iniciar())
        self.addCleanup(r.parar)
        for _ in range(50):
            if self.s.entregar("1", "alvo", {"cmd": "refresh", "path": "/x"}):
                break
            time.sleep(0.1)
        self.assertEqual(got.get(timeout=2)["path"], "/x")

    def test_entregar_sem_receptor_devolve_false(self):
        self.assertFalse(self.s.entregar("1", "ninguem", {"cmd": "x"}))

    def test_fila_cheia_recusa_em_vez_de_crescer(self):
        for _ in range(jipc.LIMITE_FILA):
            self.s.fila.put(({}, None))
        with mock.patch.dict(os.environ, self.s.env()):
            self.assertFalse(jipc.enviar({"cmd": "x"}, timeout=2))
        self.assertEqual(self.s.fila.qsize(), jipc.LIMITE_FILA)


if __name__ == "__main__":
    unittest.main()
