import csv
import queue
import re
import threading
import time
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from playwright.sync_api import sync_playwright

# Configuração visual do CustomTkinter
ctk.set_appearance_mode("System")  
ctk.set_default_color_theme("blue")

PASTA = (Path(sys.executable).parent if getattr(sys, "frozen", False)
         else Path(__file__).parent)
STORAGE = PASTA / "tmdb_auth.json"
FONTE = "Segoe UI"

# Textos que o extrator grava quando não acha a informação.
# Nunca devem ser enviados ao TMDB.
VALORES_INVALIDOS = {"não disponível", "nao disponivel", "erro", "erro de carregamento", "n/a", "-"}

class AppTMDB(ctk.CTkFrame):
    def __init__(self, master=None):
        super().__init__(master, fg_color="#F7F9FC", corner_radius=0)

        self.caminho_csv = None
        self.fila = queue.Queue()
        self.lista_temporadas = ["1"] 

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.pack(fill="x", padx=42, pady=(30, 18))
        self.lbl_titulo = ctk.CTkLabel(
            topo, text="🗄️  Automatizador TMDB", text_color="#172033",
            font=ctk.CTkFont(family=FONTE, size=30, weight="bold"))
        self.lbl_titulo.pack(anchor="w")
        ctk.CTkLabel(topo, text="Envie títulos e sinopses revisados para uma temporada.",
                     text_color="#667085", font=ctk.CTkFont(family=FONTE, size=14)).pack(
                         anchor="w", pady=(5, 0))

        sessao = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=15,
                              border_width=1, border_color="#E4E9F2")
        sessao.pack(fill="x", padx=42, pady=(0, 16))
        status = ctk.CTkFrame(sessao, fg_color="#EAF8EF", width=54, height=54,
                              corner_radius=27)
        status.pack(side="left", padx=20, pady=16)
        status.pack_propagate(False)
        ctk.CTkLabel(status, text="✅", text_color="#16A34A",
                     font=ctk.CTkFont(family="Segoe UI Emoji", size=22)).pack(expand=True)
        info = ctk.CTkFrame(sessao, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text="Sessão TMDB", text_color="#16A34A",
                     font=ctk.CTkFont(family=FONTE, size=14, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(info, text="Faça login antes de iniciar a automação.",
                     text_color="#667085", font=ctk.CTkFont(family=FONTE, size=12)).pack(anchor="w")
        self.btn_login = ctk.CTkButton(
            sessao, text="🔄  Fazer novo login", command=self.acao_login,
            fg_color="#FFFFFF", hover_color="#F4EEFF", text_color="#7C3AED",
            border_width=1, border_color="#7C3AED", width=150, height=40)
        self.btn_login.pack(side="right", padx=20)

        # --- CONTAINER DE CAMPOS ---
        self.frame_campos = ctk.CTkFrame(
            self, fg_color="#FFFFFF", corner_radius=16,
            border_width=1, border_color="#E4E9F2")
        self.frame_campos.pack(padx=42, fill="x")
        self.frame_campos.grid_columnconfigure((0, 1, 2), weight=1)

        # ID da Série e Botão Buscar
        self.lbl_tv_id = ctk.CTkLabel(self.frame_campos, text="ID da Série no TMDB:")
        self.lbl_tv_id.grid(row=0, column=0, padx=(20, 8), pady=(18, 4), sticky="w")
        
        self.frame_id_busca = ctk.CTkFrame(self.frame_campos, fg_color="transparent")
        self.frame_id_busca.grid(row=1, column=0, padx=(20, 8), pady=(0, 12), sticky="ew")
        
        self.txt_tv_id = ctk.CTkEntry(self.frame_id_busca, placeholder_text="Ex: 4816", height=40)
        self.txt_tv_id.insert(0, "4816")
        self.txt_tv_id.pack(side="left", padx=(0, 10))
        
        self.btn_buscar_seasons = ctk.CTkButton(
            self.frame_id_busca, text="🔍  Buscar", width=100, height=40,
            command=self.acao_buscar_temporadas,
            fg_color="#7C3AED", hover_color="#6D28D9")
        self.btn_buscar_seasons.pack(side="left")

        # Temporada
        self.lbl_season = ctk.CTkLabel(self.frame_campos, text="Escolha a Temporada:")
        self.lbl_season.grid(row=0, column=1, padx=8, pady=(18, 4), sticky="w")
        self.menu_season = ctk.CTkOptionMenu(self.frame_campos, values=self.lista_temporadas, height=40)
        self.menu_season.grid(row=1, column=1, padx=8, pady=(0, 12), sticky="ew")

        # Idioma
        self.lbl_idioma = ctk.CTkLabel(self.frame_campos, text="Idioma de Destino:")
        self.lbl_idioma.grid(row=0, column=2, padx=(8, 20), pady=(18, 4), sticky="w")
        self.menu_idioma = ctk.CTkOptionMenu(self.frame_campos, values=["pt-BR", "pt-PT"], height=40)
        self.menu_idioma.set("pt-BR") 
        self.menu_idioma.grid(row=1, column=2, padx=(8, 20), pady=(0, 12), sticky="ew")

        # --- SELEÇÃO DE ARQUIVO ---
        self.btn_csv = ctk.CTkButton(
            self.frame_campos, text="📂  Selecionar arquivo CSV", command=self.buscar_arquivo,
            height=42, corner_radius=10,
            fg_color="#475467", hover_color="#344054")
        self.btn_csv.grid(row=3, column=2, padx=(8, 20), pady=(4, 18), sticky="ew")

        self.lbl_nome_csv = ctk.CTkLabel(
            self.frame_campos, text="Nenhum arquivo selecionado", anchor="w",
            fg_color="#F8FAFC", corner_radius=8,
            font=ctk.CTkFont(family=FONTE, size=12, slant="italic"))
        self.lbl_nome_csv.grid(row=3, column=0, columnspan=2, padx=(20, 8),
                               pady=(4, 18), sticky="ew")

        # --- BOTÕES DE AÇÃO ---
        self.frame_botoes = ctk.CTkFrame(self.frame_campos, fg_color="transparent")
        self.frame_botoes.grid(row=4, column=0, columnspan=3, padx=20,
                               pady=(0, 18), sticky="e")

        self.btn_iniciar = ctk.CTkButton(
            self.frame_botoes, text="▶️  Iniciar automação", command=self.acao_automacao,
            width=230, height=44, fg_color="#7C3AED", hover_color="#6D28D9",
            font=ctk.CTkFont(family=FONTE, size=14, weight="bold"))
        self.btn_iniciar.grid(row=0, column=0)

        # --- ÁREA DE LOG / STATUS ---
        painel_log = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=15,
                                  border_width=1, border_color="#E4E9F2")
        painel_log.pack(fill="both", expand=True, padx=42, pady=(16, 30))
        ctk.CTkLabel(painel_log, text="Log de execução", text_color="#172033",
                     font=ctk.CTkFont(family=FONTE, size=14, weight="bold")).pack(
                         anchor="w", padx=20, pady=(16, 6))
        self.txt_log = ctk.CTkTextbox(
            painel_log, height=190, fg_color="#FAFBFC", text_color="#344054",
            border_width=1, border_color="#E4E9F2", corner_radius=12,
            font=ctk.CTkFont(family=FONTE, size=11))
        self.txt_log.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        self.escrever_log("Sistema Pronto. Digite o ID da Série e clique em 🔍 Buscar.")
        self.after(100, self.processar_fila)

    # ------------------------------------------------------------------
    # Comunicação thread -> interface. O Tkinter não é thread-safe, então
    # as rotinas em segundo plano só colocam pedidos na fila; quem mexe nos
    # widgets é sempre o loop principal (processar_fila).
    # ------------------------------------------------------------------
    def na_ui(self, funcao):
        self.fila.put(funcao)

    def processar_fila(self):
        try:
            while True:
                self.fila.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self.processar_fila)

    def escrever_log(self, mensagem):
        def inserir():
            self.txt_log.insert(tk.END, mensagem + "\n")
            self.txt_log.see(tk.END)
        if threading.current_thread() is threading.main_thread():
            inserir()
        else:
            self.na_ui(inserir)

    def configurar(self, widget, **opcoes):
        self.na_ui(lambda: widget.configure(**opcoes))

    def buscar_arquivo(self):
        caminho = filedialog.askopenfilename(
            title="Selecione a planilha de sinopses (Qualquer nome)",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")]
        )
        if caminho:
            self.caminho_csv = Path(caminho)
            self.lbl_nome_csv.configure(text=f"Selecionado: {self.caminho_csv.name}", text_color="#2ecc71")
            self.escrever_log(f"Arquivo carregado com sucesso: {self.caminho_csv.name}")

    def acao_login(self):
        self.btn_login.configure(state="disabled")
        threading.Thread(target=self.rotina_login, daemon=True).start()

    def rotina_login(self):
        self.escrever_log("Abrindo navegador... Faça login no TMDB e FECHE a aba ao terminar.")
        context = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://www.themoviedb.org/login")
                page.wait_for_event("close", timeout=0)
                context.storage_state(path=str(STORAGE))
            self.escrever_log("Sessão de login capturada e salva com sucesso!")
        except Exception:
            self.escrever_log("Aviso: Navegador fechado. Verifique se o login funcionou.")
            try:
                if context:
                    context.storage_state(path=str(STORAGE))
            except Exception:
                pass
        finally:
            self.configurar(self.btn_login, state="normal")

    def acao_buscar_temporadas(self):
        tv_id = self.txt_tv_id.get().strip()
        if not tv_id.isdigit():
            self.escrever_log("ERRO: Digite um ID de série válido (somente números).")
            return
        self.btn_buscar_seasons.configure(state="disabled", text="Buscando...")
        threading.Thread(target=self.rotina_buscar_temporadas, args=(tv_id,), daemon=True).start()

    def rotina_buscar_temporadas(self, tv_id):
        self.escrever_log(f"Verificando catálogo de temporadas para a série ID {tv_id}...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True)
                page = browser.new_context().new_page()
                page.goto(f"https://www.themoviedb.org/tv/{tv_id}/seasons")
                page.wait_for_load_state("networkidle")
                hrefs = page.locator("a[href*='/season/']").evaluate_all(
                    "els => els.map(e => e.getAttribute('href') || '')")
                browser.close()

            temporadas = set()
            for href in hrefs:
                achado = re.search(rf"/tv/{tv_id}[^/]*/season/(\d+)", href)
                if achado:
                    temporadas.add(int(achado.group(1)))

            if temporadas:
                lista = [str(n) for n in sorted(temporadas)]
                padrao = "1" if "1" in lista else lista[0]

                def atualizar():
                    self.lista_temporadas = lista
                    self.menu_season.configure(values=lista)
                    self.menu_season.set(padrao)
                self.na_ui(atualizar)
                self.escrever_log(f"Sucesso! Encontradas {len(lista)} temporadas: {', '.join(lista)}")
            else:
                self.escrever_log("ERRO: Nenhuma temporada encontrada. Confira o ID da série.")
        except Exception as e:
            self.escrever_log(f"Erro ao buscar as temporadas: {e}")
        finally:
            self.configurar(self.btn_buscar_seasons, state="normal", text="🔍  Buscar")

    def acao_automacao(self):
        if not self.caminho_csv:
            self.escrever_log("ERRO: Por favor, selecione seu arquivo de planilha primeiro!")
            return
        tv_id = self.txt_tv_id.get().strip()
        if not tv_id.isdigit():
            self.escrever_log("ERRO: Digite um ID de série válido (somente números).")
            return
        # Lê os campos da interface aqui, na thread principal.
        parametros = (tv_id, self.menu_season.get(), self.menu_idioma.get())
        for botao in (self.btn_iniciar, self.btn_login, self.btn_csv, self.btn_buscar_seasons):
            botao.configure(state="disabled")
        threading.Thread(target=self.rotina_automacao, args=parametros, daemon=True).start()

    @staticmethod
    def valor_valido(texto):
        """Devolve o texto limpo, ou None se for vazio/placeholder do extrator."""
        texto = (texto or "").strip()
        if not texto or texto.casefold() in VALORES_INVALIDOS:
            return None
        return texto

    def ler_csv(self):
        episodios = {}
        ignorados = 0
        with open(self.caminho_csv, newline="", encoding="utf-8-sig") as f:
            amostra = f.read(4096)
            f.seek(0)
            try:
                separador = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
            except csv.Error:
                separador = ";"
            for linha in csv.DictReader(f, delimiter=separador):
                raw_ep = (linha.get("episodio") or "").strip()
                titulo = self.valor_valido(linha.get("titulo"))
                # Usa a primeira coluna de sinopse que tiver conteúdo de verdade.
                sinopse = next((v for v in (self.valor_valido(linha.get(c))
                                            for c in ("sinopse", "synopsis", "plot")) if v), None)
                try:
                    ep = int(raw_ep)
                except ValueError:
                    continue
                if not titulo and not sinopse:
                    ignorados += 1
                    continue
                episodios[ep] = {"titulo": titulo, "sinopse": sinopse}
        if ignorados:
            self.escrever_log(f"Aviso: {ignorados} linha(s) ignoradas por não terem título/sinopse válidos.")
        return episodios

    @staticmethod
    def preencher(campo, texto):
        campo.click()
        campo.fill(texto)

    def achar_campo_titulo(self, page, idioma_attr):
        # Estratégia 1: id previsível do idioma (ex.: #pt_BR_name).
        campo = page.locator(f"#{idioma_attr}_name")
        try:
            if campo.count() and campo.is_editable():
                return campo
        except Exception:
            pass
        # Estratégia 2: input cujo id/name contenha o idioma e "name",
        # nunca o título original.
        for el in page.locator("input[type='text']").all():
            try:
                id_attr = (el.get_attribute("id") or "") + " " + (el.get_attribute("name") or "")
                id_attr = id_attr.lower()
                if (idioma_attr.lower() in id_attr and "name" in id_attr
                        and "original" not in id_attr and el.is_editable()):
                    return el
            except Exception:
                continue
        return None

    def achar_campo_sinopse(self, page, idioma_attr):
        campo = page.locator(f"#{idioma_attr}_overview")
        try:
            if campo.count() and campo.is_editable():
                return campo
        except Exception:
            pass
        for el in page.locator("textarea").all():
            try:
                id_attr = ((el.get_attribute("id") or "") + " " + (el.get_attribute("name") or "")).lower()
                if idioma_attr.lower() in id_attr and "overview" in id_attr and el.is_editable():
                    return el
            except Exception:
                continue
        return None

    @staticmethod
    def esta_logado(page):
        """True se a página mostra o usuário logado (avatar/link do perfil)."""
        if "/login" in page.url:
            return False
        try:
            if page.get_by_text(re.compile(r"não tem permissão|don't have permission", re.I)).count():
                return False
        except Exception:
            pass
        # O link "Sair" só existe para quem está logado. (Links "/u/..." não servem:
        # a página inicial mostra perfis de outros usuários no ranking.)
        return page.locator("a[href*='logout']").count() > 0

    @staticmethod
    def fechar_cookies(page):
        # Recusa os cookies opcionais para o aviso não cobrir o botão Salvar.
        for texto in ("Rejeitar Todos", "Reject All"):
            try:
                botao = page.get_by_role("button", name=texto)
                if botao.count():
                    botao.first.click(timeout=2000)
                    return
            except Exception:
                pass

    def salvar_e_confirmar(self, page):
        """Clica em salvar e só retorna True se o servidor do TMDB aceitar o envio.

        O TMDB pode continuar na mesma página depois de salvar, então a
        confirmação vem da resposta do servidor ao envio do formulário.
        """
        for seletor_b in ["input#submit", "input[type='submit']", "button#submit",
                          "button:has-text('Save')", "button:has-text('Salvar')"]:
            btn = page.locator(seletor_b).first
            try:
                if not btn.is_visible():
                    continue
            except Exception:
                continue

            def eh_envio(resposta):
                pedido = resposta.request
                return (pedido.method in ("POST", "PUT", "PATCH")
                        and "themoviedb.org" in resposta.url
                        and "/tv/" in resposta.url)
            try:
                with page.expect_response(eh_envio, timeout=20000) as info:
                    btn.click()
                resposta = info.value
            except Exception:
                return False
            if resposta.status >= 400:
                return False
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            return True
        return False

    def rotina_automacao(self, tv_id, season, idioma):
        delay = 4
        sucesso, falhas = [], []
        try:
            try:
                episodios = self.ler_csv()
            except Exception as e:
                self.escrever_log(f"Erro ao ler os dados da planilha: {e}")
                return

            if not episodios:
                self.escrever_log("Nenhum dado válido encontrado dentro desse arquivo. Verifique os cabeçalhos.")
                return
            if not STORAGE.exists():
                self.escrever_log("ERRO: Login não encontrado. Faça o Login primeiro.")
                return

            idioma_attr = idioma.replace("-", "_")  # "pt-BR" -> "pt_BR"
            self.escrever_log(f"Iniciando atualização de {len(episodios)} episódios...")

            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=False)
                context = browser.new_context(storage_state=str(STORAGE))
                page = context.new_page()

                for ep in sorted(episodios):
                    dados = episodios[ep]
                    self.escrever_log(f"[Episódio {ep}] Abrindo formulário...")
                    url = f"https://www.themoviedb.org/tv/{tv_id}/season/{season}/episode/{ep}/edit?language={idioma}"
                    try:
                        page.goto(url)
                        page.wait_for_load_state("networkidle")
                    except Exception as e:
                        self.escrever_log(f" -> Falha ao abrir a página: {e}")
                        falhas.append(ep)
                        continue

                    if "/login" in page.url:
                        self.escrever_log("ERRO: Sessão expirada. Faça login novamente.")
                        falhas.extend(e for e in sorted(episodios) if e >= ep)
                        break

                    for seletor in ["button:has-text('Accept')", "button:has-text('Aceitar')", "button:has-text('Agree')"]:
                        try:
                            if page.locator(seletor).count() > 0:
                                page.locator(seletor).first.click()
                        except Exception:
                            pass

                    # Encontra TODOS os campos antes de alterar qualquer coisa:
                    # se faltar algum, o episódio é pulado sem salvar nada pela metade.
                    campo_t = self.achar_campo_titulo(page, idioma_attr) if dados["titulo"] else None
                    campo_s = self.achar_campo_sinopse(page, idioma_attr) if dados["sinopse"] else None
                    faltando = [nome for nome, quer, campo in (
                        ("título", dados["titulo"], campo_t),
                        ("sinopse", dados["sinopse"], campo_s)) if quer and not campo]
                    if faltando:
                        self.escrever_log(f" -> Campo de {' e '.join(faltando)} ({idioma}) não encontrado. "
                                          "Episódio pulado, nada foi salvo.")
                        page.screenshot(path=str(PASTA / f"erro_campos_ep_{ep}.png"))
                        falhas.append(ep)
                        continue

                    if campo_t:
                        self.preencher(campo_t, dados["titulo"])
                        self.escrever_log(f" -> Título: {dados['titulo']}")
                    if campo_s:
                        self.preencher(campo_s, dados["sinopse"])
                        self.escrever_log(" -> Sinopse preenchida.")

                    if self.salvar_e_confirmar(page):
                        self.escrever_log(f"[Episódio {ep}] Salvo e confirmado pelo TMDB.")
                        sucesso.append(ep)
                    else:
                        self.escrever_log(f"[Episódio {ep}] NÃO confirmado: o TMDB não saiu da tela de edição.")
                        page.screenshot(path=str(PASTA / f"erro_salvar_ep_{ep}.png"))
                        falhas.append(ep)

                    time.sleep(delay)

                browser.close()

            self.escrever_log(f"\n=== Concluído: {len(sucesso)} salvos, {len(falhas)} com falha ===")
            if falhas:
                self.escrever_log("Episódios com falha: " + ", ".join(map(str, falhas)))
        except Exception as e:
            self.escrever_log(f"Ocorreu um erro na execução: {e}")
        finally:
            self.na_ui(self.liberar_botoes)

    def liberar_botoes(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_login.configure(state="normal")
        self.btn_csv.configure(state="normal")
        self.btn_buscar_seasons.configure(state="normal", text="🔍  Buscar")


if __name__ == "__main__":
    raiz = ctk.CTk()
    raiz.geometry("1050x760")
    janela = AppTMDB(raiz)
    janela.pack(fill="both", expand=True)
    raiz.mainloop()
