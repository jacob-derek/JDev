## Gato pixel na JBar
- Skin "gatinha" (padrão): tortoiseshell filhote — cinza-escuro com manchas caramelo, marrom e bege, peito branco, sobrancelhas claras, olhos âmbar, patinha da frente bege. `JGATO_SKIN=cinza` volta ao gato cinza.
- jcat.py: gato desenhado em código (sprites 16x12 em texto). Senta, anda de um lado a outro do espaço vazio da barra, dorme com zzz; com música tocando não dorme e balança; clique nele = carinho (coração).
- JBar: o gato passeia no maior espaço livre (antes ou depois do relógio) e some se não couber. `JGATO=0` desliga. Sem jcat.py a barra é igual a antes.
- tests: test_jcat (sprites, limites, estados) e test_jbar_gato (integração com tkinter de mentira).
