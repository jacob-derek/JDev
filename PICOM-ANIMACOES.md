# Animações do picom (abrir/fechar janela, trocar workspace, mover/redimensionar)

1. Descubra a versão:  `picom --version`
2. Faça backup:        `cp ~/.config/picom/picom.conf ~/.config/picom/picom.conf.bak`
3. Cole no FIM do `~/.config/picom/picom.conf` o bloco que combina com a versão e reinicie a sessão
   (ou `pkill picom; picom --config ~/.config/picom/picom.conf &` para testar). Erro de sintaxe? O picom
   imprime a linha; é só apagar o bloco novo para voltar ao que era.

## Qualquer versão: fade (suave, leve)
```
fading = true;
fade-in-step = 0.07;
fade-out-step = 0.07;
fade-delta = 8;
```

## picom 12 ou mais novo: animações de verdade (use ESTE no lugar do fade acima)
```
animations = (
  { triggers = ["open", "show"];   preset = "appear";          duration = 0.16; scale = 0.94; },
  { triggers = ["close", "hide"];  preset = "disappear";       duration = 0.12; scale = 0.96; },
  { triggers = ["geometry"];       preset = "geometry-change"; duration = 0.14; }
);
```
- `open/show` e `close/hide` também cobrem a troca de workspace (as janelas escondem e aparecem).
- `geometry` anima mover/redimensionar (mosaico reorganizando, janela flutuante arrastada).
- Quer mais calmo? Aumente `duration`; mais "seco"? Reduza. Não gostou? Tire só o bloco.

## Borda da janela (JWM)
O fade da cor da borda ao ganhar/perder foco é do próprio JWM: `JWM_ANIM=0` desliga,
`JWM_ANIM_MS=200` deixa mais lento (padrão 140).
