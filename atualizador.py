"""Atualização pelo GitHub: procura a versão mais nova nas Releases, baixa o zip e troca
os arquivos do programa (Sinopse Editor.exe e _internal). Os dados do usuário (config,
login, histórico, trabalhos) ficam na pasta e não são tocados.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPOSITORIO = "KalidoraBR/sinopse-editor"
URL_ULTIMA = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
NOME_EXE = "Sinopse Editor.exe"


def _numeros(versao):
    partes = []
    for p in str(versao).lstrip("vV").split("."):
        digitos = "".join(c for c in p if c.isdigit())
        partes.append(int(digitos or 0))
    return tuple(partes)


def instalado():
    """Só a versão portátil (.exe) se atualiza sozinha; rodando pelo código, não."""
    return bool(getattr(sys, "frozen", False))


def procurar(versao_atual):
    """Devolve os dados da versão nova, ou None se já está na mais recente."""
    pedido = urllib.request.Request(URL_ULTIMA, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Sinopse-Editor"})
    with urllib.request.urlopen(pedido, timeout=15) as resposta:
        dados = json.load(resposta)
    versao = dados.get("tag_name", "")
    if _numeros(versao) <= _numeros(versao_atual):
        return None
    zipado = next((a for a in dados.get("assets", []) if a["name"].lower().endswith(".zip")), None)
    if not zipado:
        return None
    return {"versao": versao.lstrip("vV"), "notas": dados.get("body") or "",
            "url": zipado["browser_download_url"], "tamanho": zipado.get("size", 0),
            "pagina": dados.get("html_url", "")}


def baixar_e_preparar(url, progresso=None):
    """Baixa e extrai o zip numa pasta temporária. Devolve a pasta com o .exe novo."""
    temp = Path(tempfile.mkdtemp(prefix="sinopse_atualizacao_"))
    arquivo = temp / "nova.zip"
    pedido = urllib.request.Request(url, headers={"User-Agent": "Sinopse-Editor"})
    with urllib.request.urlopen(pedido, timeout=60) as resposta, open(arquivo, "wb") as saida:
        total = int(resposta.headers.get("Content-Length") or 0)
        feito = 0
        while True:
            bloco = resposta.read(1 << 16)
            if not bloco:
                break
            saida.write(bloco)
            feito += len(bloco)
            if progresso and total:
                progresso(feito, total)
    with zipfile.ZipFile(arquivo) as z:
        z.extractall(temp / "extraido")
    arquivo.unlink()
    exe = next((temp / "extraido").rglob(NOME_EXE), None)
    if not exe or not (exe.parent / "_internal").is_dir():
        raise RuntimeError("O arquivo baixado não tem o programa dentro.")
    return exe.parent


def trocar_e_reabrir(pasta_nova):
    """Cria um .bat que espera o programa fechar, troca os arquivos e abre de novo.
    Quem chama deve fechar a janela logo depois."""
    app = Path(sys.executable).parent
    temp = pasta_nova
    while temp.parent != Path(tempfile.gettempdir()) and temp.parent != temp:
        temp = temp.parent
    bat = Path(tempfile.gettempdir()) / "sinopse_atualizar.bat"
    bat.write_text(f"""@echo off
chcp 65001 >nul
:espera
tasklist /fi "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && (timeout /t 1 /nobreak >nul & goto espera)
robocopy "{pasta_nova / '_internal'}" "{app / '_internal'}" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS >nul
copy /y "{pasta_nova / NOME_EXE}" "{app / NOME_EXE}" >nul
start "" "{app / NOME_EXE}"
rmdir /s /q "{temp}"
(goto) 2>nul & del "%~f0"
""", encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
