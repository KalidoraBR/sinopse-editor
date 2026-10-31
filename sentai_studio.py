"""Sinopse Editor (antigo Sentai Studio) — abre a janela com a interface nova (pasta ui/).

A versão antiga, em CustomTkinter, continua em sentai_classico.py.
"""
import socket
import sys
from pathlib import Path

import webview

import barra_titulo
from servico import Api, VERSAO

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def main():
    api = Api()
    janela = webview.create_window(
        f"Sinopse Editor {VERSAO}", url=str(BASE / "ui" / "index.html"), js_api=api,
        width=1440, height=900, min_size=(1180, 720), background_color="#0B1626",
        text_select=True)
    api.ligar(janela)
    janela.events.closing += api.ao_fechar
    # Barra de título nas cores do tema (a tela pede a troca quando muda para o claro).
    janela.events.shown += lambda: barra_titulo.pintar(janela.title, "escuro")
    # Guarda as preferências da tela (ex.: lista compacta) ao lado do programa.
    pasta = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    # Porta livre só deste programa: duas cópias abertas juntas não trocam de tela.
    with socket.socket() as livre:
        livre.bind(("127.0.0.1", 0))
        porta = livre.getsockname()[1]
    webview.start(gui="edgechromium", debug="--debug" in sys.argv, private_mode=False, http_port=porta,
                  storage_path=str(pasta / "dados_tela"))


if __name__ == "__main__":
    main()
