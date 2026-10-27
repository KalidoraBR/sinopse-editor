import csv
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time


# Tela de verificação de segurança (Cloudflare) que o Fandom às vezes mostra antes da página.
VERIFICACAO = re.compile(r"just a moment|um momento|checking your browser|verifica[çc][ãa]o de seguran[çc]a|"
                         r"verifying you are human|aguarde|esperando a resposta", re.I)


def esperar_verificacao(page, limite=30):
    """Se a página for a tela de verificação, espera ela passar sozinha (até `limite` s).
    Devolve True se a página de verdade apareceu."""
    for _ in range(limite * 2):
        try:
            titulo = page.title() or ""
            topo = page.locator("body").inner_text(timeout=3000)[:400]
        except Exception:
            titulo, topo = "", ""
        if not VERIFICACAO.search(titulo) and not VERIFICACAO.search(topo):
            return True
        page.wait_for_timeout(500)
    return False
from pathlib import Path
from urllib.parse import urlparse

import customtkinter as ctk
from playwright.sync_api import sync_playwright

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")
PASTA_ATUAL = (Path(sys.executable).parent if getattr(sys, "frozen", False)
               else Path(__file__).parent)
ENDERECO_CDP = "http://127.0.0.1:9222"
PASTA_PERFIL_CHROME = PASTA_ATUAL / "chrome_coletor_perfil"
FONTE = "Segoe UI"


class AppColetorWiki(ctk.CTkFrame):
    def __init__(self, master=None):
        super().__init__(master, fg_color="#F7F9FC", corner_radius=0)
        self.fila = queue.Queue()
        self.executando = False

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=42, pady=(30, 18))
        titulos = ctk.CTkFrame(topo, fg_color="transparent")
        titulos.pack(side="left")
        ctk.CTkLabel(titulos, text="🌐  Extrator Wiki", text_color="#172033",
                     font=ctk.CTkFont(family=FONTE, size=30, weight="bold")).pack(anchor="w")
        self.lbl_subtitulo = ctk.CTkLabel(
            titulos, text="Extraia informações dos episódios a partir da página da série.",
            text_color="#667085", font=ctk.CTkFont(family=FONTE, size=14))
        self.lbl_subtitulo.pack(anchor="w", pady=(5, 0))

        self.fonte = ctk.StringVar(value="Wiki Sentai")
        self.seletor_fonte = ctk.CTkSegmentedButton(
            topo,
            values=["Wiki Sentai", "TMDB"],
            variable=self.fonte,
            command=self.alterar_fonte,
            width=310,
            height=36,
            selected_color="#2563EB",
            selected_hover_color="#1D4ED8",
            unselected_color="#EAF0FA",
            unselected_hover_color="#DFE7F4",
            text_color="#172033",
        )
        self.seletor_fonte.pack(side="right", pady=8)

        frame = ctk.CTkFrame(
            self, fg_color="#FFFFFF", corner_radius=16,
            border_width=1, border_color="#E4E9F2")
        frame.pack(fill="x", padx=42)
        frame.grid_columnconfigure(1, weight=1)
        self.lbl_url = ctk.CTkLabel(frame, text="Página da série:")
        self.lbl_url.grid(
            row=0, column=0, padx=(20, 12), pady=(20, 8), sticky="w")
        self.txt_url = ctk.CTkEntry(frame, height=40, border_color="#CDD5E1")
        self.txt_url.grid(row=0, column=1, padx=(0, 20), pady=(20, 8), sticky="ew")
        self.txt_url.insert(
            0, "https://powerrangers-fandom-com.translate.goog/wiki/"
               "Ohsama_Sentai_King-Ohger?_x_tr_sl=en&_x_tr_tl=pt"
               "&_x_tr_hl=pt&_x_tr_pto=tc#Episodes")

        self.btn_buscar_tmdb = ctk.CTkButton(
            frame, text="🔍  Buscar série", width=125, height=40,
            fg_color="#4F46E5", command=self.buscar_serie_tmdb)
        self.lbl_temporada = ctk.CTkLabel(frame, text="Temporada:")
        self.menu_temporada = ctk.CTkOptionMenu(frame, values=["1"], width=180)
        self.lbl_episodios = ctk.CTkLabel(frame, text="Episódios:")
        self.txt_episodios = ctk.CTkEntry(frame, height=40,
            placeholder_text="Todos ou 1,3,5-10")
        self.txt_episodios.insert(0, "Todos")

        self.lbl_csv = ctk.CTkLabel(frame, text="Arquivo CSV:")
        self.lbl_csv.grid(row=1, column=0, padx=(20, 12), pady=(8, 12), sticky="w")
        self.txt_csv = ctk.CTkEntry(frame, height=40, border_color="#CDD5E1")
        self.txt_csv.grid(row=1, column=1, padx=(0, 20), pady=(8, 12), sticky="ew")
        self.txt_csv.insert(0, "extracao_fandom.csv")

        self.btn = ctk.CTkButton(
            frame, text="📥  Localizar episódios e extrair", command=self.iniciar,
            height=48, corner_radius=8,
            fg_color="#4F46E5", hover_color="#4338CA",
            font=ctk.CTkFont(family=FONTE, size=14, weight="bold"))
        self.btn.grid(row=4, column=0, columnspan=3, padx=20, pady=(10, 20), sticky="ew")

        progresso = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=16,
                                 border_width=1, border_color="#E4E9F2")
        progresso.pack(fill="both", expand=True, padx=42, pady=(18, 30))
        ctk.CTkLabel(progresso, text="Progresso", text_color="#172033",
                     font=ctk.CTkFont(family=FONTE, size=15, weight="bold")).pack(
                         anchor="w", padx=20, pady=(18, 4))
        self.lbl_progresso = ctk.CTkLabel(
            progresso, text="Aguardando início", text_color="#4F46E5",
            font=ctk.CTkFont(family=FONTE, size=14, weight="bold"))
        self.lbl_progresso.pack(anchor="w", padx=20, pady=(2, 8))
        self.barra = ctk.CTkProgressBar(
            progresso, height=9, progress_color="#4F46E5")
        self.barra.pack(fill="x", padx=20)
        self.barra.set(0)
        ctk.CTkLabel(progresso, text="Log de execução", text_color="#172033",
                     font=ctk.CTkFont(family=FONTE, size=14, weight="bold")).pack(
                         anchor="w", padx=20, pady=(18, 6))
        self.log = ctk.CTkTextbox(
            progresso, height=210, fg_color="#FAFBFC", text_color="#344054",
            border_width=1, border_color="#E4E9F2", corner_radius=12)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        self.log.configure(state="disabled")
        self.mostrar_log(
            "Sistema pronto. Ao iniciar, o programa abrirá o Chrome de coleta automaticamente.")
        self.alterar_fonte("Wiki Sentai")
        self.after(100, self.processar_fila)

    def mostrar_log(self, texto):
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def enviar(self, tipo, valor=None):
        self.fila.put((tipo, valor))

    def processar_fila(self):
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "log":
                    self.mostrar_log(valor)
                elif tipo == "progresso":
                    atual, total = valor
                    self.barra.set(atual / total if total else 0)
                    self.lbl_progresso.configure(text=f"{atual} de {total} episódios")
                elif tipo == "fim":
                    self.executando = False
                    texto = ("📥  Extrair episódios do TMDB" if self.fonte.get() == "TMDB"
                             else "📥  Localizar episódios e extrair")
                    self.btn.configure(state="normal", text=texto)
                elif tipo == "temporadas":
                    titulo, temporadas = valor
                    self.menu_temporada.configure(values=temporadas)
                    self.menu_temporada.set(temporadas[0])
                    self.btn_buscar_tmdb.configure(state="normal", text="🔍  Buscar série")
                    self.mostrar_log(
                        f"Série localizada: {titulo}. Temporadas: {', '.join(temporadas)}")
                elif tipo == "busca_fim":
                    self.btn_buscar_tmdb.configure(state="normal", text="🔍  Buscar série")
        except queue.Empty:
            pass
        self.after(100, self.processar_fila)

    def iniciar(self):
        valor_origem = self.txt_url.get().strip()
        nome = Path(self.txt_csv.get().strip()).name
        fonte = self.fonte.get()
        if fonte == "Wiki Sentai" and not re.match(r"^https?://", valor_origem, re.I):
            self.mostrar_log("ERRO: informe um link completo começando com http ou https.")
            return
        if fonte == "TMDB" and not valor_origem.isdigit():
            self.mostrar_log("ERRO: informe somente o código numérico da série no TMDB.")
            return
        if not nome:
            self.mostrar_log("ERRO: informe o nome do CSV.")
            return
        if not nome.lower().endswith(".csv"):
            nome += ".csv"
        self.executando = True
        self.barra.set(0)
        self.lbl_progresso.configure(text="Localizando episódios...")
        self.btn.configure(state="disabled", text="Processando...")
        if fonte == "TMDB":
            temporada = self.menu_temporada.get()
            url = (f"https://www.themoviedb.org/tv/{valor_origem}/season/"
                   f"{temporada}?language=pt-BR")
            try:
                selecao = self.interpretar_selecao(self.txt_episodios.get())
            except ValueError as erro:
                self.mostrar_log(f"ERRO: {erro}")
                self.executando = False
                self.btn.configure(state="normal", text="📥  Extrair episódios do TMDB")
                return
        else:
            url = valor_origem
            selecao = None
        threading.Thread(
            target=self.executar, args=(url, nome, fonte, selecao), daemon=True).start()

    def alterar_fonte(self, fonte):
        self.txt_url.delete(0, "end")
        if fonte == "TMDB":
            self.lbl_url.configure(text="Código TMDB:")
            self.lbl_subtitulo.configure(
                text="Localize a série pelo código, escolha a temporada e os episódios.")
            self.txt_url.insert(0, "2328")
            self.txt_url.grid_configure(columnspan=1)
            self.btn_buscar_tmdb.grid(row=0, column=2, padx=(0, 15), pady=(16, 8))
            self.lbl_temporada.grid(row=1, column=0, padx=15, pady=8, sticky="w")
            self.menu_temporada.grid(row=1, column=1, padx=15, pady=8, sticky="w")
            self.lbl_episodios.grid(row=2, column=0, padx=15, pady=8, sticky="w")
            self.txt_episodios.grid(row=2, column=1, columnspan=2, padx=15, pady=8, sticky="ew")
            self.lbl_csv.grid_configure(row=3)
            self.txt_csv.grid_configure(row=3)
            self.txt_csv.delete(0, "end")
            self.txt_csv.insert(0, "extracao_tmdb.csv")
            self.btn.configure(text="📥  Extrair episódios do TMDB")
        else:
            self.btn_buscar_tmdb.grid_forget()
            self.lbl_temporada.grid_forget()
            self.menu_temporada.grid_forget()
            self.lbl_episodios.grid_forget()
            self.txt_episodios.grid_forget()
            self.lbl_url.configure(text="Página da série:")
            self.lbl_subtitulo.configure(
                text="Cole o link principal da série. O programa localizará os episódios automaticamente.")
            self.txt_url.insert(
                0, "https://powerrangers-fandom-com.translate.goog/wiki/"
                   "Ohsama_Sentai_King-Ohger?_x_tr_sl=en&_x_tr_tl=pt"
                   "&_x_tr_hl=pt&_x_tr_pto=tc#Episodes")
            self.lbl_csv.grid_configure(row=1)
            self.txt_csv.grid_configure(row=1)
            self.txt_csv.delete(0, "end")
            self.txt_csv.insert(0, "extracao_fandom.csv")
            self.btn.configure(text="📥  Localizar episódios e extrair")

    @staticmethod
    def interpretar_selecao(texto):
        texto = (texto or "Todos").strip()
        if texto.casefold() in {"todos", "todas", "all", "*"}:
            return None
        numeros = set()
        for parte in texto.split(","):
            parte = parte.strip()
            if not parte:
                continue
            if "-" in parte:
                inicio, fim = parte.split("-", 1)
                if not inicio.isdigit() or not fim.isdigit() or int(inicio) > int(fim):
                    raise ValueError("use episódios como Todos, 1,3,5-10.")
                numeros.update(range(int(inicio), int(fim) + 1))
            elif parte.isdigit():
                numeros.add(int(parte))
            else:
                raise ValueError("use episódios como Todos, 1,3,5-10.")
        if not numeros:
            raise ValueError("informe ao menos um episódio ou escreva Todos.")
        return numeros

    @staticmethod
    def limpar(texto):
        if not texto:
            return "Não disponível"
        return " ".join(texto.replace("\n", " ").replace("\r", " ")
                       .replace("\t", " ").split()).strip()

    @staticmethod
    def numero_episodio(texto):
        for padrao in (
            r"^\s*(?:[^\W\d_]+\.?\s*){0,3}?#?(\d+)\s*[:.\-–—]",
            r"^\s*(?:episode|episódio)\s+(\d+)\b",
        ):
            achado = re.search(padrao, texto, re.I)
            if achado:
                return int(achado.group(1))
        return None

    def buscar_serie_tmdb(self):
        tv_id = self.txt_url.get().strip()
        if not tv_id.isdigit():
            self.mostrar_log("ERRO: informe somente o código numérico da série.")
            return
        self.btn_buscar_tmdb.configure(state="disabled", text="Buscando...")
        threading.Thread(
            target=self._buscar_serie_tmdb, args=(tv_id,), daemon=True).start()

    def _buscar_serie_tmdb(self, tv_id):
        try:
            self.garantir_chrome_coleta()
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(ENDERECO_CDP)
                contexto = browser.contexts[0]
                page = contexto.pages[0] if contexto.pages else contexto.new_page()
                page.goto(
                    f"https://www.themoviedb.org/tv/{tv_id}/seasons?language=pt-BR",
                    wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
                titulo = page.locator("h2, h1").first.inner_text(timeout=5000).strip()
                hrefs = page.locator("a[href*='/season/']").evaluate_all(
                    "els => els.map(e => e.getAttribute('href') || '')")
                temporadas = set()
                for href in hrefs:
                    achado = re.search(r"/season/(\d+)", href)
                    if achado:
                        temporadas.add(int(achado.group(1)))
                if not temporadas:
                    raise RuntimeError("nenhuma temporada foi encontrada para esse código.")
                valores = [str(n) for n in sorted(temporadas)]
                self.enviar("temporadas", (self.limpar(titulo), valores))
        except Exception as erro:
            self.enviar("log", f"ERRO ao buscar a série: {erro}")
            self.enviar("busca_fim")

    def anchors(self, page, somente_secao):
        return page.locator("body").evaluate(
            """(somenteSecao) => {
                const hs = [...document.querySelectorAll('h2,h3')];
                const h = hs.find(e =>
                    /^(episodes|episode list|episódios|lista de episódios)$/i
                    .test((e.innerText || '').trim()) ||
                    /^(episodes|episode_list)$/i.test(e.id || ''));
                let as = [];
                if (h && somenteSecao) {
                    let e = h.nextElementSibling;
                    while (e && e.tagName !== 'H2') {
                        as.push(...e.querySelectorAll('a[href]'));
                        e = e.nextElementSibling;
                    }
                } else {
                    const raiz = document.querySelector('.mw-parser-output') || document.body;
                    as = [...raiz.querySelectorAll('a[href]')];
                }
                return as.map(a => ({
                    texto: (a.innerText || a.textContent || '').trim(),
                    url: new URL(a.getAttribute('href'), location.href).href
                }));
            }""", somente_secao)

    def filtrar_episodios(self, anchors):
        unicos = {}
        finais = []
        for item in anchors:
            numero = self.numero_episodio(item["texto"])
            url = item["url"].split("#", 1)[0]
            if numero is not None and url.startswith(("http://", "https://")):
                unicos.setdefault(numero, {
                    "numero": numero, "url": url, "texto": item["texto"]})
            elif (re.search(r"\b(?:final\s+(?:ep\.?|episode)|epis[oó]dio\s+final)\b"
                            r"|^\s*(?:[^\W\d_]+\.?\s*){1,3}?final\s*[:.\-–—]"
                            r"|^\s*(?:last|final|closing|ending|ultimate)\s+[^\W\d_]+\.?\s*[:.\-–—]",
                            item["texto"], re.I)
                  and url.startswith(("http://", "https://"))):
                finais.append(item)
        if finais:
            numero_final = max(unicos, default=0) + 1
            item = finais[0]
            if item["url"].split("#", 1)[0] not in {
                    dado["url"] for dado in unicos.values()}:
                unicos[numero_final] = {
                    "numero": numero_final,
                    "url": item["url"].split("#", 1)[0],
                    "texto": item["texto"],
                    "episodio_final": True,
                }
        return [unicos[n] for n in sorted(unicos)]

    def lista_principal(self, page, somente_secao):
        """Maior lista (ul/ol/tabela) da seção de episódios — ou da página inteira.

        Serve para Wikis em que o episódio não tem número no nome (ex.: só o título):
        cada item da lista é um episódio, na ordem em que aparece.
        """
        return page.locator("body").evaluate(
            """(somenteSecao) => {
                const hs = [...document.querySelectorAll('h2,h3')];
                const h = hs.find(e =>
                    /^(episodes|episode list|episode guide|episódios|lista de episódios)/i
                    .test((e.innerText || '').trim()) ||
                    /^(episodes|episode_list)$/i.test(e.id || ''));
                const raizes = [];
                if (h && somenteSecao) {
                    let e = h.nextElementSibling;
                    while (e && e.tagName !== 'H2') { raizes.push(e); e = e.nextElementSibling; }
                } else {
                    raizes.push(document.querySelector('.mw-parser-output') || document.body);
                }
                const grupos = new Map();
                const ruido = 'nav, aside, .navbox, .portable-infobox, .toc, .reference, .references';
                for (const raiz of raizes) {
                    const itens = raiz.matches && raiz.matches('li, tr') ? [raiz] : [];
                    itens.push(...raiz.querySelectorAll('li, tr'));
                    for (const c of itens) {
                        if (c.closest(ruido)) continue;
                        const a = [...c.querySelectorAll('a[href]')].find(x => {
                            const u = new URL(x.getAttribute('href'), location.href);
                            const nome = decodeURIComponent(u.pathname.split('/').pop() || '');
                            // Ignora páginas especiais (File:, Category:...), mas aceita
                            // títulos com dois-pontos, como "Wanted: Despair".
                            const especial = /^(file|image|category|template|special|user|help|talk|module|mediawiki|portal|forum|blog|message_wall|fandom)(_talk)?:/i;
                            return u.host === location.host && u.pathname.includes('/wiki/') &&
                                   !especial.test(nome) && !u.hash && u.pathname !== location.pathname;
                        });
                        if (!a) continue;
                        const pai = c.parentElement;
                        if (!grupos.has(pai)) grupos.set(pai, []);
                        grupos.get(pai).push({
                            texto: (a.innerText || a.textContent || '').trim(),
                            url: new URL(a.getAttribute('href'), location.href).href.split('#')[0]
                        });
                    }
                }
                let melhor = [];
                for (const lista of grupos.values()) if (lista.length > melhor.length) melhor = lista;
                const vistos = new Set();
                return melhor.filter(i => !vistos.has(i.url) && vistos.add(i.url));
            }""", somente_secao)

    def por_posicao(self, itens):
        """Numera os episódios pela ordem da lista (usa o número do nome, se houver)."""
        episodios = []
        for posicao, item in enumerate(itens, 1):
            numero = self.numero_episodio(item["texto"]) or posicao
            episodios.append({"numero": numero, "url": item["url"], "texto": item["texto"]})
        return episodios

    def descobrir_episodios(self, page, url):
        self.enviar("log", "Abrindo a página principal da série...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        esperar_verificacao(page)
        page.wait_for_timeout(1800)
        itens_secao = self.anchors(page, True)
        episodios = self.filtrar_episodios(itens_secao)
        if len(episodios) >= 2:
            return episodios

        # Os nomes não trazem número: usa a lista da seção "Episodes", na ordem.
        lista = self.lista_principal(page, True)
        if len(lista) >= 5:
            self.enviar("log", f"Episódios sem número no nome: usando a ordem da lista "
                               f"({len(lista)} itens).")
            return self.por_posicao(lista)

        artigo = None
        for item in itens_secao:
            texto = item["texto"].casefold()
            caminho = urlparse(item["url"]).path.casefold()
            if "episodes" in caminho or "episodes" in texto or "episódios" in texto:
                artigo = item["url"]
                break
        if artigo and artigo.split("#")[0] != page.url.split("#")[0]:
            self.enviar("log", "A lista está em outro artigo. Abrindo a página de episódios...")
            page.goto(artigo, wait_until="domcontentloaded", timeout=60000)
            esperar_verificacao(page)
            page.wait_for_timeout(1500)
            episodios = self.filtrar_episodios(self.anchors(page, False))
            if len(episodios) >= 2:
                return episodios
            lista = self.lista_principal(page, True) or self.lista_principal(page, False)
        elif len(lista) < 2:
            # O link já é a página da lista de episódios (sem seção "Episodes").
            lista = self.lista_principal(page, False)
        if len(lista) >= 2:
            self.enviar("log", f"Episódios sem número no nome: usando a ordem da lista "
                               f"({len(lista)} itens).")
            return self.por_posicao(lista)
        return []

    def extrair_secao(self, page, nomes):
        try:
            texto = page.locator("h2,h3").evaluate_all(
                """(hs, nomes) => {
                    const normal = s => (s || '').trim().toLocaleLowerCase();
                    const h = hs.find(e => nomes.some(n =>
                        normal(e.id) === n || normal(e.innerText) === n ||
                        normal(e.innerText).startsWith(n + '[')));
                    if (!h) return '';
                    const partes = [];
                    let e = h.nextElementSibling;
                    while (e && !['H2','H3'].includes(e.tagName)) {
                        if (!e.matches('aside,.portable-infobox,.toc,script,style'))
                            partes.push(e.innerText || '');
                        e = e.nextElementSibling;
                    }
                    return partes.join(' ');
                }""", [n.casefold() for n in nomes])
            return self.limpar(texto)
        except Exception:
            return "Não disponível"

    def extrair_titulo(self, page, episodio):
        try:
            titulo = page.locator("h1").first.inner_text(timeout=5000)
        except Exception:
            titulo = episodio["texto"] or page.title()
        # Tira só os prefixos genéricos ("Ep. 1:", "Episode 1:", "Final Ep.:").
        # Prefixos temáticos da série ("Space.1", "Stage 1", "Number 1") ficam no título.
        n = episodio["numero"]
        titulo = re.sub(
            rf"^\s*(?:ep|episode|epis[oó]dio)\.?\s*{n}\s*[:.\-–—]\s*",
            "", titulo, flags=re.I)
        titulo = re.sub(
            r"^\s*(?:final\s+(?:ep\.?|episode)|epis[oó]dio\s+final)\s*[:.\-–—]?\s*",
            "", titulo, flags=re.I)
        titulo = re.sub(r"\s*\|\s*RangerWiki\s*\|\s*Fandom.*$", "",
                        titulo, flags=re.I)
        return self.limpar(titulo)

    def extrair_temporada_tmdb(self, page, url):
        self.enviar("log", "Abrindo a temporada no TMDB...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2200)

        dados = page.locator("body").evaluate(
            """() => {
                const limpar = s => (s || '').replace(/\\s+/g, ' ').trim();
                const seletores = [
                    '.episode_list .card', '.episode_list .episode',
                    'section.panel .episode', 'div.episode.card'
                ];
                let cards = [];
                for (const seletor of seletores) {
                    cards = [...document.querySelectorAll(seletor)];
                    if (cards.length) break;
                }
                const resultado = [];
                for (const card of cards) {
                    const linksEp = [...card.querySelectorAll('a[href*="/episode/"]')];
                    const tituloEl = card.querySelector(
                        '.title h3 a, .title h4 a, h3 a[href*="/episode/"], '
                        + 'h4 a[href*="/episode/"], a.title') ||
                        linksEp.find(a => !/^(?:Epis[oó]dio|Episode|E)?\\s*\\d+$/i
                            .test(limpar(a.textContent))) || linksEp[0];
                    const blocoNumero = card.querySelector('.episode_number, .meta, h3, h4');
                    const textoNumero = limpar(blocoNumero?.innerText || card.innerText);
                    let achado = textoNumero.match(/(?:Epis[oó]dio|Episode|E)\\s*(\\d+)/i);
                    if (!achado && linksEp.length) {
                        achado = (linksEp[0].getAttribute('href') || '').match(/episode[/](\\d+)/i);
                    }
                    const overview = card.querySelector(
                        '.overview p, .overview, .episode_overview, p.overview, .info > p');
                    if (achado && tituloEl) resultado.push({
                        episodio: Number(achado[1]),
                        titulo: limpar(tituloEl.textContent),
                        sinopse: limpar(overview?.textContent || '')
                    });
                }
                return resultado;
            }""")

        unicos = {}
        for item in dados:
            numero = item.get("episodio")
            if numero and numero not in unicos:
                unicos[numero] = {
                    "episodio": numero,
                    "titulo": self.limpar(item.get("titulo")),
                    "sinopse": self.limpar(item.get("sinopse")),
                }
        return [unicos[n] for n in sorted(unicos)]

    @staticmethod
    def porta_chrome_aberta():
        try:
            with socket.create_connection(("127.0.0.1", 9222), timeout=1):
                return True
        except OSError:
            return False

    @staticmethod
    def localizar_chrome():
        candidatos = []
        localizado = shutil.which("chrome") or shutil.which("google-chrome")
        if localizado:
            candidatos.append(Path(localizado))

        for variavel in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variavel)
            if base:
                candidatos.append(
                    Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")

        for caminho in candidatos:
            if caminho.is_file():
                return caminho
        return None

    def garantir_chrome_coleta(self):
        if self.porta_chrome_aberta():
            self.enviar("log", "Chrome de coleta já está aberto.")
            return

        executavel = self.localizar_chrome()
        if not executavel:
            raise RuntimeError(
                "Não encontrei o Google Chrome instalado neste computador.")

        PASTA_PERFIL_CHROME.mkdir(exist_ok=True)
        self.enviar("log", "Abrindo uma janela separada do Chrome para a coleta...")
        opcoes = {}
        if os.name == "nt":
            opcoes["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [
                str(executavel),
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9222",
                f"--user-data-dir={PASTA_PERFIL_CHROME}",
                "--no-first-run",
                "--no-default-browser-check",
                # Sem isso o Chrome "economiza" as abas em segundo plano e a coleta fica lenta.
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **opcoes,
        )

        limite = time.time() + 15
        while time.time() < limite:
            if self.porta_chrome_aberta():
                self.enviar("log", "Chrome de coleta conectado com sucesso.")
                return
            time.sleep(0.4)
        raise RuntimeError(
            "O Chrome foi aberto, mas a porta 9222 não respondeu após 15 segundos.")

    def executar(self, url, nome, fonte, selecao=None):
        destino = PASTA_ATUAL / nome
        self.enviar("log", "Preparando o Google Chrome de coleta...")
        try:
            self.garantir_chrome_coleta()
            with sync_playwright() as p:
                self.enviar("log", "Conectando ao Chrome em 127.0.0.1:9222...")
                browser = p.chromium.connect_over_cdp(ENDERECO_CDP)
                if not browser.contexts:
                    raise RuntimeError("Nenhuma janela do Chrome foi encontrada.")
                contexto = browser.contexts[0]
                page = contexto.pages[0] if contexto.pages else contexto.new_page()
                if fonte == "TMDB":
                    episodios_tmdb = self.extrair_temporada_tmdb(page, url)
                    if not episodios_tmdb:
                        raise RuntimeError(
                            "Não encontrei os episódios nessa página do TMDB. "
                            "Confirme se o link abre diretamente a temporada e se ela possui episódios.")
                    if selecao is not None:
                        disponiveis = {item["episodio"] for item in episodios_tmdb}
                        ausentes = sorted(selecao - disponiveis)
                        episodios_tmdb = [
                            item for item in episodios_tmdb
                            if item["episodio"] in selecao]
                        if ausentes:
                            self.enviar(
                                "log", "Aviso: episódios não encontrados: "
                                + ", ".join(map(str, ausentes)))
                        if not episodios_tmdb:
                            raise RuntimeError(
                                "nenhum dos episódios selecionados existe nessa temporada.")
                    total = len(episodios_tmdb)
                    self.enviar("log", f"Encontrados {total} episódios no TMDB.")
                    with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
                        escritor = csv.writer(
                            arquivo, delimiter=";", quoting=csv.QUOTE_ALL)
                        escritor.writerow(["episodio", "titulo", "sinopse"])
                        for posicao, item in enumerate(episodios_tmdb, 1):
                            escritor.writerow([
                                item["episodio"], item["titulo"], item["sinopse"]])
                            arquivo.flush()
                            self.enviar("log", f"Episódio {item['episodio']} coletado.")
                            self.enviar("progresso", (posicao, total))
                    self.enviar("log", f"Concluído. Arquivo salvo em: {destino}")
                    return

                episodios = self.descobrir_episodios(page, url)
                if not episodios:
                    raise RuntimeError(
                        "Não encontrei links como 'Ep. 1' e 'Ep. 2' na seção Episodes.")

                total = len(episodios)
                self.enviar("log", f"Encontrados {total} episódios. Iniciando a extração.")
                with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
                    escritor = csv.writer(arquivo, delimiter=";", quoting=csv.QUOTE_ALL)
                    escritor.writerow(["episodio", "titulo", "synopsis", "plot", "cast"])
                    for posicao, ep in enumerate(episodios, 1):
                        numero = ep["numero"]
                        self.enviar("log", f"[{posicao}/{total}] Extraindo episódio {numero}...")
                        try:
                            page.goto(ep["url"], wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_timeout(1000)
                            escritor.writerow([
                                numero,
                                self.extrair_titulo(page, ep),
                                self.extrair_secao(page, ["synopsis", "sinopse"]),
                                self.extrair_secao(page, ["plot", "enredo"]),
                                self.extrair_secao(page, ["cast", "elenco"]),
                            ])
                        except Exception as erro:
                            self.enviar("log", f"Falha no episódio {numero}: {erro}")
                            escritor.writerow(
                                [numero, "Erro de carregamento", "Erro", "Erro", "Erro"])
                        arquivo.flush()
                        self.enviar("progresso", (posicao, total))
                self.enviar("log", f"Concluído. Arquivo salvo em: {destino}")
        except Exception as erro:
            self.enviar("log", f"ERRO: {erro}")
            self.enviar(
                "log",
                "Feche somente a janela 'Chrome de coleta' e tente novamente. "
                "O seu Chrome comum pode continuar aberto.")
        finally:
            self.enviar("fim")

    def fechar(self):
        if self.executando:
            self.mostrar_log("A extração ainda está em andamento. Aguarde antes de fechar.")
        else:
            self.destroy()


if __name__ == "__main__":
    raiz = ctk.CTk()
    raiz.geometry("1050x760")
    janela = AppColetorWiki(raiz)
    janela.pack(fill="both", expand=True)
    raiz.mainloop()
