"""Ponte entre a tela (HTML em ui/) e o núcleo. Cada método público pode ser
chamado pelo JavaScript da tela (window.pywebview.api.<método>).

A lista de episódios mora aqui; a tela recebe avisos por `app.evento({...})`.
"""
import json
import re
import threading

import pyperclip
import webview

import atualizador
import nucleo
from automatizador import STORAGE
from instrucoes import ARQUIVO_INSTRUCOES, PROMPT_PADRAO, carregar_instrucoes

VERSAO = "1.3"
FINALIZADOS = ("Enviado", "Já preenchido")
INCOMPLETOS = ("Sem texto", "Sem sinopse")
ARQUIVO_HISTORICO = nucleo.PASTA / "historico_envios.json"
LIMITE_HISTORICO = 5000
# Por série (código TMDB): glossário e últimos links de Wiki/TVDB usados.
ARQUIVO_SERIES = nucleo.PASTA / "series_salvas.json"


_COMUNS = {"The", "A", "An", "And", "But", "When", "While", "After", "Before", "With", "As",
           "In", "On", "At", "To", "Of", "For", "From", "However", "Meanwhile", "Then", "Now",
           "His", "Her", "Their", "Its", "This", "That", "These", "Those", "He", "She", "They",
           "It", "We", "I", "You", "Can", "Will", "One", "Two", "Three", "Episode", "Part",
           "Earth", "Japan", "Tokyo", "Christmas", "Is", "Are", "Was", "Not", "No", "If",
           "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


def _nomes_proprios(texto):
    """Palavras com maiúscula no meio da frase (prováveis nomes próprios),
    que normalmente não deveriam ser traduzidas."""
    nomes = []
    for frase in re.split(r"(?<=[.!?])\s+", texto):
        palavras = re.findall(r"[A-Za-zÀ-ÿ][\w'\-]*", frase)
        for p in palavras[1:]:
            limpo = re.sub(r"'s$", "", p)
            if limpo[:1].isupper() and len(limpo) >= 3 and limpo not in _COMUNS \
                    and limpo not in nomes:
                nomes.append(limpo)
    return nomes


def ler_series():
    try:
        return json.loads(ARQUIVO_SERIES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def gravar_serie(codigo, nome="", **campos):
    codigo = str(codigo or "")
    if not codigo.isdigit():
        return
    dados = ler_series()
    item = dados.setdefault(codigo, {})
    if nome:
        item["nome"] = nome
    item.update(campos)
    ARQUIVO_SERIES.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


class Api:
    def __init__(self):
        self._janela = None
        self._trava = threading.Lock()
        self._ocupado = False
        self._parar = False
        self._proximo_id = 1
        self.visivel = False
        self.episodios = []
        self.serie = {"codigo": "", "nome": "", "ano": "", "poster": "", "temporadas": [],
                      "temporada": "1"}
        self.idioma = nucleo.ler_config().get("idioma", "pt-BR")

    # ------------------------------------------------------------- interno
    def ligar(self, janela):
        self._janela = janela

    def tema_janela(self, tema):
        """Pinta a barra de título do Windows com o tema da tela (escuro ou claro)."""
        import barra_titulo
        if not self._janela:
            return {"ok": False}
        return {"ok": barra_titulo.pintar(self._janela.title, "claro" if tema == "claro" else "escuro")}

    def _avisar_tela(self, tipo, **dados):
        if not self._janela:
            return
        try:
            self._janela.evaluate_js(
                f"window.app && app.evento({json.dumps(dict(dados, tipo=tipo))})")
        except Exception:
            pass

    def _estado(self):
        return {"episodios": self.episodios, "serie": self.serie, "idioma": self.idioma,
                "ocupado": self._ocupado, "visivel": self.visivel}

    def _publicar(self):
        self._mexeu = True
        self._avisar_tela("estado", estado=self._estado())
        self._salvar_trabalho()

    def _salvar_trabalho(self):
        # Trava: se a lista nunca foi carregada nem mexida nesta sessão (ex.: a tela não
        # abriu direito), não grava uma lista vazia por cima do trabalho guardado.
        if not self.episodios and not getattr(self, "_mexeu", False):
            return
        dados = {"versao": VERSAO, "serie": self.serie, "idioma": self.idioma,
                 "episodios": self.episodios}
        try:
            nucleo.ARQUIVO_TRABALHO.write_text(json.dumps(dados, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
        except OSError:
            pass

    def _novo_episodio(self, base, **extra):
        e = {"id": self._proximo_id, "codigo": "", "temporada": "", "serie": "", "ano": "",
             "poster": "", "numero": 0, "titulo": "", "sinopse": "", "original_titulo": "",
             "original_sinopse": "", "atual_titulo": "", "atual_sinopse": "",
             "enviar": True, "situacao": "Original"}
        e.update(base)
        e.update(extra)
        e["codigo"], e["temporada"] = str(e["codigo"]), str(e["temporada"])
        e["numero"] = int(e["numero"])
        self._proximo_id += 1
        return e

    def _trocar_lista(self, episodios):
        self.episodios = episodios
        self._publicar()

    def _em_segundo_plano(self, rotina, *args):
        with self._trava:
            if self._ocupado:
                self._avisar_tela("aviso", texto="Espere a tarefa atual terminar.")
                return False
            self._ocupado = True
            self._parar = False
        self._avisar_tela("ocupado", valor=True)

        def rodar():
            try:
                rotina(*args)
            except nucleo.ErroAPI as erro:
                self._log(f"Erro: {erro}.")
                self._avisar_tela("aviso", texto=f"Erro: {erro}.")
            except Exception as erro:
                self._log(f"Erro: {erro}")
                self._avisar_tela("aviso", texto=f"Erro: {erro}")
            finally:
                self._ocupado = False
                self._avisar_tela("ocupado", valor=False)
                self._salvar_trabalho()
        threading.Thread(target=rodar, daemon=True).start()
        return True

    def _log(self, texto):
        self._avisar_tela("log", texto=texto)

    def _aviso_nucleo(self, tipo, **dados):
        if tipo == "log":
            self._log(dados["texto"])
        elif tipo == "progresso":
            self._avisar_tela("progresso", **dados)
        elif tipo == "situacao":
            e = self._por_id(dados["id"])
            if e:
                valor = dados["valor"]
                if valor == "Pendente":
                    valor = e.get("_antes", e["situacao"])
                elif valor == "Enviando":
                    e["_antes"] = e["situacao"]
                e["situacao"] = valor
                if valor in FINALIZADOS:
                    e["enviar"] = False
                self._avisar_tela("episodio", episodio=e)
        elif tipo == "aviso":
            self._log(dados["texto"])
            self._avisar_tela("aviso", texto=dados["texto"])
        elif tipo == "historico":
            self._registrar_historico(dados["registro"])
        elif tipo == "pedir_login":
            self._avisar_tela("login", estado="expirado")
            self._avisar_tela("pedir_login")

    # ------------------------------------------------------------ histórico
    def _ler_historico_arquivo(self):
        try:
            return json.loads(ARQUIVO_HISTORICO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _registrar_historico(self, registro):
        with self._trava:
            historico = self._ler_historico_arquivo()
            registro["id"] = f"{registro['quando']}-{len(historico)}"
            historico.append(registro)
            try:
                ARQUIVO_HISTORICO.write_text(
                    json.dumps(historico[-LIMITE_HISTORICO:], ensure_ascii=False, indent=1),
                    encoding="utf-8")
            except OSError:
                pass

    def _por_id(self, ident):
        return next((e for e in self.episodios if e["id"] == ident), None)

    def _dialogo(self, salvar, nome="", titulo=""):
        tipo = webview.SAVE_DIALOG if salvar else webview.OPEN_DIALOG
        kwargs = {"file_types": ("Planilha CSV (*.csv)", "Todos os arquivos (*.*)")}
        if salvar:
            kwargs["save_filename"] = nome
        resultado = self._janela.create_file_dialog(tipo, **kwargs)
        if not resultado:
            return None
        return resultado if isinstance(resultado, str) else resultado[0]

    # ============================================================ início
    def iniciar(self):
        pendente = None
        try:
            dados = json.loads(nucleo.ARQUIVO_TRABALHO.read_text(encoding="utf-8"))
            episodios = dados.get("episodios", [])
            # Arquivos de versões antigas não tinham série/temporada em cada episódio.
            for ep in episodios:
                ep.setdefault("codigo", dados.get("codigo", ""))
                ep.setdefault("temporada", dados.get("temporada", ""))
                ep.setdefault("serie", dados.get("serie", "") if isinstance(dados.get("serie"),
                                                                            str) else "")
                if ep.get("situacao") == "Enviado ✔":
                    ep["situacao"] = "Enviado"
            faltam = [e for e in episodios if e.get("situacao") not in FINALIZADOS]
            if faltam:
                grupos = []
                for e in episodios:
                    g = nucleo.nome_grupo(e)
                    if g not in grupos:
                        grupos.append(g)
                pendente = {"grupos": grupos, "faltam": len(faltam), "total": len(episodios)}
                self._guardado = dados
        except (OSError, ValueError):
            pass
        config = nucleo.ler_config()
        return {"estado": self._estado(), "pendente": pendente, "versao": VERSAO,
                "tem_chave": bool(config.get("chave_tmdb")),
                "login": "verificando" if STORAGE.exists() else "desconectado"}

    def continuar_trabalho(self):
        dados = getattr(self, "_guardado", None)
        if not dados:
            return self._estado()
        if isinstance(dados.get("serie"), dict):
            self.serie.update(dados["serie"])
        self.idioma = dados.get("idioma", self.idioma)
        self.episodios = [self._novo_episodio(
            {k: v for k, v in e.items() if k not in ("id", "_antes")}) for e in dados["episodios"]]
        self._limpar_provisorios()
        self._publicar()
        return self._estado()

    def _limpar_provisorios(self):
        """Textos como "To be added" que vieram da Wiki antes da correção viram vazio."""
        n = sum(nucleo.limpar_provisorios(e) for e in self.episodios)
        if n:
            self._log(f"{n} episódio(s) foram corrigidos ao abrir (códigos como “&#039;” no "
                      "título ou texto provisório como “To be added”).")
        return n

    def verificar_login(self):
        def conferir():
            try:
                valido = nucleo.login_valido()
            except Exception:
                self._avisar_tela("login", estado="nao_verificado")
                return
            self._avisar_tela("login", estado={None: "desconectado", True: "conectado",
                                               False: "expirado"}[valido])
        threading.Thread(target=conferir, daemon=True).start()

    def entrar(self):
        def rotina():
            self._log("Entre com sua conta na janela do TMDB. Ela fecha sozinha no final.")
            if nucleo.fazer_login(self._aviso_nucleo):
                self._log("Login feito e salvo!")
                self._avisar_tela("login", estado="conectado")
                self._avisar_tela("aviso", texto="Login no TMDB feito com sucesso.")
            else:
                self._log("A janela foi fechada antes de terminar o login.")
        return self._em_segundo_plano(rotina)

    def mostrar_navegador(self, valor):
        self.visivel = bool(valor)
        return self.visivel

    def parar(self):
        self._parar = True
        self._log("Parando depois do episódio atual...")

    # ======================================================== configuração
    def ler_config(self):
        c = nucleo.ler_config()
        chave = c.get("chave_tmdb", "")
        return {"tem_chave": bool(chave), "chave_final": chave[-4:] if chave else "",
                "idioma": c.get("idioma", "pt-BR"), "limite": c.get("limite", 350),
                "sinopse_temporada": bool(c.get("sinopse_temporada", False)),
                "conferir_prefixo": bool(c.get("conferir_prefixo", True)),
                "revisar_envio": bool(c.get("revisar_envio", True)),
                "analisar_idiomas": bool(c.get("analisar_idiomas", True)),
                "pagina_serie": bool(c.get("pagina_serie", True)),
                "atualizacoes": bool(c.get("atualizacoes", True))}

    def _com_temporada(self):
        """Opção (desligada por padrão): importar também a sinopse da temporada."""
        return bool(nucleo.ler_config().get("sinopse_temporada", False)) and \
            bool(nucleo.tmdb_configurado())

    def testar_chave(self, chave):
        try:
            nucleo.TMDB(chave).testar()
            return {"ok": True}
        except nucleo.ErroAPI as erro:
            return {"ok": False, "erro": str(erro)}

    def salvar_config(self, chave, idioma, limite, sinopse_temporada=False,
                      conferir_prefixo=True, revisar_envio=True, analisar_idiomas=True,
                      pagina_serie=True, atualizacoes=True):
        c = nucleo.ler_config()
        c["atualizacoes"] = bool(atualizacoes)
        c["pagina_serie"] = bool(pagina_serie)
        c["analisar_idiomas"] = bool(analisar_idiomas)
        c["sinopse_temporada"] = bool(sinopse_temporada)
        c["conferir_prefixo"] = bool(conferir_prefixo)
        c["revisar_envio"] = bool(revisar_envio)
        if chave is not None:
            c["chave_tmdb"] = chave.strip()
        c["idioma"] = idioma
        c["limite"] = int(limite)
        nucleo.salvar_config(c)
        self.idioma = idioma
        self._publicar()
        return self.ler_config()

    # =========================================================== atualização
    def procurar_atualizacao(self, manual=False):
        """Opção (ligada por padrão): ao abrir, olha se há versão nova no GitHub."""
        if not manual and not nucleo.ler_config().get("atualizacoes", True):
            return {"nova": None}
        try:
            nova = atualizador.procurar(VERSAO)
        except Exception:
            return {"nova": None, "erro": "Não foi possível falar com o GitHub agora."}
        return {"nova": nova, "pode_instalar": atualizador.instalado()}

    def instalar_atualizacao(self, url):
        def rotina():
            try:
                ultimo = [-1]

                def progresso(feito, total):
                    pct = int(feito * 100 / total)
                    if pct != ultimo[0]:
                        ultimo[0] = pct
                        self._avisar_tela("atualizacao", pct=pct)
                pasta = atualizador.baixar_e_preparar(url, progresso)
                self._avisar_tela("atualizacao", pct=100, pronto=True)
                atualizador.trocar_e_reabrir(pasta)
                self._salvar_trabalho()
                self._janela.destroy()
            except Exception as erro:
                self._avisar_tela("atualizacao", erro=str(erro))
        threading.Thread(target=rotina, daemon=True).start()
        return {"ok": True}

    # ================================================================ série
    def buscar_series(self, texto):
        texto = (texto or "").strip()
        if not texto:
            return {"resultados": []}
        api = nucleo.tmdb_configurado()
        try:
            if texto.isdigit():
                s = nucleo.info_serie(texto, self.visivel)
                return {"resultados": [{"codigo": s["codigo"], "nome": s["nome"],
                                        "ano": s["ano"], "poster": s["poster"]}]}
            if not api:
                return {"erro": "Para buscar pelo nome, coloque a chave da API do TMDB em "
                                "Configurações. Sem ela, digite o código da série."}
            return {"resultados": api.buscar(texto)}
        except nucleo.ErroAPI as erro:
            return {"erro": f"Não consegui buscar: {erro}."}
        except Exception as erro:
            return {"erro": f"Não consegui buscar: {erro}"}

    def escolher_serie(self, codigo):
        def rotina():
            self._avisar_tela("progresso", atual=0, total=0, texto="Carregando a série...")
            s = nucleo.info_serie(codigo, self.visivel)
            numeros = [t["numero"] for t in s["temporadas"]]
            s["temporada"] = "1" if 1 in numeros else (str(numeros[0]) if numeros else "1")
            self.serie = s
            self._publicar()
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"{s['nome']} ({s['ano']}) · {len(numeros)} temporadas")
        return self._em_segundo_plano(rotina)

    def definir(self, campo, valor):
        if campo == "temporada":
            self.serie["temporada"] = str(valor)
        elif campo == "idioma":
            self.idioma = valor
        self._salvar_trabalho()
        return self._estado()

    # ============================================================ importar
    def _grupo_atual(self):
        temp = self.serie.get("temporada", "1")
        poster = next((t.get("poster") for t in self.serie.get("temporadas", [])
                       if str(t["numero"]) == str(temp) and t.get("poster")), "") \
            or self.serie.get("poster", "")
        return {"codigo": self.serie.get("codigo", ""), "temporada": temp,
                "serie": self.serie.get("nome", ""), "ano": self.serie.get("ano", ""),
                "poster": poster}

    def _com_pagina_serie(self, codigo, temporada, eps):
        """Opcional (ligado): põe no topo da temporada o item "SÉRIE" (nome e sinopse) e a
        sinopse da temporada. Marcados só quando a série ainda não tem português no TMDB."""
        if not nucleo.ler_config().get("pagina_serie", True):
            return eps
        try:
            extras, tem = nucleo.itens_pagina_serie(codigo, temporada, self.idioma)
        except Exception as erro:
            self._log(f"Não consegui conferir a página da série ({erro}).")
            return eps
        if any(e.get("tipo") == "temporada" for e in eps):
            extras = [x for x in extras if x.get("tipo") != "temporada"]
        if extras and not tem:
            self._log("A série ainda não tem tradução em português no TMDB: o item “SÉRIE” "
                      "veio marcado e é enviado primeiro, liberando os episódios.")
        return extras + list(eps)

    def analisar_idiomas(self):
        """Opcional: em quais idiomas a temporada escolhida tem texto no TMDB."""
        if not str(self.serie.get("codigo", "")).isdigit():
            return {"erro": "Escolha a série primeiro (busque pelo nome ou código)."}
        if not nucleo.tmdb_configurado():
            return {"sem_chave": True}
        grupo = self._grupo_atual()
        try:
            r = nucleo.idiomas_temporada(grupo["codigo"], grupo["temporada"], self.idioma)
        except Exception as erro:
            return {"erro": f"Não consegui analisar os idiomas: {erro}"}
        return dict(r, serie=grupo["serie"], temporada=grupo["temporada"])

    def importar_tmdb(self, ordem=None):
        if not str(self.serie.get("codigo", "")).isdigit():
            return {"erro": "Escolha a série primeiro (busque pelo nome ou código)."}
        grupo = self._grupo_atual()
        ordem = [c for c in (ordem or []) if c]

        def rotina():
            self._avisar_tela("progresso", atual=0, total=0,
                              texto=f"Importando {grupo['serie']} · Temporada {grupo['temporada']}...")
            if ordem and ordem != ["en-US"] and nucleo.tmdb_configurado():
                eps = nucleo.episodios_tmdb_idiomas(grupo["codigo"], grupo["temporada"], ordem,
                                                    self.idioma, com_temporada=self._com_temporada())
            else:
                eps = nucleo.episodios_tmdb(grupo["codigo"], grupo["temporada"], self.visivel,
                                            self._aviso_nucleo, com_temporada=self._com_temporada())
            if not eps:
                self._avisar_tela("aviso", texto="Não encontrei episódios nessa temporada.")
                return
            eps = self._com_pagina_serie(grupo["codigo"], grupo["temporada"], eps)
            self._trocar_lista([self._novo_episodio(grupo, fonte="TMDB", **e) for e in eps])
            outros = sorted({c for e in eps for c in (e.get("idioma_titulo"), e.get("idioma_sinopse"))
                             if c and not c.startswith("en")})
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"{len(eps)} episódios importados do TMDB"
                                    + (f" (inglês + {', '.join(outros)})." if outros else " em inglês."))
            if nucleo.ler_config().get("conferir_prefixo", True):
                self._procurar_prefixo(f"{grupo['codigo']}|{grupo['temporada']}", automatico=True)
        return {"ok": self._em_segundo_plano(rotina)}

    # ================================= prefixo que o TMDB não traz (pela Wiki)
    def _procurar_prefixo(self, chave, automatico=False):
        """Lê a Wiki salva da série e, se ela numera os títulos com um prefixo
        próprio (Quest 01:, Space.1:...) que a lista não tem, avisa a tela."""
        codigo = chave.split("|")[0]
        grupo = [e for e in self.episodios if f"{e['codigo']}|{e['temporada']}" == chave
                 and e.get("tipo") != "temporada"]
        if not grupo:
            return
        if nucleo.tem_prefixo([e["titulo"] for e in grupo]):
            if not automatico:
                self._avisar_tela("aviso", texto="Os títulos dessa temporada já têm prefixo.")
            return
        link = ler_series().get(codigo, {}).get("wiki", "")
        if not link:
            if not automatico:
                self._avisar_tela("aviso", texto="Ainda não há link da Wiki salvo para essa "
                                                 "série. Importe ou complemente pela Wiki uma vez.")
            return
        self._log("Conferindo na Wiki se a série usa prefixo nos títulos...")
        try:
            eps = nucleo.episodios_wiki(link, self.visivel, self._aviso_nucleo, lambda: self._parar)
        except Exception as erro:
            self._log(f"Não consegui ler a Wiki: {erro}")
            return
        achado = nucleo.detectar_prefixo([e.get("titulo", "") for e in eps or []])
        if not achado:
            self._log("A Wiki não usa prefixo nos títulos.")
            if not automatico:
                self._avisar_tela("aviso", texto="A Wiki dessa série não usa prefixo nos títulos.")
            return
        modelo, dois = achado
        exemplo = next((e for e in grupo if e["titulo"].strip()), grupo[0])
        n = str(exemplo["numero"]).zfill(2) if dois else str(exemplo["numero"])
        self._avisar_tela("prefixo", chave=chave, modelo=modelo, dois=dois,
                          serie=exemplo.get("serie", ""),
                          exemplo=modelo.replace("{n}", n) + " " + exemplo["titulo"].strip())

    def descobrir_prefixo(self, chave):
        return {"ok": self._em_segundo_plano(lambda: self._procurar_prefixo(chave))}

    def _conferir_com_tmdb(self, eps, codigo, temporada, fonte):
        """Compara a quantidade de episódios lidos (Wiki/TVDB) com a do TMDB e avisa
        se não bater, dizendo quais números faltam ou sobram."""
        if not str(codigo).isdigit():
            return
        esperado = 0
        try:
            if str(codigo) == str(self.serie.get("codigo")):
                temps = self.serie.get("temporadas", [])
            else:
                api = nucleo.tmdb_configurado()
                temps = api.serie(codigo)["temporadas"] if api else []
            esperado = next((t.get("episodios", 0) for t in temps
                             if str(t["numero"]) == str(temporada)), 0)
        except Exception:
            return
        if not esperado:
            return  # sem a contagem do TMDB (ex.: sem chave da API), não dá para comparar
        numeros = {e["numero"] for e in eps}
        faltam = sorted(set(range(1, esperado + 1)) - numeros)
        sobram = sorted(n for n in numeros if n > esperado)
        if not faltam and not sobram and len(eps) == esperado:
            self._log(f"Conferido com o TMDB: {esperado} episódios, tudo certo.")
            return
        texto = f"{fonte}: {len(eps)} episódios; o TMDB tem {esperado} nessa temporada."
        if faltam:
            texto += f" Faltando: {', '.join(map(str, faltam[:15]))}{' ...' if len(faltam) > 15 else ''}."
        if sobram:
            texto += f" A mais: {', '.join(map(str, sobram[:15]))}{' ...' if len(sobram) > 15 else ''}."
        self._log(texto + " Confira a numeração antes de enviar.")
        self._avisar_tela("aviso", texto=texto + " Confira a numeração antes de enviar.")

    def importar_wiki(self, url):
        grupo = self._grupo_atual()
        gravar_serie(grupo["codigo"], grupo.get("serie", ""), wiki=url)

        def rotina():
            eps = nucleo.episodios_wiki(url, self.visivel, self._aviso_nucleo,
                                        lambda: self._parar)
            if not eps:
                self._avisar_tela("aviso", texto="Não encontrei a lista de episódios nessa "
                                                 "página da Wiki.")
                return
            self._trocar_lista([self._novo_episodio(grupo, fonte="Wiki", **e) for e in eps])
            self._conferir_com_tmdb(eps, grupo["codigo"], grupo["temporada"], "Wiki")
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"{len(eps)} episódios importados da Wiki.")
        return {"ok": self._em_segundo_plano(rotina)}

    def sugerir_wiki(self, nome):
        """Opcional: sugere páginas do Fandom para a série (você escolhe se usa)."""
        nome = (nome or "").strip() or self.serie.get("nome", "")
        if not nome:
            return {"erro": "Escolha a série no topo (ou digite o nome) para buscar a Wiki."}
        try:
            return {"sugestoes": nucleo.sugerir_wikis(nome, self.visivel), "nome": nome}
        except Exception as erro:
            return {"erro": f"Não consegui buscar no Fandom: {erro}"}

    def importar_tvdb(self, link, temporada):
        if not nucleo.slug_tvdb(link):
            return {"erro": "Cole o link da série no TVDB (ex.: https://thetvdb.com/series/nome)."}
        grupo = self._grupo_atual()
        gravar_serie(grupo["codigo"], grupo.get("serie", ""), tvdb=link)
        temporada = str(temporada or grupo["temporada"] or "1")
        grupo["temporada"] = temporada

        def rotina():
            eps = nucleo.episodios_tvdb(link, temporada, self.visivel, self._aviso_nucleo,
                                        lambda: self._parar)
            if not eps:
                self._avisar_tela("aviso", texto=f"Não encontrei episódios na temporada "
                                                 f"{temporada} desse link do TVDB.")
                return
            self._trocar_lista([self._novo_episodio(grupo, fonte="TVDB", **e) for e in eps])
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"{len(eps)} episódios importados do TVDB.")
            self._conferir_com_tmdb(eps, grupo["codigo"], temporada, "TVDB")
        return {"ok": self._em_segundo_plano(rotina)}

    # ======================================================== complementar

    def faltando(self):
        """Grupos (série/temporada) com episódios sem texto original, para o Complementar."""
        grupos = {}
        for e in self.episodios:
            if e["situacao"] in INCOMPLETOS:
                chave = f"{e['codigo']}|{e['temporada']}"
                g = grupos.setdefault(chave, {"chave": chave, "nome": nucleo.nome_grupo(e),
                                              "temporada": e["temporada"], "numeros": []})
                g["numeros"].append(e["numero"])
        return {"grupos": list(grupos.values())}

    def complementar(self, link, chave, temporada_fonte):
        """Busca em outro site (TVDB ou Wiki) só o texto que falta nos episódios
        "Sem texto"/"Sem sinopse" de um grupo, casando pelo número do episódio."""
        link = (link or "").strip()
        if not (nucleo.eh_tvdb(link) or link.lower().startswith("http")):
            return {"erro": "Cole um link do TVDB ou de uma Wiki (começando com http)."}
        alvo = [e for e in self.episodios if f"{e['codigo']}|{e['temporada']}" == chave
                and e["situacao"] in INCOMPLETOS]
        if not alvo:
            return {"erro": "Não há episódios sem texto nessa temporada."}
        numeros = {e["numero"] for e in alvo}
        gravar_serie(alvo[0]["codigo"], alvo[0].get("serie", ""),
                     **({"tvdb": link} if nucleo.eh_tvdb(link) else {"wiki": link}))

        def rotina():
            self._log(f"Complementando {len(alvo)} episódio(s) com {link}...")
            if nucleo.eh_tvdb(link):
                achados = nucleo.episodios_tvdb(link, temporada_fonte, self.visivel,
                                                self._aviso_nucleo, lambda: self._parar,
                                                apenas=numeros)
            else:
                achados = nucleo.episodios_wiki(link, self.visivel, self._aviso_nucleo,
                                                lambda: self._parar, apenas=numeros)
            por_numero = {a["numero"]: a for a in achados}
            completos = parciais = 0
            for e in alvo:
                novo = por_numero.get(e["numero"])
                if not novo:
                    continue
                ganhou = False
                for campo in ("titulo", "sinopse"):
                    original = novo.get(f"original_{campo}") or ""
                    if original and not e.get(f"original_{campo}"):
                        e[f"original_{campo}"] = original
                        if not (e.get(campo) or "").strip():
                            e[campo] = original
                        ganhou = True
                if novo.get("sinopse_do_plot") and e.get("original_sinopse") == novo.get("original_sinopse"):
                    e["sinopse_do_plot"] = True
                for chave_ref in [k for k in novo if k.startswith("ref_pt") and novo[k]]:
                    e[chave_ref] = novo[chave_ref]  # português do TVDB, como referência
                if not ganhou:
                    continue
                e["fonte_complemento"] = "TVDB" if nucleo.eh_tvdb(link) else "Wiki"
                if e.get("original_sinopse"):
                    e["situacao"], e["enviar"] = "Complementado", True
                    completos += 1
                else:
                    e["situacao"] = "Sem sinopse"
                    parciais += 1
            self._publicar()
            faltam = len(alvo) - completos - parciais
            texto = f"Complementar: {completos} episódio(s) completados"
            if parciais:
                texto += f", {parciais} só com título"
            if faltam:
                texto += f", {faltam} não encontrados nesse site"
            self._avisar_tela("aviso", texto=texto + ".")
            self._log(texto + ".")
            self._avisar_tela("progresso", atual=1, total=1, texto=texto + ".")
        return {"ok": self._em_segundo_plano(rotina)}

    def conferir_lote(self, itens):
        """Valida as linhas da janela de lote antes de importar."""
        for item in itens:
            if not str(item.get("codigo", "")).isdigit():
                return {"erro": f"O código “{item.get('codigo', '')}” não é válido."}
            try:
                nucleo.interpretar_temporadas(item.get("temporadas", ""), [1])
            except ValueError as erro:
                return {"erro": f"Série {item['codigo']}: {erro}."}
        return {"ok": True}

    def importar_lote(self, itens):
        def rotina():
            novos, problemas = [], []
            total_series = len(itens)
            for n_serie, item in enumerate(itens, 1):
                if self._parar:
                    break
                codigo = str(item["codigo"])
                lote = f"Série {n_serie} de {total_series}"
                self._avisar_tela("progresso", atual=0, total=0,
                                  texto=f"{lote} · buscando a série {codigo}...")
                try:
                    s = nucleo.info_serie(codigo, self.visivel)
                except Exception as erro:
                    problemas.append(f"série {codigo} ({erro})")
                    continue
                disponiveis = [t["numero"] for t in s["temporadas"]]
                if not disponiveis:
                    problemas.append(f"série {codigo}: nenhuma temporada encontrada")
                    continue
                pedidas = nucleo.interpretar_temporadas(item.get("temporadas", ""), disponiveis)
                faltando = [n for n in pedidas if n not in disponiveis]
                if faltando:
                    problemas.append(f"{s['nome']}: temporada(s) "
                                     f"{', '.join(map(str, faltando))} não existe(m)")
                pedidas = [n for n in pedidas if n in disponiveis]
                wiki = (item.get("wiki") or "").strip()
                tvdb = nucleo.eh_tvdb(wiki)
                if wiki and not tvdb and len(pedidas) != 1:
                    problemas.append(f"{s['nome']}: o link da Wiki só vale para uma "
                                     "temporada; usei o TMDB")
                for temporada in pedidas:
                    if self._parar:
                        break
                    poster = next((t["poster"] for t in s["temporadas"]
                                   if t["numero"] == temporada and t.get("poster")), "") \
                        or s.get("poster", "")
                    grupo = {"codigo": codigo, "temporada": str(temporada), "serie": s["nome"],
                             "ano": s["ano"], "poster": poster}
                    rotulo = f"{lote} · {s['nome']} · T{temporada}"
                    if len(pedidas) > 1:
                        rotulo += f" ({pedidas.index(temporada) + 1} de {len(pedidas)} temporadas)"
                    self._avisar_tela("progresso", atual=0, total=0, texto=f"{rotulo} · começando...")

                    def aviso_lote(tipo, rotulo=rotulo, **dados):
                        # Põe "Série 2 de 3 · Nome · T1" na frente do andamento de cada episódio.
                        if tipo == "progresso" and dados.get("texto"):
                            dados["texto"] = f"{rotulo} · {dados['texto']}"
                        self._aviso_nucleo(tipo, **dados)
                    if tvdb:
                        eps = nucleo.episodios_tvdb(wiki, temporada, self.visivel,
                                                    aviso_lote, lambda: self._parar)
                    elif wiki and len(pedidas) == 1:
                        eps = nucleo.episodios_wiki(wiki, self.visivel, aviso_lote,
                                                    lambda: self._parar)
                    else:
                        eps = nucleo.episodios_tmdb(codigo, temporada, self.visivel,
                                                    aviso_lote,
                                                    com_temporada=self._com_temporada())
                    if eps and wiki:
                        esperado = next((t.get("episodios", 0) for t in s["temporadas"]
                                         if t["numero"] == temporada), 0)
                        if esperado and len(eps) != esperado:
                            problemas.append(f"{s['nome']} · Temporada {temporada}: o link trouxe "
                                             f"{len(eps)} episódios e o TMDB tem {esperado}")
                    if not eps:
                        problemas.append(f"{s['nome']} · Temporada {temporada}: nenhum episódio")
                    fonte = "TVDB" if tvdb else ("Wiki" if wiki and len(pedidas) == 1 else "TMDB")
                    if eps and temporada == pedidas[0]:
                        eps = self._com_pagina_serie(codigo, temporada, eps)
                    novos += [self._novo_episodio(grupo, fonte=fonte, **e) for e in eps]
                    self._log(f"{s['nome']} · Temporada {temporada}: {len(eps)} episódios.")
            for p in problemas:
                self._log(f"Aviso: {p}.")
            if problemas:
                self._avisar_tela("aviso", texto=f"{len(problemas)} aviso(s) no lote. "
                                                 "Veja em Mensagens.")
            if not novos:
                self._avisar_tela("aviso", texto="Nada foi importado no lote.")
                return
            self._trocar_lista(novos)
            grupos = len({(e["codigo"], e["temporada"]) for e in novos})
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"Lote importado: {len(novos)} episódios em {grupos} "
                                    "temporadas.")
        return {"ok": self._em_segundo_plano(rotina)}

    # ============================================================ planilha
    def abrir_planilha(self):
        caminho = self._dialogo(False)
        if not caminho:
            return {"cancelado": True}
        grupo = self._grupo_atual()
        try:
            linhas, ignoradas = nucleo.ler_planilha(caminho, grupo)
        except Exception as erro:
            return {"erro": f"Não consegui abrir a planilha: {erro}"}
        if not linhas:
            return {"erro": "A planilha não tem episódios válidos. Use o modelo como base."}
        novos = []
        for l in linhas:
            mesmo = l["codigo"] == grupo["codigo"]
            novos.append(self._novo_episodio(
                l, serie=grupo["serie"] if mesmo else "", ano=grupo["ano"] if mesmo else "",
                poster=grupo["poster"] if mesmo else "", situacao="Editado"))
        self._trocar_lista(novos)
        texto = f"{len(novos)} episódios importados da planilha."
        if ignoradas:
            texto += f" {ignoradas} linha(s) vazias foram ignoradas."
        return {"ok": True, "texto": texto}

    def exportar_planilha(self):
        if not self.episodios:
            return {"erro": "Ainda não há episódios para exportar."}
        grupos = {(e["codigo"], e["temporada"]) for e in self.episodios}
        if len(grupos) == 1:
            e = self.episodios[0]
            nome = f"{e.get('serie') or 'episodios'} T{e['temporada']}.csv"
        else:
            nome = "lote_episodios.csv"
        caminho = self._dialogo(True, "".join(c for c in nome if c not in '\\/:*?"<>|'))
        if not caminho:
            return {"cancelado": True}
        nucleo.escrever_planilha(caminho, self.episodios)
        return {"ok": True, "texto": f"Planilha exportada em {caminho}."}

    def baixar_modelo(self):
        caminho = self._dialogo(True, "modelo_sentai_studio.csv")
        if not caminho:
            return {"cancelado": True}
        nucleo.escrever_modelo(caminho)
        return {"ok": True, "texto": "Modelo salvo. As colunas codigo_tmdb e temporada podem "
                                     "ficar vazias: aí vale a série escolhida no topo."}

    # ============================================================== lista
    def editar(self, ident, campo, valor):
        e = self._por_id(ident)
        if not e or campo not in ("titulo", "sinopse"):
            return None
        e[campo] = valor
        if e["situacao"] in ("Original", "Traduzido", "Enviado", "Falhou", "Já preenchido",
                             "Sem texto", "Sem sinopse", "Complementado"):
            e["situacao"] = "Editado"
        self._salvar_trabalho()
        return e

    def editar_original(self, ident, titulo, sinopse, idioma=""):
        """O usuário escreve (ou corrige) o texto ORIGINAL de um episódio, em qualquer
        idioma. Se o episódio ainda não foi traduzido, o texto também vai para os campos
        de tradução, para entrar no próximo "Copiar para traduzir"."""
        e = self._por_id(ident)
        if not e:
            return {"erro": "Episódio não encontrado."}
        titulo, sinopse = (titulo or "").strip(), (sinopse or "").strip()
        nao_traduzido = e["situacao"] in ("Original", "Sem texto", "Sem sinopse", "Complementado")
        antes = {"titulo": e.get("original_titulo", ""), "sinopse": e.get("original_sinopse", "")}
        novos = {"titulo": titulo, "sinopse": sinopse}
        for campo, valor in novos.items():
            e[f"original_{campo}"] = valor
            if idioma:
                e[f"idioma_{campo}"] = idioma if valor else ""
            # Leva junto para a tradução se ainda não foi traduzido (ou estava igual ao original).
            if nao_traduzido or not (e.get(campo) or "").strip() or e.get(campo) == antes[campo]:
                e[campo] = valor
        if e["situacao"] in ("Sem texto", "Sem sinopse", "Original", "Complementado"):
            e["situacao"], e["enviar"] = "Original", True
            nucleo.classificar_original(e)
            if e["situacao"] == "Original" and (not antes["titulo"] or not antes["sinopse"]):
                e["situacao"], e["fonte_complemento"] = "Complementado", "você"
        self._publicar()
        return {"ok": True, "episodio": e,
                "texto": f"Texto original do episódio {e['numero']} atualizado."}

    def marcar(self, ident, valor):
        e = self._por_id(ident)
        if e:
            e["enviar"] = bool(valor)
            self._salvar_trabalho()
        return e

    def marcar_varios(self, ids, valor):
        for e in self.episodios:
            if e["id"] in ids:
                e["enviar"] = bool(valor)
        self._publicar()
        return self._estado()

    # ================================================ localizar e substituir
    def _ocorrencias(self, busca, troca, campos, maiusculas, palavra, so_marcados):
        import re
        if not busca:
            return None, []
        padrao = re.escape(busca)
        if palavra:
            padrao = rf"(?<!\w){padrao}(?!\w)"
        regex = re.compile(padrao, 0 if maiusculas else re.I)
        achados = []
        for e in self.episodios:
            if so_marcados and not e["enviar"]:
                continue
            for campo in campos:
                texto = e.get(campo) or ""
                if regex.search(texto):
                    achados.append({"id": e["id"], "campo": campo, "numero": e["numero"],
                                    "temporada": e["temporada"], "serie": e.get("serie", ""),
                                    "antes": texto, "depois": regex.sub(lambda _m: troca, texto),
                                    "vezes": len(regex.findall(texto))})
        return regex, achados

    def _ref_pt(self, e):
        prefixo = "ref_ptpt" if self.idioma == "pt-PT" else "ref_ptbr"
        return e.get(f"{prefixo}_titulo", ""), e.get(f"{prefixo}_sinopse", "")

    def usar_portugues_tvdb(self, ids):
        """Copia o título/sinopse em português que o TVDB tem para a tradução,
        sem passar pela IA. `ids` vazio = todos os pendentes que tiverem."""
        usados = 0
        for e in self.episodios:
            if (ids and e["id"] not in ids) or e["situacao"] in FINALIZADOS:
                continue
            titulo, sinopse = self._ref_pt(e)
            if not (titulo or sinopse):
                continue
            if titulo:
                e["titulo"] = titulo
            if sinopse:
                e["sinopse"] = sinopse
            e["situacao"], e["enviar"] = "Traduzido", True
            usados += 1
        if not usados:
            return {"erro": "Nenhum episódio com texto em português no TVDB."}
        self._publicar()
        return {"ok": True, "texto": f"Texto em português do TVDB usado em {usados} episódio(s). "
                                     "Confira antes de enviar."}

    def localizar(self, busca, troca, campos, maiusculas, palavra, so_marcados):
        _, achados = self._ocorrencias(busca, troca, campos, maiusculas, palavra, so_marcados)
        return {"total": sum(a["vezes"] for a in achados), "episodios": len({a["id"] for a in achados}),
                "itens": achados[:200]}

    def substituir(self, busca, troca, campos, maiusculas, palavra, so_marcados):
        _, achados = self._ocorrencias(busca, troca, campos, maiusculas, palavra, so_marcados)
        if not achados:
            return {"erro": "Nada encontrado para substituir."}
        for a in achados:
            e = self._por_id(a["id"])
            e[a["campo"]] = a["depois"]
            if e["situacao"] in ("Original", "Traduzido", "Falhou", "Complementado"):
                e["situacao"] = "Editado"
        self._publicar()
        total = sum(a["vezes"] for a in achados)
        return {"ok": True, "texto": f"{total} troca(s) feitas em "
                                     f"{len({a['id'] for a in achados})} episódio(s)."}

    # ================================================== ajustar numeração
    def ajustar_numeracao(self, chave, deslocar, a_partir_de):
        """Soma `deslocar` (pode ser negativo) ao número dos episódios do grupo
        a partir de um episódio. Ex.: a Wiki contou um especial e tudo andou uma casa."""
        deslocar, a_partir_de = int(deslocar), int(a_partir_de)
        grupo = [e for e in self.episodios if f"{e['codigo']}|{e['temporada']}" == chave
                 and e.get("tipo") != "temporada"]
        mover = [e for e in grupo if e["numero"] >= a_partir_de]
        if not deslocar or not mover:
            return {"erro": "Nada para ajustar com esses valores."}
        ficam = {e["numero"] for e in grupo if e["numero"] < a_partir_de}
        novos = [e["numero"] + deslocar for e in mover]
        if min(novos) < 0:
            return {"erro": "Assim algum episódio ficaria com número negativo."}
        if ficam & set(novos) or len(set(novos)) != len(novos):
            return {"erro": "Assim dois episódios ficariam com o mesmo número. Remova o "
                            "episódio repetido primeiro ou mude o “a partir do episódio”."}
        for e in mover:
            e["numero"] += deslocar
        grupo.sort(key=lambda e: e["numero"])
        self._reordenar()
        self._publicar()
        return {"ok": True, "texto": f"{len(mover)} episódio(s) renumerados "
                                     f"({'+' if deslocar > 0 else ''}{deslocar})."}

    # ================================================== prefixo dos títulos
    def prefixar_titulos(self, chave, modelo, dois_digitos):
        """Põe um prefixo numerado no título de cada episódio do grupo.
        Ex.: modelo "Missão {n}: " → "Missão 01: O Rugido do Leão!!".
        Útil quando a fonte (ex.: TMDB) não traz o "Quest 01:" que a série usa."""
        modelo = (modelo or "").strip()
        if not modelo:
            return {"erro": "Escreva o prefixo. Ex.: Missão {n}:"}
        if "{n}" not in modelo:
            modelo += " {n}:"
        if not modelo.endswith((" ", "-", "–", "—")):
            modelo += " "
        grupo = [e for e in self.episodios if f"{e['codigo']}|{e['temporada']}" == chave
                 and e.get("tipo") != "temporada" and (e.get("titulo") or "").strip()]
        fixo = modelo.split("{n}")[0].strip().lower()
        feitos = 0
        for e in grupo:
            if fixo and e["titulo"].strip().lower().startswith(fixo):
                continue
            n = str(e["numero"]).zfill(2) if dois_digitos else str(e["numero"])
            e["titulo"] = modelo.replace("{n}", n) + e["titulo"].strip()
            if e["situacao"] in ("Original", "Traduzido", "Falhou", "Complementado"):
                e["situacao"] = "Editado"
            feitos += 1
        if not feitos:
            return {"erro": "Nenhum título para mudar (talvez todos já tenham o prefixo)."}
        self._publicar()
        return {"ok": True, "texto": f"Prefixo colocado em {feitos} título(s)."}

    def remover(self, ids):
        antes = len(self.episodios)
        self.episodios = [e for e in self.episodios if e["id"] not in set(ids)]
        self._publicar()
        return {"ok": True, "texto": f"{antes - len(self.episodios)} episódio(s) removidos da lista."}

    def _reordenar(self):
        """Mantém a ordem dos grupos e ordena os episódios dentro de cada um."""
        ordem = []
        for e in self.episodios:
            g = (e["codigo"], e["temporada"])
            if g not in ordem:
                ordem.append(g)
        self.episodios.sort(key=lambda e: (ordem.index((e["codigo"], e["temporada"])), e["numero"]))

    def limpar(self):
        self._trocar_lista([])
        return self._estado()

    # ========================================================= tradução
    def copiar(self):
        # Só os marcados e ainda não enviados: episódios sem texto original já vêm
        # desmarcados e não atrapalham a tradução.
        lista = [e for e in self.episodios if e["enviar"] and e["situacao"] not in FINALIZADOS]
        if not lista:
            return {"erro": "Nenhum episódio marcado para traduzir." if self.episodios
                    else "Ainda não há episódios para copiar."}
        ids = {e["id"] for e in lista}
        # Só avisa dos que faltam nas mesmas temporadas que estão sendo traduzidas.
        grupos = {(e["codigo"], e["temporada"]) for e in lista}
        omitidos = [e for e in self.episodios
                    if e["id"] not in ids and (e["codigo"], e["temporada"]) in grupos]
        salvas, glossarios = ler_series(), []
        for codigo in dict.fromkeys(str(e["codigo"]) for e in lista):
            linhas = [l.strip() for l in salvas.get(codigo, {}).get("glossario", "").splitlines()
                      if l.strip()]
            if linhas:
                nome = next((e.get("serie") for e in lista if str(e["codigo"]) == codigo), codigo)
                glossarios.append((nome, linhas))
        pyperclip.copy(nucleo.texto_para_traduzir(lista, self.idioma, omitidos, glossarios))
        self._copiados = [e["id"] for e in lista]
        fora = len(self.episodios) - len(lista)
        texto = (f"{len(lista)} episódios copiados com as instruções. Cole no ChatGPT ou "
                 "Claude e depois clique em “Colar tradução”.")
        if fora:
            texto += f" ({fora} desmarcados ou já enviados ficaram de fora.)"
        return {"ok": True, "texto": texto}

    def colar(self):
        if not self.episodios:
            return {"erro": "Importe os textos originais antes de colar a tradução."}
        # As marcas ([5], [T2-E5]...) dependem de quais episódios foram copiados.
        ids = getattr(self, "_copiados", None)
        base = [e for e in self.episodios if e["id"] in ids] if ids else []
        traducoes = nucleo.ler_traducao(pyperclip.paste() or "", base or self.episodios)
        if not traducoes:
            return {"erro": "Não reconheci o texto copiado. Ele precisa ter as marcas dos "
                            "episódios (ex.: [1]), Título: e Sinopse:."}
        for ident, (titulo, sinopse) in traducoes.items():
            e = self._por_id(ident)
            if titulo is not None:
                e["titulo"] = titulo
            if sinopse is not None:
                e["sinopse"] = sinopse
            e["situacao"] = "Traduzido"
        self._publicar()
        return {"ok": True, "texto": f"Tradução colada em {len(traducoes)} episódios. "
                                     "Confira e envie."}

    # ============================================ glossário e links salvos
    def ler_glossarios(self):
        """Séries da lista (e as que já têm glossário), com o texto salvo de cada uma."""
        salvas, series = ler_series(), {}
        for e in self.episodios:
            if str(e["codigo"]).isdigit():
                series.setdefault(str(e["codigo"]), e.get("serie") or e["codigo"])
        if str(self.serie.get("codigo", "")).isdigit():
            series.setdefault(str(self.serie["codigo"]), self.serie.get("nome") or self.serie["codigo"])
        for codigo, item in salvas.items():
            if item.get("glossario"):
                series.setdefault(codigo, item.get("nome") or codigo)
        return {"series": [{"codigo": c, "nome": n, "texto": salvas.get(c, {}).get("glossario", "")}
                           for c, n in series.items()]}

    def salvar_glossario(self, codigo, nome, texto):
        if not str(codigo).isdigit():
            return {"erro": "Escolha uma série."}
        gravar_serie(codigo, nome, glossario=(texto or "").strip())
        return {"ok": True, "texto": "Glossário salvo. Ele vai junto no “Copiar para traduzir”."}

    def link_salvo(self, codigo=None):
        """Últimos links de Wiki/TVDB usados para a série (para preencher sozinho)."""
        codigo = str(codigo or self._grupo_atual()["codigo"] or "")
        item = ler_series().get(codigo, {})
        return {"wiki": item.get("wiki", ""), "tvdb": item.get("tvdb", "")}

    def ler_instrucoes(self):
        return {"texto": carregar_instrucoes(), "padrao": PROMPT_PADRAO}

    def salvar_instrucoes(self, texto):
        ARQUIVO_INSTRUCOES.write_text((texto or "").strip(), encoding="utf-8")
        return {"ok": True}

    # =============================================================== envio
    def _para_enviar(self):
        padrao = self._grupo_atual()
        itens, sem_codigo = [], 0
        for e in self.episodios:
            titulo = "" if nucleo.provisorio(e["titulo"]) else (nucleo.valor_valido(e["titulo"]) or "")
            sinopse = "" if nucleo.provisorio(e["sinopse"]) else (nucleo.valor_valido(e["sinopse"]) or "")
            if not e["enviar"] or not (titulo or sinopse):
                continue
            codigo = e["codigo"] or padrao["codigo"]
            if not str(codigo).isdigit():
                sem_codigo += 1
                continue
            itens.append({"id": e["id"], "codigo": codigo,
                          "temporada": e["temporada"] or padrao["temporada"],
                          "numero": e["numero"], "serie": e.get("serie", ""),
                          "tipo": e.get("tipo", "episodio"),
                          "titulo": titulo, "sinopse": sinopse,
                          "original_titulo": e.get("original_titulo", "")})
        return itens, sem_codigo

    def preparar_envio(self):
        if not STORAGE.exists():
            return {"precisa_login": True}
        itens, sem_codigo = self._para_enviar()
        grupos = {}
        existentes = {"titulo": 0, "sinopse": 0}
        conhecidos = 0
        for i in itens:
            chave = f"{i['serie'] or 'Série ' + str(i['codigo'])} — temporada {i['temporada']}"
            grupos[chave] = grupos.get(chave, 0) + 1
            e = self._por_id(i["id"])
            if e and e.get("via_api"):
                conhecidos += 1
                if i["titulo"] and nucleo.ja_preenchido(e.get("atual_titulo")):
                    existentes["titulo"] += 1
                if i["sinopse"] and e.get("atual_sinopse"):
                    existentes["sinopse"] += 1
        revisao = self._revisar(itens) if nucleo.ler_config().get("revisar_envio", True) else []
        return {"total": len(itens), "sem_codigo": sem_codigo, "idioma": self.idioma,
                "revisao": revisao,
                "grupos": [{"nome": k, "quantidade": v} for k, v in grupos.items()],
                "existentes": existentes,
                # Só dá para prever com dados da API (o que já existe no TMDB).
                "previsao": conhecidos == len(itens) and bool(itens)}

    # ================================================ revisão antes de enviar
    def _revisar(self, itens):
        """Aponta possíveis problemas na tradução. Só avisa; quem decide é o usuário."""
        limite = int(nucleo.ler_config().get("limite", 350))
        varios = len({(x["codigo"], x["temporada"]) for x in itens}) > 1
        avisos = []
        for i in itens:
            e = self._por_id(i["id"])
            if not e:
                continue
            rotulo = ("SÉRIE" if e.get("tipo") == "serie" else
                      "TEMP" if e.get("tipo") == "temporada" else "E" + str(e["numero"]).zfill(2))
            if varios:
                rotulo = f"{e.get('serie') or e['codigo']} T{e['temporada']} {rotulo}"
            achados = []
            t, ot = (e.get("titulo") or "").strip(), (e.get("original_titulo") or "").strip()
            s, os_ = (e.get("sinopse") or "").strip(), (e.get("original_sinopse") or "").strip()
            if t and ot and t == ot and len(t.split()) > 1:
                achados.append("título igual ao original (não traduzido?)")
            if s and os_ and s == os_:
                achados.append("sinopse igual à original (não traduzida?)")
            if len(s) > limite:
                achados.append(f"sinopse longa ({len(s)} de {limite} caracteres)")
            m = re.match(r"^\s*[^\W\d_]+(?:[ .][^\W\d_]+)?[ .]?#?(\d+)\s*[:.\-–—]", t)
            if m and e.get("tipo") != "temporada" and int(m.group(1)) != int(e["numero"]):
                achados.append(f"o título diz {int(m.group(1))}, mas é o episódio {e['numero']}")
            if s and os_ and s != os_:
                faltam = [n for n in _nomes_proprios(os_) if n.lower() not in s.lower()]
                if faltam:
                    achados.append("nome(s) que sumiram da sinopse: " + ", ".join(faltam[:4]))
            if achados:
                avisos.append({"id": e["id"], "rotulo": rotulo, "itens": achados})
        return avisos

    # ==================================================== trabalhos salvos
    def _pasta_trabalhos(self):
        pasta = nucleo.PASTA / "trabalhos"
        pasta.mkdir(exist_ok=True)
        return pasta

    def listar_trabalhos(self):
        itens = []
        for arq in sorted(self._pasta_trabalhos().glob("*.json"),
                          key=lambda a: a.stat().st_mtime, reverse=True):
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            eps = dados.get("episodios", [])
            itens.append({"arquivo": arq.name, "nome": dados.get("nome", arq.stem),
                          "quando": dados.get("salvo_em", ""), "total": len(eps),
                          "faltam": sum(e.get("situacao") not in FINALIZADOS for e in eps),
                          "grupos": sorted({nucleo.nome_grupo(e) for e in eps})[:4]})
        return {"trabalhos": itens}

    def salvar_trabalho_como(self, nome):
        import re as _re
        import time as _time
        nome = (nome or "").strip()
        if not nome:
            return {"erro": "Dê um nome para o trabalho."}
        if not self.episodios:
            return {"erro": "A lista está vazia: não há o que salvar."}
        arquivo = self._pasta_trabalhos() / (_re.sub(r'[\\/:*?"<>|]+', "_", nome)[:80] + ".json")
        dados = {"nome": nome, "salvo_em": _time.strftime("%Y-%m-%d %H:%M"), "versao": VERSAO,
                 "serie": self.serie, "idioma": self.idioma, "episodios": self.episodios}
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True, "texto": f"Trabalho “{nome}” salvo."}

    def abrir_trabalho(self, arquivo):
        caminho = self._pasta_trabalhos() / arquivo
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"erro": "Não consegui abrir esse trabalho."}
        if isinstance(dados.get("serie"), dict):
            self.serie.update(dados["serie"])
        self.idioma = dados.get("idioma", self.idioma)
        self.episodios = [self._novo_episodio({k: v for k, v in e.items() if k not in ("id", "_antes")})
                          for e in dados.get("episodios", [])]
        self._limpar_provisorios()
        self._publicar()
        return {"ok": True, "texto": f"Trabalho “{dados.get('nome', arquivo)}” aberto."}

    def excluir_trabalho(self, arquivo):
        caminho = self._pasta_trabalhos() / arquivo
        if caminho.exists() and caminho.parent == self._pasta_trabalhos():
            caminho.unlink()
        return self.listar_trabalhos()

    # ========================================================== histórico
    def estatisticas(self):
        """Números do painel, calculados a partir do histórico de envios."""
        import time as _time
        hist = self._ler_historico_arquivo()
        envios = [h for h in hist if h.get("tipo", "envio") == "envio"]
        hoje = _time.strftime("%Y-%m-%d")
        semana = _time.strftime("%Y-%m-%d", _time.localtime(_time.time() - 7 * 86400))
        return {
            "enviados": len(envios),
            "series": len({h["codigo"] for h in envios}),
            "temporadas": len({(h["codigo"], h["temporada"]) for h in envios}),
            "hoje": sum(h["quando"][:10] == hoje for h in envios),
            "semana": sum(h["quando"][:10] >= semana for h in envios),
            "sinopses": sum("sinopse" in h.get("depois", {}) for h in envios),
            "titulos": sum("titulo" in h.get("depois", {}) for h in envios),
            "desfeitos": sum(h.get("tipo") == "desfazer" for h in hist),
        }

    # ======================================================= minhas séries
    def minhas_series(self):
        """Resumo do que já foi enviado, por série e temporada (pelo histórico)."""
        series = {}
        for h in self._ler_historico_arquivo():
            if h.get("tipo", "envio") != "envio":
                continue
            s = series.setdefault(str(h["codigo"]), {"codigo": str(h["codigo"]),
                                                     "nome": h.get("serie") or str(h["codigo"]),
                                                     "temporadas": {}, "ultimo": ""})
            t = s["temporadas"].setdefault(str(h["temporada"]), {"numeros": set(), "ultimo": ""})
            t["numeros"].add(h["numero"])
            t["ultimo"] = max(t["ultimo"], h["quando"])
            s["ultimo"] = max(s["ultimo"], h["quando"])
        lista = []
        for s in sorted(series.values(), key=lambda x: x["ultimo"], reverse=True):
            temps = [{"numero": n, "enviados": len([x for x in t["numeros"] if x]),
                      "ultimo": t["ultimo"]}
                     for n, t in sorted(s["temporadas"].items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)]
            lista.append({"codigo": s["codigo"], "nome": s["nome"], "ultimo": s["ultimo"],
                          "temporadas": temps})
        return {"series": lista, "tem_chave": bool(nucleo.tmdb_configurado())}

    def cobertura_tmdb(self, codigo):
        """Pela API: quantos episódios de cada temporada já têm título e sinopse no idioma."""
        api = nucleo.tmdb_configurado()
        if not api:
            return {"erro": "Para conferir no TMDB, cadastre a chave da API nas Configurações."}
        try:
            info = api.serie(codigo)
            idioma = self.idioma or "pt-BR"
            temps = []
            for t in info["temporadas"]:
                if not t["numero"]:
                    continue
                eps = api.temporada(codigo, t["numero"], idioma)
                temps.append({"numero": str(t["numero"]), "total": len(eps),
                              "titulos": sum(nucleo.ja_preenchido(e["titulo"]) for e in eps),
                              "sinopses": sum(bool(e["sinopse"].strip()) for e in eps)})
            return {"ok": True, "codigo": str(codigo), "idioma": idioma, "temporadas": temps}
        except Exception as erro:
            return {"erro": f"Não consegui consultar o TMDB: {erro}"}

    def conferir_mudancas(self, codigo):
        """Compara o que você enviou (Histórico) com o que o TMDB tem hoje, episódio
        por episódio, e lista o que alguém mudou ou apagou depois."""
        api = nucleo.tmdb_configurado()
        if not api:
            return {"erro": "Para conferir no TMDB, cadastre a chave da API nas Configurações."}
        ultimos = {}
        for h in self._ler_historico_arquivo():
            if str(h.get("codigo")) == str(codigo) and h.get("tipo", "envio") == "envio" \
                    and h.get("depois"):
                ultimos[(str(h["temporada"]), int(h["numero"]), h.get("idioma", "pt-BR"))] = h
        if not ultimos:
            return {"erro": "Nada enviado dessa série ainda."}

        def rotina():
            mudancas, total = [], len(ultimos)
            nome = next(iter(ultimos.values())).get("serie") or str(codigo)
            for n, ((temp, num, idioma), h) in enumerate(sorted(ultimos.items()), 1):
                if self._parar:
                    break
                self._avisar_tela("progresso", atual=n - 1, total=total,
                                  texto=f"Conferindo {nome} · T{temp} E{num} no TMDB...")
                # A página do episódio no idioma é atualizada na hora (a lista de
                # traduções e a da temporada ficam um tempo em cache no TMDB).
                try:
                    caminho = f"/tv/{codigo}/season/{temp}" + (f"/episode/{num}" if num else "")
                    t = api._get(caminho, language=idioma)
                except Exception as erro:
                    self._log(f"T{temp} E{num}: não consegui consultar ({erro}).")
                    continue
                titulo = (t.get("name") or "").strip()
                agora = {"titulo": titulo if nucleo.ja_preenchido(titulo) else "",
                         "sinopse": (t.get("overview") or "").strip()}
                for campo, enviado in h["depois"].items():
                    enviado = (enviado or "").strip()
                    if enviado and agora.get(campo, "") != enviado:
                        mudancas.append({"temporada": temp, "numero": num, "campo": campo,
                                         "enviado": enviado, "agora": agora.get(campo, ""),
                                         "quando": h.get("quando", "")})
            self._avisar_tela("progresso", atual=total, total=total,
                              texto=f"Conferência de {nome} terminada.")
            self._avisar_tela("mudancas", serie=nome, total=total, itens=mudancas)
        return {"ok": self._em_segundo_plano(rotina)}

    def abrir_serie(self, codigo, temporada):
        """Escolhe a série e a temporada no topo (para importar e continuar)."""
        def rotina():
            s = nucleo.info_serie(codigo, self.visivel)
            numeros = [str(t["numero"]) for t in s["temporadas"]]
            s["temporada"] = str(temporada) if str(temporada) in numeros else (numeros[0] if numeros else "1")
            self.serie = s
            self._publicar()
            self._avisar_tela("progresso", atual=1, total=1,
                              texto=f"{s['nome']} · temporada {s['temporada']} escolhida. Agora é só importar.")
        return {"ok": self._em_segundo_plano(rotina)}

    def ler_historico(self):
        return {"registros": list(reversed(self._ler_historico_arquivo()))[:1000]}

    def desfazer(self, ids):
        """Devolve ao TMDB o texto que havia antes dos envios escolhidos."""
        if not STORAGE.exists():
            return {"precisa_login": True}
        por_id = {r["id"]: r for r in self._ler_historico_arquivo()}
        itens = []
        for n, ident in enumerate(ids):
            r = por_id.get(ident)
            if not r or not r.get("antes"):
                continue
            itens.append({"id": f"desfazer-{n}", "codigo": r["codigo"], "temporada": r["temporada"],
                          "numero": r["numero"], "serie": r.get("serie", ""),
                          "titulo": r["antes"].get("titulo", ""),
                          "sinopse": r["antes"].get("sinopse", ""),
                          "campos": list(r["antes"].keys()), "forcar": True,
                          "_idioma": r.get("idioma", self.idioma)})
        if not itens:
            return {"erro": "Nada para desfazer nos itens escolhidos."}
        idiomas = {i["_idioma"] for i in itens}

        def rotina():
            feitos = falhas = 0
            for idioma in idiomas:
                lote = [i for i in itens if i["_idioma"] == idioma]
                r = nucleo.enviar_episodios(lote, idioma, self.visivel, True, True,
                                            self._aviso_nucleo, lambda: self._parar)
                feitos, falhas = feitos + r["ok"], falhas + r["falhas"]
            self._avisar_tela("aviso", texto=f"Desfazer concluído: {feitos} restaurados"
                                             f"{f', {falhas} com problema' if falhas else ''}.")
            self._avisar_tela("historico_mudou")
        return {"ok": self._em_segundo_plano(rotina), "total": len(itens)}

    def enviar(self, sub_titulo, sub_sinopse):
        itens, _ = self._para_enviar()
        if not itens:
            return {"erro": "Nenhum episódio marcado com título ou sinopse para enviar."}
        self._salvar_trabalho()

        def rotina():
            r = nucleo.enviar_episodios(itens, self.idioma, self.visivel, bool(sub_titulo),
                                        bool(sub_sinopse), self._aviso_nucleo,
                                        lambda: self._parar)
            if r["ok"]:
                self._avisar_tela("login", estado="conectado")
            self._avisar_tela("envio_fim", **r)
        return {"ok": self._em_segundo_plano(rotina)}
