"""Gera icone.ico (ícone do Sinopse Editor no Windows): TV com play, sobre o
degradê verde-água → turquesa (cores inspiradas no TMDB)."""
from pathlib import Path

from PIL import Image, ImageDraw

TAM = 512
VERDE = (144, 206, 161)
TURQUESA = (1, 180, 228)
MARINHO = (13, 37, 63, 255)


def degrade():
    """Degradê na diagonal (canto de cima à esquerda → canto de baixo à direita)."""
    img = Image.new("RGBA", (TAM, TAM))
    px = img.load()
    for y in range(TAM):
        for x in range(TAM):
            t = (x + y) / (2 * (TAM - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(VERDE, TURQUESA)) + (255,)
    return img


def desenhar():
    mascara = Image.new("L", (TAM, TAM), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((16, 16, TAM - 16, TAM - 16), radius=120, fill=255)
    img = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))
    img.paste(degrade(), (0, 0), mascara)
    d = ImageDraw.Draw(img)
    # Mesmo desenho do ícone da tela (grade de 56 → 512, com margem)
    u = (TAM - 96) / 56
    x0 = y0 = 48

    def p(x, y):
        return (x0 + x * u, y0 + y * u)
    traco = 34
    d.rounded_rectangle((*p(6, 11), *p(50, 41)), radius=int(7 * u), outline=MARINHO, width=traco)
    d.polygon([p(24, 20), p(24, 32), p(34, 26)], fill=MARINHO)
    d.line((*p(20, 48), *p(36, 48)), fill=MARINHO, width=traco)
    r = traco / 2
    for x in (20, 36):
        cx, cy = p(x, 48)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=MARINHO)
    return img


if __name__ == "__main__":
    destino = Path(__file__).parent / "icone.ico"
    desenhar().save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                    (128, 128), (256, 256)])
    desenhar().resize((256, 256)).save(Path(__file__).parent / "ui" / "icone.png")
    print("ícone salvo em", destino)
