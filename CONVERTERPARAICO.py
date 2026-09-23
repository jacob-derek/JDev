from pathlib import Path
from PIL import Image


TAMANHOS = [
    (256, 256),
    (128, 128),
    (64, 64),
    (48, 48),
    (32, 32),
    (16, 16),
]


def converter(caminho):
    caminho = Path(caminho)

    if not caminho.exists():
        print(f"Arquivo não encontrado: {caminho}")
        return

    if caminho.suffix.lower() != ".png":
        print("O arquivo precisa ser PNG.")
        return

    saida = caminho.with_suffix(".ico")

    imagem = Image.open(caminho).convert("RGBA")

    imagem.save(
        saida,
        format="ICO",
        sizes=TAMANHOS
    )

    print(f"✓ Convertido: {saida}")


def main():
    arquivos = [
        "JFiles.png",
        "JCode.png",
        "JShell.png",
    ]

    for arquivo in arquivos:
        converter(arquivo)


if __name__ == "__main__":
    main()