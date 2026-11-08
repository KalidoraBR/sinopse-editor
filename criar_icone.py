"""Gera icone.ico (ícone do Sinopse Editor no Windows) e ui/icone.png: uma tela escura
com duas linhas de legenda, sobre o ciano do TMDB. É o mesmo desenho do logo da tela."""
from pathlib import Path

from PIL import Image, ImageDraw

TAM = 1024
CIANO = (1, 180, 228, 255)
ESCURO = (8, 17, 29, 255)


def desenhar():
    img = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((32, 32, TAM - 32, TAM - 32), radius=230, fill=CIANO)
    d.rounded_rectangle((176, 200, TAM - 176, TAM - 200), radius=110, fill=ESCURO)
    for (x0, x1, y) in ((300, TAM - 300, 560), (380, TAM - 380, 680)):
        d.rounded_rectangle((x0, y - 34, x1, y + 34), radius=34, fill=CIANO)
    return img


if __name__ == "__main__":
    pasta = Path(__file__).parent
    icone = desenhar()
    icone.save(pasta / "icone.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                          (128, 128), (256, 256)])
    icone.resize((256, 256), Image.LANCZOS).save(pasta / "ui" / "icone.png")
    print("ícone salvo")
