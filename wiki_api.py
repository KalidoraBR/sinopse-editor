"""Leitura de Wikis do Fandom (e outras MediaWiki) pela API oficial (api.php),
sem abrir navegador. É o caminho principal; o navegador fica só de reserva.

Mesmas regras do leitor antigo (extrator.py):
- lista de episódios: links numerados da seção "Episodes"; senão a maior lista
  dessa seção (episódios sem número, na ordem); senão o artigo de episódios;
- sinopse: seção Synopsis; senão Summary; senão Plot (marcada para a IA resumir).
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser

AGENTE = "SinopseEditor/7 (uso pessoal; leitura de títulos e sinopses)"
PAUSA = 0.35  # segundos entre pedidos, para não sobrecarregar o site
ESPECIAL = re.compile(r"^(file|image|category|template|special|user|help|talk|module|mediawiki|"
                      r"portal|forum|blog|message[_ ]wall|fandom)([_ ]talk)?:", re.I)
SECAO_EPISODIOS = re.compile(r"^(episodes|episode list|episode guide|episódios|lista de episódios)", re.I)
RUIDO = {"aside", "nav", "script", "style"}
CLASSES_RUIDO = re.compile(r"portable-infobox|navbox|toc\b|reference|mw-editsection|noprint", re.I)


class ErroWiki(Exception):
    pass


# ------------------------------------------------------------- endereços
def separar(url):
    """https://x.fandom.com[/pt-br]/wiki/Título → (base da API, título, origem)."""
    p = urllib.parse.urlparse((url or "").strip())
    m = re.match(r"^(/[a-z-]+)?/wiki/(.+)$", p.path)
    if not p.netloc or not m:
        raise ErroWiki("O link precisa ser de uma página de Wiki (…/wiki/Nome).")
    prefixo = m.group(1) or ""
    titulo = urllib.parse.unquote(m.group(2)).replace("_", " ")
    origem = f"{p.scheme or 'https'}://{p.netloc}"
    return f"{origem}{prefixo}/api.php", titulo, origem + prefixo


def _api(base, **params):
    params.update(format="json", formatversion="2")
    url = base + "?" + urllib.parse.urlencode(params)
    ultimo = None
    for tentativa in range(4):
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                dados = json.loads(resposta.read().decode("utf-8"))
            time.sleep(PAUSA)
            return dados
        except urllib.error.HTTPError as erro:
            ultimo = erro
            if erro.code in (403, 404):
                break
        except Exception as erro:  # rede instável, resposta não-JSON (página de bloqueio)
            ultimo = erro
        time.sleep(2 * (tentativa + 1))
    raise ErroWiki(f"a API da Wiki não respondeu ({ultimo})")


def pagina(base, titulo):
    """HTML já pronto da página (seguindo redirecionamentos) e o título exibido."""
    d = _api(base, action="parse", page=titulo, prop="text|displaytitle", redirects=1,
             disableeditsection=1, disabletoc=1)
    if "error" in d:
        raise ErroWiki(d["error"].get("info", "página não encontrada"))
    p = d["parse"]
    return p.get("text", ""), _so_texto(p.get("displaytitle") or p.get("title") or titulo)


# ------------------------------------------------------- mini leitor HTML
class _No:
    __slots__ = ("tag", "attrs", "filhos", "pai")

    def __init__(self, tag, attrs=None, pai=None):
        self.tag, self.attrs, self.filhos, self.pai = tag, dict(attrs or {}), [], pai

    def texto(self):
        partes = []
        for f in self.filhos:
            if isinstance(f, str):
                partes.append(f)
            elif not f.ruido():
                partes.append(f.texto())
                if f.tag in ("p", "li", "br", "div", "tr", "h2", "h3"):
                    partes.append(" ")
        return "".join(partes)

    def ruido(self):
        return self.tag in RUIDO or bool(CLASSES_RUIDO.search(self.attrs.get("class", "") or ""))

    def todos(self, tags):
        for f in self.filhos:
            if isinstance(f, _No):
                if f.tag in tags:
                    yield f
                yield from f.todos(tags)


class _Arvore(HTMLParser):
    VAZIOS = {"br", "img", "hr", "meta", "link", "input", "wbr", "source", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _No("raiz")
        self.atual = self.raiz

    def handle_starttag(self, tag, attrs):
        no = _No(tag, attrs, self.atual)
        self.atual.filhos.append(no)
        if tag not in self.VAZIOS:
            self.atual = no

    def handle_endtag(self, tag):
        no = self.atual
        while no is not self.raiz and no.tag != tag:
            no = no.pai
        if no is not self.raiz:
            self.atual = no.pai

    def handle_data(self, data):
        self.atual.filhos.append(data)


def _arvore(html):
    a = _Arvore()
    a.feed(html or "")
    raiz = a.raiz
    # O conteúdo vem dentro de <div class="mw-parser-output">
    for no in raiz.todos({"div"}):
        if "mw-parser-output" in (no.attrs.get("class") or ""):
            return no
    return raiz


def _so_texto(html):
    """Tira as marcações e traduz códigos como &#039; (apóstrofo) e &amp; (&)."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html or "")).split())


def _limpar(texto):
    texto = re.sub(r"\[\s*\d+\s*\]", "", texto or "")  # notas de rodapé [1]
    return " ".join(texto.split()).strip()


def _nivel(no):
    """'h2'/'h3' para cabeçalhos (inclusive o formato novo <div class="mw-heading mw-heading2">)."""
    if not isinstance(no, _No):
        return None
    if no.tag in ("h2", "h3"):
        return no.tag
    m = re.search(r"mw-heading([23])", no.attrs.get("class", "") or "")
    return f"h{m.group(1)}" if no.tag == "div" and m else None


def _cabecalho(no):
    return _nivel(no) is not None


def _nome_cabecalho(no):
    ids = [no.attrs.get("id", "")] + [f.attrs.get("id", "") for f in no.todos({"span", "h2", "h3"})]
    return _limpar(no.texto()), [i for i in ids if i]


def _secao(raiz, combina, parar_em=("h2", "h3")):
    """Nós depois do cabeçalho cujo nome combina, até o próximo cabeçalho."""
    irmaos = raiz.filhos
    for i, no in enumerate(irmaos):
        if not _cabecalho(no):
            continue
        nome, ids = _nome_cabecalho(no)
        if combina(nome, ids):
            saida = []
            for prox in irmaos[i + 1:]:
                if _nivel(prox) in parar_em:
                    break
                saida.append(prox)
            return saida
    return None


# ------------------------------------------------------------- episódios
def _link_wiki(a, origem, titulo_atual):
    href = a.attrs.get("href") or ""
    if not href or href.startswith("#"):
        return None
    u = urllib.parse.urlparse(urllib.parse.urljoin(origem + "/", href))
    m = re.match(r"^(?:/[a-z-]+)?/wiki/(.+)$", u.path)
    if not m or u.fragment and not m.group(1):
        return None
    nome = urllib.parse.unquote(m.group(1)).replace("_", " ")
    if ESPECIAL.match(nome) or nome == titulo_atual or "redlink=1" in (u.query or ""):
        return None
    return {"texto": _limpar(a.texto()), "url": f"{u.scheme}://{u.netloc}{u.path}", "titulo": nome}


def _links(nos, origem, titulo):
    saida = []
    for no in nos:
        if isinstance(no, _No) and not no.ruido():
            for a in no.todos({"a"}):
                if any(isinstance(p, _No) and p.ruido() for p in _ancestrais(a)):
                    continue
                item = _link_wiki(a, origem, titulo)
                if item:
                    saida.append(item)
    return saida


def _ancestrais(no):
    while no.pai is not None:
        no = no.pai
        yield no


def _maior_lista(nos, origem, titulo):
    """Maior lista (li/tr) — cada item é um episódio, na ordem."""
    grupos = {}
    for no in nos:
        if not isinstance(no, _No):
            continue
        itens = ([no] if no.tag in ("li", "tr") else []) + list(no.todos({"li", "tr"}))
        for c in itens:
            if c.ruido() or any(p.ruido() for p in _ancestrais(c)):
                continue
            link = next((x for x in (_link_wiki(a, origem, titulo) for a in c.todos({"a"})) if x), None)
            if link:
                grupos.setdefault(id(c.pai), []).append(link)
    melhor = max(grupos.values(), key=len, default=[])
    vistos, saida = set(), []
    for item in melhor:
        if item["url"] not in vistos:
            vistos.add(item["url"])
            saida.append(item)
    return saida


def descobrir(url, coletor, avisar):
    """Lista de episódios [{numero, url, texto, titulo}] da página da série."""
    base, titulo, origem = separar(url)
    avisar("log", texto="Lendo a lista de episódios pela API da Wiki (sem navegador)...")
    html, _ = pagina(base, titulo)
    raiz = _arvore(html)
    secao = _secao(raiz, lambda n, ids: bool(SECAO_EPISODIOS.match(n)) or
                   any(re.match(r"^(episodes|episode_list)$", i, re.I) for i in ids),
                   parar_em=("h2",))
    if secao:
        eps = coletor.filtrar_episodios(_links(secao, origem, titulo))
        if len(eps) >= 2:
            return _com_titulo(eps), base
        lista = _maior_lista(secao, origem, titulo)
        if len(lista) >= 5:
            avisar("log", texto=f"Episódios sem número no nome: usando a ordem da lista ({len(lista)} itens).")
            return _com_titulo(coletor.por_posicao(lista)), base
        # A lista está em outro artigo ("List of … episodes")
        artigo = next((i for i in _links(secao, origem, titulo)
                       if re.search(r"episod", i["titulo"] + " " + i["texto"], re.I)), None)
        if artigo:
            avisar("log", texto="A lista está em outro artigo. Lendo a página de episódios...")
            html2, _ = pagina(base, artigo["titulo"])
            todos = _links([_arvore(html2)], origem, artigo["titulo"])
            eps = coletor.filtrar_episodios(todos)
            if len(eps) >= 2:
                return _com_titulo(eps), base
    eps = coletor.filtrar_episodios(_links([raiz], origem, titulo))
    return (_com_titulo(eps), base) if len(eps) >= 2 else ([], base)


def _com_titulo(eps):
    for e in eps:
        if not e.get("titulo"):
            caminho = urllib.parse.urlparse(e["url"]).path
            e["titulo"] = urllib.parse.unquote(caminho.split("/wiki/", 1)[-1]).replace("_", " ")
    return eps


def _texto_secao(raiz, nomes):
    nomes = [n.casefold() for n in nomes]

    def combina(nome, ids):
        n = nome.casefold()
        return any(n == x or n.startswith(x + "[") or n.startswith(x + " (") or
                   any(i.casefold() == x for i in ids) for x in nomes)
    nos = _secao(raiz, combina)
    if not nos:
        return ""
    partes = []
    for no in nos:
        if isinstance(no, str):
            partes.append(no)
        elif not no.ruido() and no.tag not in ("table",):
            partes.append(no.texto())
    return _limpar(" ".join(partes))


LIMITE_PLOT = 1000


def cortar_plot(texto, limite=LIMITE_PLOT):
    """O enredo completo pode ter milhares de letras; para virar sinopse basta o começo
    (a premissa). Corta no fim de uma frase, perto do limite."""
    if len(texto) <= limite:
        return texto
    trecho = texto[:limite]
    fim = max(trecho.rfind(". "), trecho.rfind("! "), trecho.rfind("? "))
    return (trecho[:fim + 1] if fim > limite * 0.5 else trecho.rsplit(" ", 1)[0] + "…").strip()


def limpar_titulo(titulo, numero):
    """Tira só os prefixos genéricos ("Ep. 1:", "Episode 1:", "Final Ep.:")."""
    titulo = re.sub(rf"^\s*(?:ep|episode|epis[oó]dio)\.?\s*{numero}\s*[:.\-–—]\s*", "", titulo, flags=re.I)
    titulo = re.sub(r"^\s*(?:final\s+(?:ep\.?|episode)|epis[oó]dio\s+final)\s*[:.\-–—]?\s*", "",
                    titulo, flags=re.I)
    return _limpar(titulo)


def ler_episodio(base, ep):
    """(título, sinopse, veio_do_plot) de um episódio."""
    html, exibido = pagina(base, ep["titulo"])
    raiz = _arvore(html)
    from nucleo import texto_util  # aqui dentro para não haver importação circular
    # Seção que só diz "To be added" conta como vazia: aí passa para a próxima.
    sinopse = (texto_util(_texto_secao(raiz, ["synopsis", "sinopse", "sinopsis"]), "sinopse") or
               texto_util(_texto_secao(raiz, ["summary", "sumário", "sumario", "resumo", "resumen"]), "sinopse"))
    do_plot = False
    if not sinopse:
        sinopse = cortar_plot(texto_util(_texto_secao(raiz, ["plot", "enredo", "story", "história"]), "sinopse"))
        do_plot = bool(sinopse)
    return limpar_titulo(exibido or ep.get("texto", ""), ep["numero"]), sinopse, do_plot
