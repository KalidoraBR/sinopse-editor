"""Parte "sem tela" do Sentai Studio: busca, extração, tradução (copiar/colar),
planilhas e envio ao TMDB. A interface (web ou antiga) só chama estas funções.

Funções longas recebem `avisar(tipo, **dados)` para contar o progresso e
`deve_parar()` para saber se o usuário clicou em Parar.
"""
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

from automatizador import AppTMDB, PASTA, STORAGE
from extrator import AppColetorWiki, ENDERECO_CDP, esperar_verificacao
import wiki_api
from instrucoes import MARCA_EPISODIOS, carregar_instrucoes

ARQUIVO_TRABALHO = PASTA / "trabalho_em_andamento.json"
ARQUIVO_CONFIG = PASTA / "config.json"
NOMES_IDIOMA = {"pt-BR": "português do Brasil", "pt-PT": "português de Portugal"}
COLUNAS_CSV = ["codigo_tmdb", "temporada", "episodio", "titulo", "sinopse"]
MODELO_CSV = [
    COLUNAS_CSV,
    ["1399", "1", "1", "Título do episódio 1", "Sinopse do episódio 1."],
    ["1399", "1", "2", "Título do episódio 2", "Sinopse do episódio 2."],
    ["1399", "2", "1", "Título do episódio 1 da temporada 2", "Sinopse."],
]
SINAIS_BLOQUEIO = re.compile(
    r"just a moment|attention required|access denied|verify you are human|"
    r"checking your browser|are you a robot|um momento|verifica[çc][ãa]o de seguran[çc]a", re.I)
# Marcas dos episódios no texto para tradução: [5], [T2-E5] ou [1399-T2-E5].
PADRAO_MARCA = (r"\[\s*(?:\d+\s*-\s*)?(?:T\s*\d+\s*-\s*)?E?\s*\d+\s*\]"
                r"|\[\s*(?:\d+\s*-\s*)?S[ÉE]RIE\s*\]")
POSTER = "https://image.tmdb.org/t/p/w185"


class Coletor:
    """Usa as rotinas de coleta do Extrator sem precisar da tela dele."""

    def __init__(self, avisar):
        self.avisar = avisar

    def enviar(self, tipo, valor=None):
        if tipo == "log":
            self.avisar("log", texto=valor)


for _nome in ("anchors", "filtrar_episodios", "descobrir_episodios", "extrair_secao",
              "lista_principal", "por_posicao",
              "extrair_titulo", "garantir_chrome_coleta", "extrair_temporada_tmdb",
              "limpar", "numero_episodio", "porta_chrome_aberta", "localizar_chrome"):
    setattr(Coletor, _nome, AppColetorWiki.__dict__[_nome])

achar_titulo = AppTMDB.achar_campo_titulo
achar_sinopse = AppTMDB.achar_campo_sinopse
salvar_e_confirmar = AppTMDB.salvar_e_confirmar
valor_valido = AppTMDB.valor_valido
esta_logado = AppTMDB.esta_logado
fechar_cookies = AppTMDB.fechar_cookies


# ============================================================== utilidades
def sem_leia_mais(texto):
    """Remove o link "Saiba mais"/"Read more" que o TMDB põe no fim da sinopse."""
    return re.sub(r"\s*(?:Saiba mais|Leia mais|Read more|Ler mais)\s*\.?\s*$", "", texto,
                  flags=re.I)


# Mensagens que o TMDB mostra quando o episódio não tem texto no idioma.
SINOPSE_GENERICA = re.compile(
    r"we don.t have an overview|help us expand our database|n[aã]o temos uma sinopse|"
    r"ajude.nos a expandir|no overview", re.I)
TITULO_GENERICO = re.compile(
    r"^\s*(?:(?:epis[oó]dio|episode|ep\.?)\s*\d+|unknown|tba|tbd|untitled)\s*$", re.I)


# Textos provisórios que Wikis e sites deixam no lugar da sinopse/título que ainda
# não existe ("To be added", "TBA"...), inclusive já traduzidos. Contam como vazio.
TEXTO_PROVISORIO = re.compile(
    r"^\W*(?:(?:synopsis|summary|plot|description|overview|sinopse|resumo|enredo|sinopsis)\s*"
    r"(?:is\s*|será\s*|ser[aá]\s*)?)?"
    r"(?:to\s*be\s*(?:added|announced|determined|confirmed|written)|tba|tbd|tbc|n/?a|"
    r"coming\s*soon|no\s*(?:synopsis|summary|plot|description)(?:\s*(?:yet|available))?|"
    r"(?:not\s*)?available\s*soon|under\s*construction|unknown|"
    r"a\s*ser\s*(?:adicionad[oa]|anunciad[oa]|definid[oa]|escrit[oa])|em\s*breve|"
    r"por\s*(?:adicionar|anunciar|definir)|sem\s*sinopse|desconhecid[oa]|"
    r"por\s*a[ñn]adir|pr[oó]ximamente|sin\s*sinopsis)"
    r"(?:\s*(?:yet|ainda|a[uú]n))?\W*$", re.I)


def provisorio(texto):
    """True se o texto for só um aviso provisório (ex.: "To be added.")."""
    texto = (texto or "").strip()
    return bool(texto) and len(texto) <= 80 and bool(TEXTO_PROVISORIO.match(texto))


def limpar_provisorios(ep):
    """Lista salva antes destas correções: troca códigos como &#039; pelo caractere certo
    (sem mexer na situação) e tira textos provisórios ("To be added"), deixando o
    episódio desmarcado como "Sem sinopse"/"Sem texto". Devolve True se mudou algo."""
    import html as _html
    mudou = provisorio_achado = False
    for chave in ("titulo", "sinopse", "original_titulo", "original_sinopse"):
        valor = ep.get(chave) or ""
        if "&" in valor and re.search(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", valor, re.I):
            ep[chave] = _html.unescape(valor)
            mudou = True
    for campo in ("titulo", "sinopse"):
        if provisorio(ep.get(f"original_{campo}")):
            ep[f"original_{campo}"] = ""
            provisorio_achado = True
        if provisorio(ep.get(campo)):
            ep[campo] = ""
            provisorio_achado = True
    if provisorio_achado and ep.get("situacao") not in ("Enviado", "Já preenchido"):
        ep["situacao"] = "Original"
        ep["enviar"] = True
        classificar_original(ep)
    return mudou or provisorio_achado


def texto_util(texto, campo):
    """Devolve o texto, ou "" se for vazio ou só a mensagem/título automático do TMDB."""
    texto = sem_leia_mais((texto or "").strip())
    if not valor_valido(texto) or provisorio(texto):
        return ""
    if campo == "sinopse" and SINOPSE_GENERICA.search(texto):
        return ""
    if campo == "titulo" and TITULO_GENERICO.match(texto):
        return ""
    return texto


def classificar_original(ep):
    """Episódio sem texto original não serve para traduzir: vem desmarcado."""
    titulo, sinopse = ep.get("original_titulo", ""), ep.get("original_sinopse", "")
    if ep.get("tipo") in ("temporada", "serie"):
        if not sinopse:
            ep.update(situacao="Sem sinopse", enviar=False)
        return ep
    if not titulo and not sinopse:
        ep.update(situacao="Sem texto", enviar=False)
    elif not sinopse:
        ep.update(situacao="Sem sinopse", enviar=False)
    return ep


def ja_preenchido(valor):
    """True se o campo do TMDB já tem texto de verdade.

    Títulos automáticos do próprio TMDB ("Episódio 3", "Episode 3") contam como vazios.
    """
    valor = (valor or "").strip()
    return bool(valor) and not re.fullmatch(r"(?:epis[oó]dio|episode|ep\.?)\s*\d+", valor, re.I)


def interpretar_temporadas(texto, disponiveis):
    """ "todas" (ou vazio) -> todas menos os especiais (0); "1-3, 5" -> [1, 2, 3, 5]."""
    texto = (texto or "").strip().casefold()
    if texto in ("", "todas", "todos", "all", "*"):
        normais = [n for n in disponiveis if n != 0]
        return normais or list(disponiveis)
    escolhidas = set()
    for parte in re.split(r"[,;\s]+", texto):
        if not parte:
            continue
        if "-" in parte:
            inicio, fim = parte.split("-", 1)
            if not (inicio.isdigit() and fim.isdigit()):
                raise ValueError(f"não entendi as temporadas “{texto}”")
            escolhidas.update(range(int(inicio), int(fim) + 1))
        elif parte.isdigit():
            escolhidas.add(int(parte))
        else:
            raise ValueError(f"não entendi as temporadas “{texto}”")
    return sorted(escolhidas)


def normalizar_marca(marca):
    return re.sub(r"\s+", "", marca).upper().replace("É", "E")


def ler_config():
    try:
        return json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar_config(config):
    ARQUIVO_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=1),
                              encoding="utf-8")


@contextmanager
def abrir_navegador(visivel, login=None):
    """Abre o Chrome (oculto ou visível) e entrega uma aba pronta para uso."""
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=not visivel)
        versao = navegador.version.split(".")[0]
        contexto = navegador.new_context(
            storage_state=str(login) if login else None,
            viewport={"width": 1366, "height": 900},
            # Sem "HeadlessChrome" na identificação, alguns sites bloqueiam menos.
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        f"(KHTML, like Gecko) Chrome/{versao}.0.0.0 Safari/537.36"))
        try:
            yield contexto.new_page()
        finally:
            navegador.close()


# ============================================================ API do TMDB
class ErroAPI(Exception):
    pass


class TMDB:
    """Leitura de dados pela API oficial do TMDB (pôsteres, nomes, episódios).

    Aceita a "Chave da API" (v3) ou o "Token de leitura" (v4, começa com eyJ).
    """
    BASE = "https://api.themoviedb.org/3"

    def __init__(self, chave):
        self.chave = (chave or "").strip()

    def _get(self, caminho, **params):
        cabecalhos = {"Accept": "application/json"}
        if self.chave.startswith("eyJ"):
            cabecalhos["Authorization"] = f"Bearer {self.chave}"
        else:
            params["api_key"] = self.chave
        url = f"{self.BASE}{caminho}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=cabecalhos),
                                        timeout=20) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            if erro.code == 401:
                raise ErroAPI("a chave da API do TMDB não foi aceita") from None
            if erro.code == 404:
                raise ErroAPI("não encontrado no TMDB") from None
            raise ErroAPI(f"o TMDB respondeu com erro {erro.code}") from None
        except OSError as erro:
            raise ErroAPI(f"sem conexão com o TMDB ({erro})") from None

    def testar(self):
        self._get("/configuration")
        return True

    def buscar(self, nome):
        dados = self._get("/search/tv", query=nome, language="pt-BR")
        return [{"codigo": str(s["id"]), "nome": s.get("name") or s.get("original_name"),
                 "original": s.get("original_name") or "",
                 "ano": (s.get("first_air_date") or "")[:4],
                 "poster": POSTER + s["poster_path"] if s.get("poster_path") else ""}
                for s in dados.get("results", [])[:8]]

    def serie(self, codigo):
        s = self._get(f"/tv/{codigo}", language="en-US")
        return {"codigo": str(codigo), "nome": s.get("name") or s.get("original_name") or "",
                "ano": (s.get("first_air_date") or "")[:4],
                "poster": POSTER + s["poster_path"] if s.get("poster_path") else "",
                "temporadas": [{"numero": t["season_number"],
                                "episodios": t.get("episode_count", 0),
                                "poster": POSTER + t["poster_path"] if t.get("poster_path")
                                else ""}
                               for t in s.get("seasons", [])]}

    def sinopse_temporada(self, codigo, numero, idioma="en-US"):
        return self._get(f"/tv/{codigo}/season/{numero}", language=idioma).get("overview") or ""

    def temporada(self, codigo, numero, idioma="en-US"):
        t = self._get(f"/tv/{codigo}/season/{numero}", language=idioma)
        return [{"numero": e["episode_number"], "titulo": e.get("name") or "",
                 "sinopse": e.get("overview") or ""} for e in t.get("episodes", [])]


def idiomas_temporada(codigo, temporada, destino="pt-BR"):
    """Pela API: em quais idiomas a temporada tem título e sinopse, episódio por
    episódio. O idioma de destino (o da tradução) fica de fora."""
    api = tmdb_configurado()
    if not api:
        raise ErroAPI("Cadastre a chave da API nas Configurações.")
    lista = api._get(f"/tv/{codigo}/translations").get("translations", [])
    vistos, idiomas = set(), []
    for t in lista:
        cod = f"{t.get('iso_639_1', '')}-{t.get('iso_3166_1', '')}".strip("-")
        if not cod or cod in vistos or cod == destino:
            continue
        vistos.add(cod)
        idiomas.append({"codigo": cod, "nome": t.get("name") or t.get("english_name") or cod,
                        "nome_en": t.get("english_name") or ""})
    if not any(i["codigo"].startswith("en") for i in idiomas):
        idiomas.insert(0, {"codigo": "en-US", "nome": "English", "nome_en": "English"})
    total, saida = 0, []
    for i in idiomas[:30]:
        try:
            eps = api.temporada(codigo, temporada, i["codigo"])
        except ErroAPI:
            continue
        total = max(total, len(eps))
        titulos = [e["numero"] for e in eps if texto_util(e["titulo"], "titulo")]
        sinopses = [e["numero"] for e in eps if texto_util(e["sinopse"], "sinopse")]
        if titulos or sinopses:
            saida.append(dict(i, titulos=titulos, sinopses=sinopses))
    # Inglês primeiro; o resto do mais completo para o menos completo.
    saida.sort(key=lambda i: (not i["codigo"].startswith("en"), -(len(i["titulos"]) + len(i["sinopses"]))))
    return {"total": total, "idiomas": saida}


def episodios_tmdb_idiomas(codigo, temporada, ordem, destino="pt-BR", com_temporada=False):
    """Como episodios_tmdb, mas em vários idiomas: cada título e cada sinopse vem do
    primeiro idioma da `ordem` que tiver o texto (ex.: inglês, e o que faltar, espanhol)."""
    api = tmdb_configurado()
    por_idioma = {cod: {e["numero"]: e for e in api.temporada(codigo, temporada, cod)} for cod in ordem}
    try:
        atuais = {e["numero"]: e for e in api.temporada(codigo, temporada, destino)}
    except ErroAPI:
        atuais = {}
    numeros = sorted({n for eps in por_idioma.values() for n in eps})
    saida = []
    for n in numeros:
        titulo = sinopse = ""
        de_titulo = de_sinopse = ""
        for cod in ordem:
            e = por_idioma[cod].get(n, {})
            if not titulo and texto_util(e.get("titulo", ""), "titulo"):
                titulo, de_titulo = texto_util(e["titulo"], "titulo"), cod
            if not sinopse and texto_util(e.get("sinopse", ""), "sinopse"):
                sinopse, de_sinopse = texto_util(e["sinopse"], "sinopse"), cod
        atual = atuais.get(n, {})
        saida.append(classificar_original({
            "numero": n, "titulo": titulo, "sinopse": sinopse,
            "original_titulo": titulo, "original_sinopse": sinopse,
            "idioma_titulo": de_titulo, "idioma_sinopse": de_sinopse,
            "atual_titulo": texto_util(atual.get("titulo", ""), "titulo"),
            "atual_sinopse": texto_util(atual.get("sinopse", ""), "sinopse"),
            "via_api": True}))
    if com_temporada:
        original = de = ""
        for cod in ordem:
            texto = texto_util(api.sinopse_temporada(codigo, temporada, cod), "sinopse")
            if texto:
                original, de = texto, cod
                break
        try:
            atual = texto_util(api.sinopse_temporada(codigo, temporada, destino), "sinopse")
        except ErroAPI:
            atual = ""
        saida.insert(0, classificar_original({
            "numero": 0, "tipo": "temporada", "titulo": "", "sinopse": original,
            "original_titulo": "", "original_sinopse": original, "idioma_sinopse": de,
            "atual_titulo": "", "atual_sinopse": atual, "via_api": True}))
    return saida


def itens_pagina_serie(codigo, temporada, destino="pt-BR"):
    """Itens da página da série para o topo da temporada: nome + sinopse da série e a
    sinopse da temporada (originais em inglês), com o que o TMDB já tem em `destino`.
    Vêm MARCADOS só se a série ainda não tem tradução nesse idioma (sem ela o TMDB não
    deixa editar os episódios); senão vêm desmarcados, para você decidir.
    Devolve (itens, tem_traducao)."""
    api = tmdb_configurado()
    if not api:
        return [], True
    lingua, pais = (destino.split("-") + [""])[:2]
    traducoes = api._get(f"/tv/{codigo}/translations").get("translations", [])
    atual = next((t.get("data", {}) for t in traducoes if t.get("iso_639_1") == lingua
                  and (not pais or t.get("iso_3166_1") == pais)), None)
    tem = atual is not None
    s = api._get(f"/tv/{codigo}", language="en-US")
    nome, sinopse = s.get("name") or s.get("original_name") or "", texto_util(s.get("overview"), "sinopse")
    serie = classificar_original({
        "numero": -1, "tipo": "serie", "titulo": nome, "sinopse": sinopse,
        "original_titulo": nome, "original_sinopse": sinopse,
        "atual_titulo": (atual or {}).get("name", "") or "",
        "atual_sinopse": texto_util((atual or {}).get("overview", ""), "sinopse"), "via_api": True})
    itens = [serie]
    try:
        sin_t = texto_util(api.sinopse_temporada(codigo, temporada, "en-US"), "sinopse")
    except ErroAPI:
        sin_t = ""
    if sin_t:
        try:
            atual_t = texto_util(api.sinopse_temporada(codigo, temporada, destino), "sinopse") if tem else ""
        except ErroAPI:
            atual_t = ""
        itens.append(classificar_original({
            "numero": 0, "tipo": "temporada", "titulo": "", "sinopse": sin_t,
            "original_titulo": "", "original_sinopse": sin_t, "atual_titulo": "",
            "atual_sinopse": atual_t, "via_api": True}))
    for item in itens:
        if tem and item.get("situacao") not in ("Sem sinopse", "Sem texto"):
            item["enviar"] = False  # já tem português: fica à sua escolha
    return itens, tem


def tmdb_configurado():
    chave = ler_config().get("chave_tmdb", "")
    return TMDB(chave) if chave else None


# ========================================================= série e coleta
def buscar_info_serie_site(pagina, codigo):
    """Nome, ano e temporadas lidos da página do TMDB (quando não há chave da API)."""
    pagina.goto(f"https://www.themoviedb.org/tv/{codigo}?language=en-US",
                wait_until="domcontentloaded", timeout=60000)
    info = pagina.evaluate("""() => {
        const nome = document.querySelector('.title h2 a, section.header h2 a, h2 a');
        const ano = document.querySelector('.title .release_date, span.release_date');
        const img = document.querySelector('.poster img, img.poster');
        return {nome: nome ? nome.textContent.trim() : '',
                ano: ano ? ano.textContent.trim() : '',
                poster: img ? (img.currentSrc || img.src || '') : ''};
    }""")
    pagina.goto(f"https://www.themoviedb.org/tv/{codigo}/seasons?language=en-US",
                wait_until="domcontentloaded", timeout=60000)
    hrefs = pagina.locator("a[href*='/season/']").evaluate_all(
        "els => els.map(e => e.getAttribute('href') || '')")
    temporadas = sorted({int(m.group(1)) for h in hrefs
                         if (m := re.search(rf"/tv/{codigo}[^/]*/season/(\d+)", h))})
    ano = re.search(r"\d{4}", info["ano"])
    return {"codigo": str(codigo), "nome": info["nome"], "ano": ano.group(0) if ano else "",
            "poster": info["poster"],
            "temporadas": [{"numero": n, "episodios": 0, "poster": ""} for n in temporadas]}


def info_serie(codigo, visivel, pagina=None):
    """Usa a API quando há chave; senão, lê a página do site."""
    api = tmdb_configurado()
    if api:
        return api.serie(codigo)
    if pagina is not None:
        return buscar_info_serie_site(pagina, codigo)
    with abrir_navegador(visivel) as nova:
        return buscar_info_serie_site(nova, codigo)


def episodios_tmdb(codigo, temporada, visivel, avisar, pagina=None, com_temporada=False):
    """Textos em inglês de uma temporada; com a API, também o que já existe em pt-BR."""
    api = tmdb_configurado()
    if api:
        originais = api.temporada(codigo, temporada, "en-US")
        try:
            atuais = {e["numero"]: e for e in api.temporada(codigo, temporada, "pt-BR")}
        except ErroAPI:
            atuais = {}
        saida = []
        for e in originais:
            atual = atuais.get(e["numero"], {})
            titulo, sinopse = texto_util(e["titulo"], "titulo"), texto_util(e["sinopse"], "sinopse")
            saida.append(classificar_original({
                "numero": e["numero"], "titulo": titulo, "sinopse": sinopse,
                "original_titulo": titulo, "original_sinopse": sinopse,
                "atual_titulo": texto_util(atual.get("titulo", ""), "titulo"),
                "atual_sinopse": texto_util(atual.get("sinopse", ""), "sinopse"),
                "via_api": True}))
        if com_temporada:
            # Opcional: a sinopse da própria temporada entra como item "0".
            original = texto_util(api.sinopse_temporada(codigo, temporada, "en-US"), "sinopse")
            try:
                atual = texto_util(api.sinopse_temporada(codigo, temporada, "pt-BR"), "sinopse")
            except ErroAPI:
                atual = ""
            saida.insert(0, classificar_original({
                "numero": 0, "tipo": "temporada", "titulo": "", "sinopse": original,
                "original_titulo": "", "original_sinopse": original,
                "atual_titulo": "", "atual_sinopse": atual, "via_api": True}))
        return saida

    def ler(pg):
        itens = Coletor(avisar).extrair_temporada_tmdb(
            pg, f"https://www.themoviedb.org/tv/{codigo}/season/{temporada}?language=en-US")
        return [{"numero": i["episodio"], "titulo": texto_util(i["titulo"], "titulo"),
                 "sinopse": texto_util(i["sinopse"], "sinopse")} for i in itens]
    if pagina is not None:
        lidos = ler(pagina)
    else:
        with abrir_navegador(visivel) as nova:
            lidos = ler(nova)
    for e in lidos:
        e["original_titulo"], e["original_sinopse"] = e["titulo"], e["sinopse"]
        classificar_original(e)
    return lidos


# O que não precisa carregar para ler o texto da Wiki (deixa cada página bem mais leve).
_TIPOS_PESADOS = {"image", "media", "font"}
_ANUNCIOS = re.compile(r"doubleclick|googlesyndication|googletagmanager|google-analytics|"
                       r"amazon-adsystem|adnxs|criteo|taboola|outbrain|scorecardresearch|"
                       r"quantserve|moatads|pubmatic|rubiconproject|openx|indexww|casalemedia|"
                       r"nativo|jwplayer|jwpcdn|connatix|beacon|/ads?[/.?]", re.I)


def _aliviar(pagina):
    """Bloqueia imagens, vídeos, fontes e anúncios nessa aba."""
    def filtro(rota):
        pedido = rota.request
        if pedido.resource_type in _TIPOS_PESADOS or _ANUNCIOS.search(pedido.url):
            return rota.abort()
        return rota.continue_()
    try:
        pagina.route("**/*", filtro)
    except Exception:
        pass
    return pagina


def _ler_wiki(pagina, url, coletor, avisar, deve_parar, apenas=None):
    """Lê os episódios; devolve None se o site bloquear o acesso.
    `apenas`: números dos episódios a ler (o Complementar não relê a temporada toda)."""
    _aliviar(pagina)
    episodios = coletor.descobrir_episodios(pagina, url)
    if episodios and apenas:
        episodios = [e for e in episodios if e["numero"] in apenas]
        if not episodios:
            return []
    if not episodios:
        texto = (pagina.title() or "") + " " + pagina.locator("body").inner_text()[:2000]
        return None if SINAIS_BLOQUEIO.search(texto) else []
    resultado = []
    total = len(episodios)
    for i, ep in enumerate(episodios, 1):
        if deve_parar():
            break
        avisar("progresso", atual=i, total=total,
               texto=f"Lendo episódio {ep['numero']} da Wiki ({i} de {total})")
        if i > 1 and i % 15 == 1:
            # Uma aba aberta por muito tempo vai acumulando memória e fica lenta: troca por uma nova.
            try:
                nova = _aliviar(pagina.context.new_page())
                pagina.unroute_all(behavior="ignoreErrors")
                pagina.close()
                pagina = nova
            except Exception:
                pass
        try:
            for tentativa in range(3):
                pagina.goto(ep["url"], wait_until="domcontentloaded", timeout=60000)
                if esperar_verificacao(pagina):
                    break
                avisar("log", texto=f"Episódio {ep['numero']}: o site pediu verificação; "
                                    "esperando e tentando de novo...")
                pagina.wait_for_timeout(5000 * (tentativa + 1))
            else:
                raise RuntimeError("a verificação de segurança do site não terminou")
            pagina.wait_for_timeout(600)
            do_plot = False
            sinopse = (texto_util(coletor.extrair_secao(pagina, ["synopsis", "sinopse", "sinopsis"]), "sinopse")
                       or texto_util(coletor.extrair_secao(pagina, ["summary", "sumário", "sumario",
                                                                    "resumo", "resumen"]), "sinopse"))
            if not sinopse:
                # Sem sinopse: usa o enredo completo (Plot); a IA vai resumir na tradução.
                sinopse = wiki_api.cortar_plot(texto_util(coletor.extrair_secao(pagina, ["plot", "enredo"]), "sinopse"))
                do_plot = bool(sinopse)
            titulo = coletor.extrair_titulo(pagina, ep)
        except Exception as erro:
            avisar("log", texto=f"Episódio {ep['numero']}: não consegui ler ({erro}).")
            titulo, sinopse, do_plot = "", "", False
        titulo, sinopse = texto_util(titulo, "titulo"), texto_util(sinopse, "sinopse")
        resultado.append(classificar_original({
            "numero": ep["numero"], "titulo": titulo, "sinopse": sinopse,
            "original_titulo": titulo, "original_sinopse": sinopse,
            "sinopse_do_plot": bool(do_plot and sinopse)}))
    return resultado


def _ler_wiki_api(url, coletor, avisar, deve_parar, apenas=None):
    """Caminho principal: a API da Wiki (api.php), sem navegador. None se não der."""
    try:
        episodios, base = wiki_api.descobrir(url, coletor, avisar)
    except wiki_api.ErroWiki as erro:
        avisar("log", texto=f"A API da Wiki não serviu ({erro}).")
        return None
    if not episodios:
        return None
    if apenas:
        episodios = [e for e in episodios if e["numero"] in apenas]
        if not episodios:
            return []
    resultado, total = [], len(episodios)
    for i, ep in enumerate(episodios, 1):
        if deve_parar():
            break
        avisar("progresso", atual=i, total=total,
               texto=f"Lendo episódio {ep['numero']} da Wiki ({i} de {total})")
        try:
            titulo, sinopse, do_plot = wiki_api.ler_episodio(base, ep)
        except wiki_api.ErroWiki as erro:
            avisar("log", texto=f"Episódio {ep['numero']}: não consegui ler ({erro}).")
            titulo, sinopse, do_plot = ep.get("texto", ""), "", False
        titulo, sinopse = texto_util(titulo, "titulo"), texto_util(sinopse, "sinopse")
        resultado.append(classificar_original({
            "numero": ep["numero"], "titulo": titulo, "sinopse": sinopse,
            "original_titulo": titulo, "original_sinopse": sinopse,
            "sinopse_do_plot": bool(do_plot and sinopse)}))
    return resultado


def fechar_chrome_coleta():
    """Fecha a janela do Chrome de coleta (perfil próprio do programa), se estiver aberta."""
    try:
        import subprocess
        comando = ("Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
                   "? { $_.CommandLine -like '*chrome_coletor_perfil*' } | "
                   "% { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
        subprocess.run(["powershell", "-NoProfile", "-Command", comando], timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def episodios_wiki(url, visivel, avisar, deve_parar, apenas=None):
    coletor = Coletor(avisar)
    resultado = _ler_wiki_api(url, coletor, avisar, deve_parar, apenas)
    if resultado is not None:
        return resultado
    # Reserva 1: navegador oculto.
    avisar("log", texto="Abrindo a página da Wiki no navegador oculto...")
    with abrir_navegador(visivel) as pagina:
        resultado = _ler_wiki(pagina, url, coletor, avisar, deve_parar, apenas)
    if resultado is None:
        # Reserva 2: o site bloqueou o modo oculto; usa a janela de coleta e fecha no fim.
        avisar("log", texto="O site bloqueou o modo oculto. Abrindo o navegador visível...")
        coletor.garantir_chrome_coleta()
        try:
            with sync_playwright() as p:
                navegador = p.chromium.connect_over_cdp(ENDERECO_CDP)
                contexto = navegador.contexts[0]
                pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
                resultado = _ler_wiki(pagina, url, coletor, avisar, deve_parar, apenas)
        finally:
            fechar_chrome_coleta()
    return resultado or []


# ======================================================= sugerir a Wiki
WIKIS_IGNORADAS = re.compile(r"//(soap|community|best-tv-shows|logos|tropedia|"
                             r"allthetropes|dubbing|international-entertainment-project)\.fandom",
                             re.I)


def sugerir_wikis(nome, visivel=False):
    """Procura a série na busca geral do Fandom e devolve os links mais prováveis."""
    nome = (nome or "").strip()
    if not nome:
        return []
    url = ("https://community.fandom.com/wiki/Special:Search?scope=cross-wiki&query="
           + urllib.parse.quote(nome))
    with abrir_navegador(visivel) as pagina:
        pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
        pagina.wait_for_timeout(2000)
        links = pagina.evaluate(r"""() => [...document.querySelectorAll('a[href]')].map(a => a.href)
            .filter(h => /\.fandom\.com\/(?:[a-z-]+\/)?wiki\/./.test(h))
            .filter((h, i, l) => l.indexOf(h) === i)""")
    alvo = re.sub(r"[^a-z0-9]+", "", nome.casefold())
    sugestoes = []
    for link in links:
        if WIKIS_IGNORADAS.search(link) or re.search(r"/wiki/[^/]*:", link):
            continue
        titulo = urllib.parse.unquote(link.rsplit("/wiki/", 1)[-1]).replace("_", " ")
        wiki = re.search(r"//([^.]+)\.fandom", link).group(1)
        chave = re.sub(r"[^a-z0-9]+", "", titulo.casefold())
        nota = 0 if chave == alvo else (1 if alvo in chave or chave in alvo else 2)
        sugestoes.append({"url": link, "titulo": titulo, "wiki": wiki, "nota": nota})
    sugestoes.sort(key=lambda s: s["nota"])
    return sugestoes[:6]


# ================================================================== TVDB
# Só leitura das páginas públicas, devagar (uso pessoal, sem a API paga).
PAUSA_TVDB = (1.5, 2.5)  # segundos entre uma página e outra


def slug_tvdb(link):
    """Aceita o link da série no TVDB (ou só o nome curto) e devolve o nome curto."""
    link = (link or "").strip()
    achado = re.search(r"thetvdb\.com/series/([^/?#]+)", link, re.I)
    if achado:
        return achado.group(1)
    return link if re.fullmatch(r"[a-z0-9-]+", link, re.I) else ""


def eh_tvdb(link):
    return "thetvdb.com" in (link or "").lower()


def _pausa_tvdb(pagina):
    import random
    pagina.wait_for_timeout(int(random.uniform(*PAUSA_TVDB) * 1000))


class InstavelTVDB(Exception):
    pass


def _abrir_tvdb(pagina, url, seletor=None, avisar=None, tentativas=4):
    """Abre uma página do TVDB. O servidor dele às vezes responde 502/504: nesse caso
    espera um pouco (cada vez mais) e tenta de novo."""
    for n in range(1, tentativas + 1):
        try:
            resposta = pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = resposta.status if resposta else 0
        except Exception:
            status = 0
        titulo = pagina.title() or ""
        if status >= 500 or status == 0 or re.search(r"gateway|bad gateway|time-?out", titulo, re.I):
            if avisar:
                avisar("log", texto=f"TVDB instável (tentativa {n} de {tentativas}), "
                                    "esperando para tentar de novo...")
            pagina.wait_for_timeout(4000 * n)
            continue
        texto = titulo + " " + pagina.locator("body").inner_text()[:1500]
        if SINAIS_BLOQUEIO.search(texto):
            raise ErroAPI("o TVDB pediu verificação (bloqueio temporário). Tente mais tarde ou "
                          "ligue “Mostrar navegador”")
        if seletor:
            try:
                pagina.wait_for_selector(seletor, state="attached", timeout=10000)
            except Exception:
                pass
        return
    raise InstavelTVDB("o servidor do TVDB não respondeu")


def episodios_tvdb(link, temporada, visivel, avisar, deve_parar, apenas=None):
    """Títulos e sinopses em inglês de uma temporada do TVDB (numeração "oficial")."""
    slug = slug_tvdb(link)
    if not slug:
        raise ErroAPI("não reconheci o link do TVDB (ex.: https://thetvdb.com/series/nome-da-serie)")
    with abrir_navegador(visivel) as pagina:
        avisar("progresso", atual=0, total=0, texto=f"Abrindo a temporada {temporada} no TVDB...")
        try:
            _abrir_tvdb(pagina, f"https://thetvdb.com/series/{slug}/seasons/official/{temporada}",
                        "table tbody tr", avisar)
        except InstavelTVDB:
            raise ErroAPI("o servidor do TVDB está instável agora (erro 502/504 dele). "
                          "Tente de novo em alguns minutos") from None
        linhas = pagina.evaluate(r"""() => [...document.querySelectorAll('table tbody tr')]
            .map((tr) => {
                const cod = (tr.querySelector('td')?.textContent || '').trim();
                const a = tr.querySelector("a[href*='/episodes/']");
                return a ? {cod, url: a.href} : null;
            }).filter(Boolean)""")
        episodios = []
        for linha in linhas:
            achado = re.search(r"E(\d+)", linha["cod"], re.I)
            if achado:
                episodios.append({"numero": int(achado.group(1)), "url": linha["url"]})
        if apenas:
            episodios = [e for e in episodios if e["numero"] in apenas]
        if not episodios:
            return []
        resultado, falharam = [], []
        total = len(episodios)
        for i, ep in enumerate(episodios, 1):
            if deve_parar():
                avisar("log", texto="Importação do TVDB interrompida.")
                break
            avisar("progresso", atual=i, total=total,
                   texto=f"Lendo o episódio {ep['numero']} no TVDB ({i} de {total})")
            _pausa_tvdb(pagina)
            try:
                _abrir_tvdb(pagina, ep["url"], ".change_translation_text[data-language]", avisar)
                textos = pagina.evaluate(r"""() => {
                    const t = {};
                    document.querySelectorAll('.change_translation_text[data-language]').forEach((d) => {
                        t[d.getAttribute('data-language')] = {
                            titulo: d.getAttribute('data-title') || '',
                            sinopse: (d.innerText || d.textContent || '').trim()};
                    });
                    return t;
                }""")
            except ErroAPI:
                raise
            except InstavelTVDB:
                avisar("log", texto=f"TVDB, episódio {ep['numero']}: o servidor não respondeu "
                                    "depois de 4 tentativas. Ficou sem texto.")
                falharam.append(ep["numero"])
                textos = {}
            except Exception as erro:
                avisar("log", texto=f"TVDB, episódio {ep['numero']}: não consegui ler ({erro}).")
                falharam.append(ep["numero"])
                textos = {}
            ing = textos.get("eng", {})
            ref = {}
            for codigo_idioma, prefixo in (("pt", "ref_ptbr"), ("por", "ref_ptpt")):
                t = textos.get(codigo_idioma, {})
                ref[f"{prefixo}_titulo"] = texto_util(t.get("titulo", ""), "titulo")
                ref[f"{prefixo}_sinopse"] = texto_util(t.get("sinopse", ""), "sinopse")
            titulo = texto_util(ing.get("titulo", ""), "titulo")
            sinopse = texto_util(ing.get("sinopse", ""), "sinopse")
            resultado.append(classificar_original({
                "numero": ep["numero"], "titulo": titulo, "sinopse": sinopse,
                "original_titulo": titulo, "original_sinopse": sinopse, "fonte": "TVDB",
                **ref}))
        if falharam:
            avisar("aviso", texto=f"TVDB instável: {len(falharam)} episódio(s) ficaram sem texto "
                                  f"({', '.join(map(str, falharam))}). Importe de novo mais tarde.")
        return resultado


# ================================================================ planilha
def ler_planilha(caminho, padrao):
    """Lê o CSV; colunas codigo_tmdb/temporada vazias usam `padrao`."""
    linhas, ignoradas = [], 0
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        amostra = f.read(4096)
        f.seek(0)
        try:
            separador = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
        except csv.Error:
            separador = ";"
        for registro in csv.DictReader(f, delimiter=separador):
            registro = {(k or "").strip().casefold(): v for k, v in registro.items()}
            try:
                numero = int((registro.get("episodio") or "").strip())
            except ValueError:
                continue
            titulo = valor_valido(registro.get("titulo"))
            sinopse = next((v for v in (valor_valido(registro.get(c)) for c in
                                        ("sinopse", "synopsis", "plot")) if v), None)
            if not titulo and not sinopse:
                ignoradas += 1
                continue
            codigo = (registro.get("codigo_tmdb") or "").strip() or padrao.get("codigo", "")
            temporada = (registro.get("temporada") or "").strip() or padrao.get("temporada", "")
            linhas.append({"codigo": codigo, "temporada": temporada, "numero": numero,
                           "titulo": titulo or "", "sinopse": sinopse or ""})
    return linhas, ignoradas


def escrever_planilha(caminho, episodios):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
        escritor.writerow(COLUNAS_CSV)
        for e in episodios:
            escritor.writerow([e["codigo"], e["temporada"], e["numero"], e.get("titulo", ""),
                               e.get("sinopse", "")])


def escrever_modelo(caminho):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f, delimiter=";").writerows(MODELO_CSV)


# ============================================================== tradução
def _grupos(episodios):
    vistos = {}
    for e in episodios:
        vistos.setdefault((str(e["codigo"]), str(e["temporada"])), e)
    return vistos


def nome_grupo(e):
    nome = e.get("serie") or (f"Série {e['codigo']}" if e.get("codigo") else "Série sem código")
    ano = f" ({e['ano']})" if e.get("ano") else ""
    return f"{nome}{ano} · Temporada {e.get('temporada') or '?'}"


def marca(e, grupos):
    if e.get("tipo") == "serie":
        # Nome e sinopse da série inteira (página principal da série no TMDB).
        return "[SÉRIE]" if len({c for c, _ in grupos}) == 1 else f"[{e['codigo']}-SÉRIE]"
    if len(grupos) == 1:
        return f"[{e['numero']}]"
    if len({codigo for codigo, _ in grupos}) == 1:
        return f"[T{e['temporada']}-E{e['numero']}]"
    return f"[{e['codigo']}-T{e['temporada']}-E{e['numero']}]"


def _aviso_omitidos(omitidos):
    """Explica à IA quais episódios ficaram de fora, para ela não estranhar os saltos."""
    if not omitidos:
        return ""
    motivos = {}
    for e in omitidos:
        if e.get("situacao") in ("Enviado", "Já preenchido"):
            motivo = "já traduzidos/preenchidos no TMDB"
        elif e.get("situacao") in ("Sem texto", "Sem sinopse"):
            motivo = "sem texto original para traduzir"
        else:
            motivo = "não selecionados"
        motivos.setdefault((nome_grupo(e), motivo), []).append(e["numero"])
    linhas = "\n".join(f"- {grupo}: episódio(s) {', '.join(map(str, sorted(nums)))} ({motivo})"
                       for (grupo, motivo), nums in motivos.items())
    return ("\n\nEPISÓDIOS OMITIDOS DE PROPÓSITO\n"
            "Alguns episódios não estão na lista abaixo, então a numeração pode pular "
            "(por exemplo, do 5 para o 7). Isso é normal. Traduza somente os episódios "
            "listados: não crie os que faltam, não renumere e não comente a ausência.\n" + linhas)


def _aviso_plot(episodios, grupos):
    """Episódios cuja "sinopse" é o enredo completo (Plot) da Wiki: a IA deve resumir."""
    do_plot = [e for e in episodios if e.get("sinopse_do_plot")]
    if not do_plot:
        return ""
    marcas = ", ".join(marca(e, grupos) for e in do_plot)
    return ("\n\nENREDO PARA RESUMIR\nNos episódios " + marcas + " a Wiki não tinha sinopse: o "
            "texto em “Sinopse:” é o enredo completo do episódio (seção Plot), às vezes longo e "
            "cheio de detalhes. Nesses, não traduza tudo: escreva uma SINOPSE curta, no mesmo "
            "estilo das outras (2 a 3 frases, até 3 linhas), contando só a premissa do episódio, "
            "sem revelar o final nem reviravoltas. Mantenha os nomes próprios.")


def texto_para_traduzir(episodios, idioma, omitidos=None, glossarios=None):
    grupos = _grupos(episodios)
    trocas = {"{idioma}": NOMES_IDIOMA.get(idioma, idioma)}
    if len(grupos) == 1:
        e = next(iter(grupos.values()))
        temporada = str(e.get("temporada") or "")
        trocas.update({
            "{serie}": f"“{e.get('serie') or '(nome da série)'}”",
            "{ano}": f", de {e['ano']}" if e.get("ano") else "",
            "{temporada}": f", temporada {temporada}" if temporada not in ("", "0") else "",
        })
        lote = ""
    else:
        trocas.update({"{serie}": "cada série listada em “SÉRIES NESTE LOTE”",
                       "{ano}": "", "{temporada}": ""})
        por_serie = {}
        for (codigo, temporada), e in grupos.items():
            por_serie.setdefault((e.get("serie") or f"Série {codigo}", e.get("ano", "")),
                                 []).append(temporada)
        lote = "\n\nSÉRIES NESTE LOTE (pesquise cada uma):\n" + "\n".join(
            f"- “{nome}”{f' ({ano})' if ano else ''}: temporada(s) {', '.join(temps)}"
            for (nome, ano), temps in por_serie.items())
    texto = carregar_instrucoes()
    for chave, valor in trocas.items():
        texto = texto.replace(chave, valor)
    if any(e.get("tipo") == "serie" for e in episodios):
        texto += ("\n\nPÁGINA DA SÉRIE\nO item [SÉRIE] é o nome e a sinopse da SÉRIE inteira (não de um "
                  "episódio). Título: mantenha o nome original da série, exatamente como está, a menos "
                  "que exista um nome oficial lançado no Brasil. Sinopse: traduza com as mesmas regras.")
    if any(e.get("tipo") == "temporada" for e in episodios):
        texto += ("\n\nSINOPSE DA TEMPORADA\nO item de número 0 (marca [0] ou [T…-E0]) é a sinopse "
                  "da temporada inteira, não um episódio: ele não tem título. Traduza só a "
                  "sinopse, com as mesmas regras, e deixe a linha “Título:” vazia.")
    outros = sorted({c for e in episodios for c in (e.get("idioma_titulo"), e.get("idioma_sinopse"))
                     if c and not c.startswith("en")})
    if outros:
        texto += ("\n\nIDIOMAS DOS ORIGINAIS\nNem todos os textos abaixo estão em inglês: alguns "
                  f"estão em {', '.join(outros)} (o TMDB não tinha em inglês). Traduza todos para "
                  f"{NOMES_IDIOMA.get(idioma, idioma)}, com as mesmas regras, mantendo os nomes próprios.")
    if glossarios:
        texto += ("\n\nGLOSSÁRIO (escolhas do usuário: siga exatamente; elas valem mais que a "
                  "sua pesquisa)")
        for nome, linhas in glossarios:
            texto += f"\n“{nome}”:\n" + "\n".join(f"- {l}" for l in linhas)
    texto += lote + _aviso_plot(episodios, grupos) + _aviso_omitidos(omitidos) + f"\n\n{MARCA_EPISODIOS}\n"
    anterior = None
    for e in episodios:
        grupo = (str(e["codigo"]), str(e["temporada"]))
        if len(grupos) > 1 and grupo != anterior:
            texto += f"\n=== {nome_grupo(e)} ===\n"
            anterior = grupo
        texto += (f"\n{marca(e, grupos)}\nTítulo: {e.get('titulo') or ''}\n"
                  f"Sinopse: {e.get('sinopse') or ''}\n")
    return texto


def ler_traducao(texto, episodios):
    """Devolve {id do episódio: (título ou None, sinopse ou None)}."""
    if MARCA_EPISODIOS in texto:
        texto = texto.split(MARCA_EPISODIOS, 1)[1]
    grupos = _grupos(episodios)
    por_marca = {normalizar_marca(marca(e, grupos)): e["id"] for e in episodios}
    saida = {}
    for m, corpo in re.findall(rf"({PADRAO_MARCA})\s*(.*?)(?={PADRAO_MARCA}|\Z)", texto, re.S):
        ident = por_marca.get(normalizar_marca(m))
        if ident is None:
            continue
        corpo = corpo.replace("**", "").replace("```", "")
        corpo = re.sub(r"^\s*===.*?===\s*$", "", corpo, flags=re.M)
        titulo = re.search(r"(?:T[ií]tulo|Title)\s*:\s*(.*?)\s*(?=(?:Sinopse|Synopsis)\s*:|\Z)",
                           corpo, re.S | re.I)
        sinopse = re.search(r"(?:Sinopse|Synopsis)\s*:\s*(.*)", corpo, re.S | re.I)
        saida[ident] = (titulo.group(1).strip() if titulo else None,
                        sinopse.group(1).strip() if sinopse else None)
    return saida


# ================================================================== login
def login_valido():
    if not STORAGE.exists():
        return None
    with abrir_navegador(False, login=STORAGE) as pagina:
        pagina.goto("https://www.themoviedb.org/", wait_until="domcontentloaded", timeout=30000)
        return esta_logado(pagina)


def fazer_login(avisar):
    """Abre o TMDB visível; salva o login quando a pessoa termina de entrar."""
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=False)
        contexto = navegador.new_context()
        pagina = contexto.new_page()
        pagina.goto("https://www.themoviedb.org/login", wait_until="domcontentloaded")
        limite = time.time() + 600
        while time.time() < limite:
            try:
                if pagina.is_closed():
                    break
                if "/login" not in pagina.url and esta_logado(pagina):
                    contexto.storage_state(path=str(STORAGE))
                    navegador.close()
                    return True
                pagina.wait_for_timeout(1000)
            except Exception:
                break
        try:
            navegador.close()
        except Exception:
            pass
    return False


# ================================================================== envio
def _sem_traducao_da_serie(pagina):
    """O TMDB mostra "X has not yet been translated to pt-BR… Create Translation"
    quando a série ainda não tem esse idioma."""
    try:
        return pagina.locator("text=/has not yet been translated|ainda não foi traduzid/i").count() > 0
    except Exception:
        return False


def _criar_traducao(pagina):
    """Clica em "Create Translation" e espera o formulário de edição aparecer."""
    try:
        botao = pagina.locator("a, button").filter(has_text=re.compile(r"create translation|criar tradu", re.I)).first
        botao.click(timeout=8000)
        pagina.wait_for_selector("input[id$='_name'], textarea[id$='_overview']", state="attached", timeout=15000)
        return True
    except Exception:
        return False


def enviar_episodios(itens, idioma, visivel, sub_titulo, sub_sinopse, avisar, deve_parar):
    """Envia ao TMDB. `itens`: dicionários com id, codigo, temporada, numero, titulo,
    sinopse, serie. Avisa: situacao(id, valor), log(texto), progresso, pedir_login."""
    idioma_attr = idioma.replace("-", "_")
    ok, falhas, pulados = [], [], []
    total = len(itens)
    with abrir_navegador(visivel, login=STORAGE) as pagina:
        cookies_fechados = False
        for i, item in enumerate(itens, 1):
            if deve_parar():
                avisar("log", texto="Envio interrompido.")
                break
            codigo, temporada, ep = item["codigo"], item["temporada"], item["numero"]
            temporada_inteira = item.get("tipo") == "temporada"
            pagina_serie = item.get("tipo") == "serie"
            nome = ("página da série" if pagina_serie else
                    f"T{temporada} (sinopse da temporada)" if temporada_inteira else f"T{temporada} E{ep}")
            avisar("situacao", id=item["id"], valor="Enviando")
            avisar("progresso", atual=i - 1, total=total,
                   texto=f"Enviando {item.get('serie') + ' · ' if item.get('serie') else ''}"
                         f"{nome} ({i} de {total})")
            if pagina_serie:
                endereco = f"https://www.themoviedb.org/tv/{codigo}/edit?language={idioma}"
            else:
                endereco = (f"https://www.themoviedb.org/tv/{codigo}/season/{temporada}"
                            + ("" if temporada_inteira else f"/episode/{ep}") + f"/edit?language={idioma}")
            pagina.goto(endereco, wait_until="domcontentloaded", timeout=60000)
            if _sem_traducao_da_serie(pagina):
                if pagina_serie and _criar_traducao(pagina):
                    avisar("log", texto=f"A série ainda não tinha {idioma} no TMDB: tradução criada.")
                elif not pagina_serie:
                    avisar("log", texto=f"{nome}: a série ainda não tem tradução em {idioma} no TMDB, "
                                        "então o TMDB não deixa editar os episódios. Envie antes o item "
                                        "“SÉRIE” (nome e sinopse da série) e tente de novo.")
                    avisar("situacao", id=item["id"], valor="Falhou")
                    falhas.append(nome)
                    continue
            try:
                pagina.wait_for_selector(f"#{idioma_attr}_name, #{idioma_attr}_overview",
                                         state="attached", timeout=8000)
            except Exception:
                pass
            if not esta_logado(pagina):
                avisar("log", texto="O TMDB pediu login. Nada foi enviado a partir deste "
                                    "episódio.")
                for resto in itens[i - 1:]:
                    avisar("situacao", id=resto["id"], valor="Pendente")
                falhas.append(nome)
                avisar("pedir_login")
                break
            if not cookies_fechados:
                fechar_cookies(pagina)
                cookies_fechados = True
            titulo, sinopse = item.get("titulo") or "", item.get("sinopse") or ""
            # "campos" (usado no Desfazer) permite escrever texto vazio de propósito.
            campos = item.get("campos") or [c for c, v in (("titulo", titulo),
                                                           ("sinopse", sinopse)) if v]
            if temporada_inteira:
                campos = [c for c in campos if c == "sinopse"]  # o nome da temporada não muda
            if pagina_serie and titulo.strip() == (item.get("original_titulo") or "").strip():
                # O TMDB pede para deixar o título vazio quando é igual ao original.
                campos = [c for c in campos if c != "titulo"]
            forcar = item.get("forcar", False)
            campo_t = achar_titulo(None, pagina, idioma_attr) if "titulo" in campos else None
            campo_s = achar_sinopse(None, pagina, idioma_attr) if "sinopse" in campos else None
            if ("titulo" in campos and not campo_t) or ("sinopse" in campos and not campo_s):
                avisar("log", texto=f"{nome}: não achei o campo em {idioma} (o episódio "
                                    "existe nessa temporada?). Pulado.")
                pagina.screenshot(path=str(PASTA / f"erro_campos_{codigo}_T{temporada}_E{ep}.png"))
                avisar("situacao", id=item["id"], valor="Falhou")
                falhas.append(nome)
                continue
            antes_t = campo_t.input_value() if campo_t else ""
            antes_s = campo_s.input_value() if campo_s else ""
            mantidos = []
            if not (sub_titulo or forcar) and campo_t and ja_preenchido(antes_t):
                campo_t = None
                mantidos.append("título")
            if not (sub_sinopse or forcar) and campo_s and ja_preenchido(antes_s):
                campo_s = None
                mantidos.append("sinopse")
            if not campo_t and not campo_s:
                avisar("log", texto=f"{nome}: já estava preenchido no TMDB. Mantido.")
                avisar("situacao", id=item["id"], valor="Já preenchido")
                pulados.append(nome)
                continue
            if mantidos:
                avisar("log", texto=f"{nome}: {' e '.join(mantidos)} já existia e foi mantido.")
            if campo_t:
                campo_t.fill(titulo)
            if campo_s:
                campo_s.fill(sinopse)
            if salvar_e_confirmar(None, pagina):
                avisar("log", texto=f"{nome}: salvo ✔")
                avisar("situacao", id=item["id"], valor="Enviado")
                # Guarda o que havia antes (Histórico e Desfazer).
                antes, depois = {}, {}
                if campo_t:
                    antes["titulo"], depois["titulo"] = antes_t, titulo
                if campo_s:
                    antes["sinopse"], depois["sinopse"] = antes_s, sinopse
                avisar("historico", registro={
                    "quando": time.strftime("%Y-%m-%d %H:%M:%S"), "codigo": str(codigo),
                    "temporada": str(temporada), "numero": ep, "serie": item.get("serie", ""),
                    "tipo": item.get("tipo", "episodio"),
                    "idioma": idioma, "antes": antes, "depois": depois,
                    "tipo": "desfazer" if forcar else "envio"})
                ok.append(nome)
            else:
                avisar("log", texto=f"{nome}: o TMDB não confirmou o salvamento.")
                pagina.screenshot(path=str(PASTA / f"erro_salvar_{codigo}_T{temporada}_E{ep}.png"))
                avisar("situacao", id=item["id"], valor="Falhou")
                falhas.append(nome)
            pagina.wait_for_timeout(1500)  # pausa curta para não sobrecarregar o site
    resumo = f"Pronto: {len(ok)} salvos"
    if pulados:
        resumo += f", {len(pulados)} já preenchidos (mantidos)"
    if falhas:
        resumo += f", {len(falhas)} com problema ({', '.join(falhas[:10])}" \
                  f"{' ...' if len(falhas) > 10 else ''})"
    avisar("progresso", atual=total, total=total, texto=resumo)
    avisar("log", texto=resumo)
    return {"ok": len(ok), "pulados": len(pulados), "falhas": len(falhas)}


# ============================================== prefixo numerado dos títulos
_RE_PREFIXO = re.compile(r"^\s*([^\W\d_]+(?:[ .][^\W\d_]+)?)[ .]?#?(\d+)\s*[:.\-–—]\s*\S")


def detectar_prefixo(titulos):
    """Descobre se os títulos usam um prefixo numerado próprio (ex.: "Quest 01:",
    "Space.1:", "Case File 3:"). Devolve o modelo ("Quest {n}:", dois_digitos)
    quando a maioria segue o mesmo padrão; senão None. Ignora "Episode/Ep."."""
    contagem, zeros, total = {}, 0, 0
    for t in titulos:
        t = (t or "").strip()
        if not t:
            continue
        total += 1
        m = _RE_PREFIXO.match(t)
        if not m:
            continue
        palavra = m.group(1).strip()
        if palavra.lower().rstrip(".") in ("episode", "ep", "episódio", "episodio", "part", "parte"):
            continue
        separador = t[m.end(1):m.start(2)]
        resto = t[m.end(2):].lstrip()[:1]
        modelo = f"{palavra}{separador}{{n}}{resto}"
        contagem[modelo] = contagem.get(modelo, 0) + 1
        if len(m.group(2)) == 2 and m.group(2).startswith("0"):
            zeros += 1
        elif len(m.group(2)) == 1:
            zeros -= 1
    if not total or not contagem:
        return None
    modelo, vezes = max(contagem.items(), key=lambda x: x[1])
    if vezes < max(3, total * 0.6):
        return None
    return modelo, zeros > 0


def tem_prefixo(titulos):
    return detectar_prefixo(titulos) is not None
