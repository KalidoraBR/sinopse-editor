"""Pinta a barra de título do Windows (a faixa com o nome e os botões de
minimizar/fechar) com as cores do tema. Funciona no Windows 11; em versões
mais antigas não faz nada (a barra continua no padrão do sistema)."""
import ctypes
import sys

# Atributos do DWM (Windows 11, build 22000+)
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

TEMAS = {
    # cor da barra, cor do texto, cor da borda (formato #RRGGBB)
    "escuro": ("#071629", "#F2F6FA", "#071629"),
    "claro": ("#F4E6EE", "#141821", "#F4E6EE"),
}


def _colorref(hexa):
    """#RRGGBB → COLORREF do Windows (0x00BBGGRR)."""
    r, g, b = int(hexa[1:3], 16), int(hexa[3:5], 16), int(hexa[5:7], 16)
    return ctypes.c_uint(r | (g << 8) | (b << 16))


def _janela_por_titulo(titulo):
    return ctypes.windll.user32.FindWindowW(None, titulo)


def pintar(titulo, tema="escuro"):
    """Aplica as cores do tema na barra da janela com esse título. Devolve True se deu certo."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = _janela_por_titulo(titulo)
        if not hwnd:
            return False
        dwm = ctypes.windll.dwmapi
        barra, texto, borda = TEMAS.get(tema, TEMAS["escuro"])
        escuro = ctypes.c_int(1 if tema != "claro" else 0)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(escuro), 4)
        ok = True
        for atributo, cor in ((DWMWA_CAPTION_COLOR, barra), (DWMWA_TEXT_COLOR, texto),
                              (DWMWA_BORDER_COLOR, borda)):
            valor = _colorref(cor)
            ok = dwm.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(valor), 4) == 0 and ok
        return ok
    except Exception:
        return False
