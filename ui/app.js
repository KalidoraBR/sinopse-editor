/* Sinopse Editor — lógica da tela. Conversa com o Python por window.pywebview.api. */
(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ic = (nome, cls = '') => `<svg class="i ${cls}"><use href="#i-${nome}"/></svg>`;
  const chamar = (nome, ...args) => window.pywebview.api[nome](...args);

  const FINALIZADOS = ['Enviado', 'Já preenchido'];
  const S = {
    aba: 'traducao',
    E: { episodios: [], serie: {}, idioma: 'pt-BR', ocupado: false, visivel: false },
    filtro: 'pendentes', sel: null, login: 'verificando', temChave: false, limite: 350,
    sub: { t: false, s: false }, log: [],
  };

  // ================================================================ utilidades
  const grupoDe = (e) => `${e.codigo}|${e.temporada}`;
  const nomeGrupo = (e) => `${e.serie || (e.codigo ? 'Série ' + e.codigo : 'Série sem código')}${e.ano ? ' (' + e.ano + ')' : ''} · Temporada ${e.temporada || '?'}`;
  const grupos = (lista) => { const m = new Map(); lista.forEach((e) => { const g = grupoDe(e); if (!m.has(g)) m.set(g, []); m.get(g).push(e); }); return m; };
  const finalizado = (e) => FINALIZADOS.includes(e.situacao);
  const temTexto = (e) => (e.titulo || '').trim() || (e.sinopse || '').trim();
  const classeSelo = (s) => 's-' + (s === 'Já preenchido' ? 'Ja' : s.startsWith('Sem ') ? 'Sem' : s);
  const tituloAuto = (t) => /^(epis[oó]dio|episode|ep\.?)\s*\d+$/i.test((t || '').trim());
  const porId = (id) => S.E.episodios.find((e) => String(e.id) === String(id));
  const refPt = (e) => {
    const p = S.E.idioma === 'pt-PT' ? 'ref_ptpt' : 'ref_ptbr';
    return { titulo: e[p + '_titulo'] || '', sinopse: e[p + '_sinopse'] || '' };
  };
  const temRefPt = (e) => { const r = refPt(e); return !!(r.titulo || r.sinopse); };

  function visiveis() {
    const f = S.filtro;
    return S.E.episodios.filter((e) =>
      f === 'todos' ? true :
      f === 'pendentes' ? !finalizado(e) :
      f === 'marcados' ? e.enviar && !finalizado(e) :
      f === 'desmarcados' ? !e.enviar && !finalizado(e) :
      f === 'problema' ? e.situacao === 'Falhou' :
      finalizado(e));
  }

  function aviso(texto, ms = 4200) {
    const el = document.createElement('div');
    el.className = 'aviso';
    el.textContent = texto;
    $('#avisos').appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  // "faltam cerca de 20 s": mede o ritmo desde o início da tarefa atual.
  const ritmo = { total: 0, atual: 0, inicio: 0 };
  function tempoRestante(ev) {
    const agora = Date.now();
    if (ev.total !== ritmo.total || ev.atual < ritmo.atual || !ritmo.inicio) {
      Object.assign(ritmo, { total: ev.total, atual: ev.atual, inicio: agora, base: ev.atual });
      return '';
    }
    ritmo.atual = ev.atual;
    const feitos = ev.atual - ritmo.base, gasto = (agora - ritmo.inicio) / 1000;
    if (feitos < 2 || ev.atual >= ev.total || ev.total < 4) return '';
    const resta = Math.round(gasto / feitos * (ev.total - ev.atual));
    if (resta < 5) return ' · quase lá';
    return resta < 90 ? ` · faltam cerca de ${resta} s` : ` · faltam cerca de ${Math.round(resta / 60)} min`;
  }

  // Notificação animada no canto (tarefa concluída, envio terminado...).
  function notificar(titulo, texto, tipo = 'ok', ms = 6500) {
    const el = document.createElement('div');
    el.className = `notificacao ${tipo}`;
    el.setAttribute('role', 'status');
    el.innerHTML = `<span class="noti-icone">${ic(tipo === 'ok' ? 'check' : 'alerta')}</span>
      <div><b>${esc(titulo)}</b>${texto ? `<span>${esc(texto)}</span>` : ''}</div>
      <button class="noti-fechar" aria-label="Fechar aviso">${ic('fechar')}</button>
      <i class="noti-tempo" style="animation-duration:${ms}ms"></i>`;
    $('#notificacoes').appendChild(el);
    const tirar = () => { el.classList.add('saindo'); setTimeout(() => el.remove(), 220); };
    $('.noti-fechar', el).onclick = tirar;
    setTimeout(tirar, ms);
  }

  function registrar(texto) {
    const hora = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    S.log.push(`[${hora}] ${texto}`);
    if (S.log.length > 600) S.log.shift();
    const pre = $('#log');
    pre.textContent = S.log.join('\n');
    pre.scrollTop = pre.scrollHeight;
  }

  function resultado(r, sucesso) {
    if (!r) return;
    if (r.erro) aviso(r.erro, 5500);
    else if (r.texto) { aviso(r.texto); registrar(r.texto); }
    if (r.ok && sucesso) sucesso(r);
  }

  // ================================================================== janelas
  // "Sugerir link": busca a série no Fandom e preenche o campo com a escolha (opcional).
  document.addEventListener('click', async (ev) => {
    const b = ev.target.closest('[data-sugerir]');
    if (!b) return;
    const campo = document.getElementById(b.dataset.sugerir), lista = document.getElementById('sug-' + b.dataset.sugerir);
    const grupo = $('#comp-grupo') ? $('#comp-grupo').selectedOptions[0]?.textContent.split(' · ')[0].replace(/\s*\(\d{4}\)$/, '') : '';
    lista.innerHTML = '<span style="font-size:13px;color:var(--apagado)">Procurando no Fandom...</span>';
    b.disabled = true;
    const r = await chamar('sugerir_wiki', grupo || S.E.serie?.nome || '');
    b.disabled = false;
    if (r.erro) { lista.innerHTML = `<span class="erro-txt">${esc(r.erro)}</span>`; return; }
    if (!r.sugestoes.length) { lista.innerHTML = '<span style="font-size:13px;color:var(--apagado)">Nada encontrado. Cole o link manualmente.</span>'; return; }
    lista.innerHTML = r.sugestoes.map((s) => `<button class="sugestao" data-url="${esc(s.url)}"><span>${esc(s.titulo)}</span><small>${esc(s.wiki)}.fandom.com</small></button>`).join('');
    $$('.sugestao', lista).forEach((x) => x.onclick = () => { campo.value = x.dataset.url; campo.dispatchEvent(new Event('input')); lista.innerHTML = ''; });
  });

  function modal({ icone = 'camadas', alerta = false, titulo, texto = '', corpo = '', botoes = [], estreito = false, info = '' }) {
    const fundo = document.createElement('div');
    fundo.className = 'fundo-modal';
    fundo.innerHTML = `
      <div class="modal ${estreito ? 'estreito' : ''}" role="dialog" aria-modal="true" aria-labelledby="m-titulo">
        <div class="modal-cab">
          <div class="modal-icone ${alerta ? 'alerta' : ''}">${ic(icone)}</div>
          <div><h2 id="m-titulo">${esc(titulo)}</h2>${texto ? `<p>${texto}</p>` : ''}</div>
          <button class="fechar" aria-label="Fechar">${ic('fechar')}</button>
        </div>
        ${corpo ? `<div class="modal-corpo">${corpo}</div>` : ''}
        <div class="modal-rodape"><span class="info">${info}</span><div class="espaco"></div></div>
      </div>`;
    const fechar = () => {
      document.removeEventListener('keydown', tecla);
      if (fundo.classList.contains('saindo')) return;
      fundo.classList.add('saindo');
      setTimeout(() => fundo.remove(), document.body.classList.contains('sem-animacao') ? 0 : 160);
    };
    const tecla = (ev) => { if (ev.key === 'Escape') fechar(); };
    document.addEventListener('keydown', tecla);
    $('.fechar', fundo).onclick = fechar;
    fundo.addEventListener('mousedown', (ev) => { if (ev.target === fundo) fechar(); });
    const rodape = $('.modal-rodape', fundo);
    botoes.forEach((b) => {
      const el = document.createElement('button');
      el.className = b.cls || 'btn-sec';
      el.innerHTML = (b.icone ? ic(b.icone) : '') + esc(b.txt);
      el.onclick = async () => { const manter = b.acao ? await b.acao(fundo, el) : false; if (!manter) fechar(); };
      rodape.appendChild(el);
    });
    $('#modais').appendChild(fundo);
    setTimeout(() => ($('input, textarea, select', fundo) || $('.modal-rodape button:last-child', fundo))?.focus(), 30);
    return { fundo, fechar };
  }

  function confirmar(titulo, texto, txtOk = 'Continuar', alerta = false) {
    return new Promise((ok) => {
      modal({ titulo, texto, estreito: true, alerta, icone: alerta ? 'alerta' : 'camadas', botoes: [
        { txt: 'Cancelar', acao: () => ok(false) },
        { txt: txtOk, cls: 'btn-pri' + (alerta ? ' amarelo' : ''), acao: () => ok(true) },
      ] });
    });
  }

  async function podeSubstituirLista() {
    if (!S.E.episodios.length) return true;
    return confirmar('Substituir a lista?', 'Os episódios que estão na lista agora serão trocados pelos novos.', 'Substituir');
  }

  // ==================================================================== topo
  function renderTopo() {
    const eps = S.E.episodios;
    const g = grupos(eps);
    const serie = S.E.serie || {};
    const titulo = $('#titulo-serie'), sub = $('#subtitulo-serie'), poster = $('#poster');
    let img = '';
    if (g.size > 1) {
      const nomes = [...new Set(eps.map((e) => e.serie || 'Série ' + e.codigo))];
      titulo.textContent = `Lote · ${g.size} temporadas`;
      sub.textContent = nomes.slice(0, 3).join(', ') + (nomes.length > 3 ? ` e mais ${nomes.length - 3}` : '');
      img = eps.find((e) => e.poster)?.poster || '';
    } else if (serie.nome) {
      titulo.textContent = serie.nome;
      sub.textContent = serie.ano || '';
      img = serie.poster || '';
    } else if (eps.length) {
      titulo.textContent = eps[0].serie || 'Episódios importados';
      sub.textContent = eps[0].ano || '';
      img = eps[0].poster || '';
    } else {
      titulo.textContent = 'Nenhuma série escolhida';
      sub.textContent = '';
    }
    poster.innerHTML = img ? `<img src="${esc(img)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:7px">` : ic('imagem');

    const chips = [];
    if (serie.codigo) chips.push(`<span class="chip">TMDB ${esc(serie.codigo)}</span>`);
    const temps = (serie.temporadas || []).map((t) => String(t.numero));
    if (temps.length) {
      chips.push(`<label class="oculto-leitor" for="sel-temporada">Temporada</label>
        <select class="chip" id="sel-temporada">${temps.map((n) => `<option value="${n}" ${String(serie.temporada) === n ? 'selected' : ''}>${n === '0' ? 'Especiais' : 'Temporada ' + n}</option>`).join('')}</select>`);
    }
    chips.push(`<label class="oculto-leitor" for="sel-idioma">Idioma de destino</label>
      <select class="chip" id="sel-idioma">${['pt-BR', 'pt-PT'].map((i) => `<option value="${i}" ${S.E.idioma === i ? 'selected' : ''}>Destino: ${i}</option>`).join('')}</select>`);
    $('#chips').innerHTML = chips.join('');
    $('#sel-temporada')?.addEventListener('change', (ev) => { S.E.serie.temporada = ev.target.value; chamar('definir', 'temporada', ev.target.value); });
    $('#sel-idioma').addEventListener('change', (ev) => { S.E.idioma = ev.target.value; chamar('definir', 'idioma', ev.target.value); });

    const nav = $('#btn-navegador');
    nav.setAttribute('aria-pressed', String(S.E.visivel));
    nav.innerHTML = S.E.visivel ? `${ic('olho')}<span>Navegador visível</span>` : `${ic('olho-off')}<span>Navegador oculto</span>`;
  }

  function renderLogin() {
    const txt = $('#login-txt');
    const mapa = {
      verificando: ['Verificando...', '#93C5FD'], conectado: ['Conectado', '#5FD08A'],
      desconectado: ['Não conectado — entrar', '#FDA4AF'], expirado: ['Login expirado — entrar', '#FCD34D'],
      nao_verificado: ['Não verificado', '#FCD34D'],
    };
    const [t, c] = mapa[S.login] || mapa.verificando;
    txt.textContent = t;
    txt.style.color = c;
  }

  // =================================================================== lista
  function renderLista() {
    const eps = S.E.episodios;
    const vis = visiveis();
    const feitos = eps.filter(finalizado).length;
    const g = grupos(eps);
    $('#total').textContent = eps.length ? `${eps.length} episódios${g.size > 1 ? ` em ${g.size} temporadas` : ''}` : 'Nenhum episódio';
    const cont = {};
    eps.forEach((e) => { cont[e.situacao] = (cont[e.situacao] || 0) + 1; });
    $('#resumo').textContent = Object.entries(cont).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(' · ');
    $$('#filtros button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.f === S.filtro)));
    const comPt = eps.filter((e) => temRefPt(e) && !finalizado(e) && !['Traduzido', 'Editado'].includes(e.situacao)).length;
    const btnPt = $('#btn-pt-tvdb');
    btnPt.hidden = !comPt;
    $('span', btnPt).textContent = `Português do TVDB (${comPt})`;
    const incompletos = eps.filter((e) => e.situacao === 'Sem texto' || e.situacao === 'Sem sinopse').length;
    const comp = $('#btn-complementar');
    comp.hidden = !incompletos;
    $('span', comp).textContent = `Complementar (${incompletos})`;
    const falhas = eps.filter((e) => e.situacao === 'Falhou').length;
    const rep = $('#btn-repetir');
    rep.hidden = !falhas;
    $('span', rep).textContent = `Tentar de novo (${falhas})`;

    const rol = $('#rolagem');
    if (!eps.length) {
      rol.innerHTML = `<div class="vazio">
        <div class="icone-grande">${ic('lista', 'i-20')}</div>
        <h3>Sua lista de episódios está vazia</h3>
        <p>Busque uma série no topo e importe uma temporada, ou use o Lote para várias temporadas e séries de uma vez.</p>
        <div class="linha-flex" style="margin-top:8px">
          <button class="btn-sec" data-acao="tmdb">${ic('filme')} Importar do TMDB</button>
          <button class="btn-sec" data-acao="lote">${ic('camadas')} Abrir o lote</button>
        </div>
        <div class="inicio-recentes" id="inicio-recentes"></div></div>`;
      $('[data-acao="tmdb"]', rol).onclick = importarTmdb;
      $('[data-acao="lote"]', rol).onclick = abrirLote;
      preencherInicio();
    } else if (!vis.length) {
      const tudo = S.filtro === 'pendentes' && feitos > 0;
      if (tudo) {
        const enviados = eps.filter((e) => e.situacao === 'Enviado').length;
        const ja = eps.filter((e) => e.situacao === 'Já preenchido').length;
        const temporadas = grupos(eps).size;
        rol.innerHTML = `<div class="vazio conclusao">
          <div class="conclusao-icone">${ic('check')}</div>
          <h3>${temporadas > 1 ? 'Lote concluído!' : 'Temporada concluída!'}</h3>
          <p>${temporadas > 1 ? `${temporadas} temporadas` : esc(nomeGrupo(eps[0]))} ${temporadas > 1 ? 'estão' : 'está'} em português no TMDB.</p>
          <div class="conclusao-numeros">
            <div><b>${enviados}</b><span>enviados</span></div>
            <div><b>${ja}</b><span>já preenchidos</span></div>
            <div><b>${temporadas}</b><span>temporada${temporadas > 1 ? 's' : ''}</span></div>
          </div>
          <div class="linha-flex">
            <button class="btn-pri" data-acao="nova">${ic('mais')} Começar outra</button>
            <button class="btn-sec" data-acao="enviados">Ver enviados</button>
          </div></div>`;
        $('[data-acao="enviados"]', rol).onclick = () => { S.filtro = 'enviados'; renderLista(); };
        $('[data-acao="nova"]', rol).onclick = async () => {
          if (await confirmar('Começar outra?', 'A lista atual sai da tela (o que foi enviado continua no Histórico).', 'Começar')) chamar('limpar');
        };
      } else {
        rol.innerHTML = `<div class="vazio">
          <div class="icone-grande">${ic('lista', 'i-20')}</div>
          <h3>Nada por aqui</h3><p>Nenhum episódio neste filtro.</p></div>`;
      }
    } else {
      let html = '';
      for (const [, lista] of grupos(vis)) {
        const primeiro = lista[0];
        const todosDoGrupo = eps.filter((e) => grupoDe(e) === grupoDe(primeiro));
        const enviados = todosDoGrupo.filter(finalizado).length;
        if (g.size > 1 || primeiro.serie) {
          const pct = Math.round((enviados / todosDoGrupo.length) * 100);
          const marcGrupo = todosDoGrupo.filter((e) => !finalizado(e));
          const todosMarc = marcGrupo.length > 0 && marcGrupo.every((e) => e.enviar);
          const algunsMarc = !todosMarc && marcGrupo.some((e) => e.enviar);
          const fontes = [...new Set(todosDoGrupo.map((e) => e.fonte).filter(Boolean))];
          html += `<div class="grupo-cab">
            <label class="marca-grupo" title="Marcar ou desmarcar todos os episódios desta temporada"><input type="checkbox" data-grupo="${esc(grupoDe(primeiro))}"
              ${todosMarc ? 'checked' : ''} ${algunsMarc ? 'data-meio="1"' : ''} ${marcGrupo.length ? '' : 'disabled'}
              aria-label="Marcar todos de ${esc(nomeGrupo(primeiro))}"></label>
            ${primeiro.poster ? `<img class="poster p" src="${esc(primeiro.poster)}" alt="">` : `<div class="poster p" aria-hidden="true"></div>`}
            <div class="grupo-info">
              <div class="grupo-linha"><b>${esc(nomeGrupo(primeiro))}</b>${fontes.map((f) => `<span class="fonte-tag fonte-${esc(f.toLowerCase())}" title="Textos originais vindos de: ${esc(f)}">via ${esc(f)}</span>`).join('')}</div>
              <div class="grupo-linha"><div class="barrinha" aria-label="${pct}% enviado"><div style="width:${pct}%"></div></div>
                <span><b>${enviados} de ${todosDoGrupo.length}</b> enviados</span></div>
            </div>
            <button class="btn-mini tirar-grupo" data-tirar-grupo="${esc(grupoDe(primeiro))}" title="Tirar esta temporada da lista (nada muda no TMDB)" aria-label="Tirar ${esc(nomeGrupo(primeiro))} da lista">${ic('lixo')}</button></div>`;
        }
        lista.forEach((e) => { html += linhaHtml(e); });
      }
      rol.innerHTML = html;
      $$('input[data-meio]', rol).forEach((c) => { c.indeterminate = true; });
    }
    const marcaveis = vis.filter((e) => !finalizado(e));
    const mt = $('#marcar-todos');
    mt.checked = marcaveis.length > 0 && marcaveis.every((e) => e.enviar);
    mt.indeterminate = !mt.checked && marcaveis.some((e) => e.enviar);
    renderRodape();
  }

  function linhaHtml(e) {
    const tam = (e.sinopse || '').length;
    const outros = [...new Set([e.idioma_titulo, e.idioma_sinopse].filter((c) => c && !c.startsWith('en')).map((c) => c.split('-')[0].toUpperCase()))];
    let etiqueta = outros.length ? ` <span class="idi-tag" title="Original em ${esc(outros.join(', '))} (o TMDB não tinha em inglês)">${esc(outros.join('+'))}</span>` : '';
    if (e.sinopse_do_plot && !['Traduzido', 'Editado', 'Enviado', 'Já preenchido'].includes(e.situacao)) {
      etiqueta += ' <span class="idi-tag plot" title="A Wiki não tinha sinopse: veio o enredo completo (Plot). A IA vai resumir ao traduzir.">PLOT</span>';
    }
    const cls = tam > S.limite ? 'excesso' : tam > S.limite * 0.8 ? 'alerta' : '';
    return `<div class="ep ${S.sel === e.id ? 'sel' : ''} ${finalizado(e) ? 'feito' : ''}" data-id="${e.id}">
      <label onclick="event.stopPropagation()"><input type="checkbox" ${e.enviar ? 'checked' : ''} ${finalizado(e) ? 'disabled' : ''} aria-label="Enviar o episódio ${e.numero}"></label>
      <span class="cod">${e.tipo === 'serie' ? 'SÉRIE' : e.tipo === 'temporada' ? 'TEMP' : 'E' + String(e.numero).padStart(2, '0')}</span>
      <div class="txt"><b>${e.tipo === 'serie' ? 'Série: ' + (esc(e.titulo) || 'nome') : e.tipo === 'temporada' ? 'Sinopse da temporada' : (esc(e.titulo) || '<i style="color:#6E778C">sem título</i>')}${etiqueta}</b><span>${esc(e.sinopse) || '—'}</span></div>
      <span class="tam ${cls}"><span class="ind ${e.tipo === 'temporada' ? 'oculto' : (e.titulo || '').trim() ? 'tem' : 'falta'}" title="${(e.titulo || '').trim() ? 'Tem título' : 'Sem título'}">T</span><span class="ind ${tam ? 'tem' : 'falta'}" title="${tam ? 'Tem sinopse' : 'Sem sinopse'}">S</span>${tam}</span>
      <span class="selo ${classeSelo(e.situacao)}">${esc(e.situacao)}</span>
      <button class="tirar-ep" data-tirar="${e.id}" title="Tirar este episódio da lista" aria-label="Tirar o episódio ${e.numero} da lista">${ic('lixo')}</button></div>`;
  }

  function atualizarLinha(e) {
    const el = $(`.ep[data-id="${e.id}"]`);
    if (!el) return;
    const novo = document.createElement('div');
    novo.innerHTML = linhaHtml(e);
    el.replaceWith(novo.firstElementChild);
  }

  // ================================================================ inspetor
  let tempoEdicao = null;
  function renderInspetor() {
    const box = $('#inspetor');
    const e = porId(S.sel);
    if (!e) {
      box.innerHTML = `<div class="insp-vazio">Clique em um episódio da lista para ver o original, o que já existe no TMDB e editar a tradução.</div>`;
      return;
    }
    const tam = (e.sinopse || '').length;
    const cls = tam > S.limite ? 'excesso' : tam > S.limite * 0.8 ? 'alerta' : '';
    const atualT = tituloAuto(e.atual_titulo) ? '' : (e.atual_titulo || '');
    const atualS = e.atual_sinopse || '';
    let tmdbHoje;
    if (atualT || atualS) {
      tmdbHoje = `<div class="caixa-info"><span class="rot">NO TMDB HOJE (${esc(S.E.idioma.toUpperCase())}) <span class="etiqueta e-amarela">já preenchido</span></span>
        <b>${esc(atualT) || '<i>sem título</i>'}</b><span>${esc(atualS) || 'Sinopse vazia — será preenchida.'}</span></div>`;
    } else if (S.temChave && e.original_titulo) {
      tmdbHoje = `<div class="caixa-info"><span class="rot">NO TMDB HOJE (PT-BR) <span class="etiqueta e-verde">vazio</span></span><span>Nada em português ainda — será preenchido.</span></div>`;
    } else {
      tmdbHoje = `<div class="caixa-info"><span class="rot">NO TMDB HOJE</span><span>Coloque a chave da API em Configurações para ver aqui o que já existe no TMDB.</span></div>`;
    }
    box.innerHTML = `
      <div class="insp-cab" style="position:relative">
        <button class="btn-mini insp-fechar" id="insp-fechar" aria-label="Fechar painel" style="width:30px;padding:0;justify-content:center">${ic('fechar')}</button>
        ${e.serie ? `<div class="insp-serie" title="${esc(e.serie)}">${esc(e.serie)}${e.ano ? ' · ' + esc(e.ano) : ''}</div>` : ''}
        <h2>${e.tipo === 'serie' ? 'Página da série' : e.tipo === 'temporada' ? 'Sinopse da temporada' : (esc(e.titulo) || 'Sem título')}</h2>
        <div class="insp-meta">
          <span class="etq">Temporada ${esc(e.temporada || '?')}</span>
          ${e.tipo === 'serie' ? '<span class="etq">Nome e sinopse da série</span>' : e.tipo === 'temporada' ? '' : `<span class="etq">Episódio ${esc(e.numero)}</span>`}
          <span class="selo ${classeSelo(e.situacao)}">${esc(e.situacao)}</span>
        </div>
      </div>
      <div class="insp-abas" role="tablist" aria-label="Partes do episódio">
        <button role="tab" data-aba="traducao" aria-selected="${S.aba === 'traducao'}">Tradução</button>
        <button role="tab" data-aba="original" aria-selected="${S.aba === 'original'}">Original${e.original_titulo || e.original_sinopse ? '' : ' <span class="aba-ponto" title="Sem texto original"></span>'}</button>
        <button role="tab" data-aba="tmdb" aria-selected="${S.aba === 'tmdb'}">No TMDB${temRefPt(e) ? ' <span class="aba-ponto azul" title="Tem português do TVDB"></span>' : ''}</button>
      </div>
      <div class="insp-corpo">
        <div class="insp-painel" data-painel="traducao" ${S.aba === 'traducao' ? '' : 'hidden'}>
        <div class="campo" ${e.tipo === 'temporada' ? 'hidden' : ''}><label for="ed-titulo">Título traduzido</label>
          <input class="entrada" id="ed-titulo" type="text" value="${esc(e.titulo)}" style="font-weight:600"></div>
        <div class="campo"><div class="campo-cab"><label for="ed-sinopse">Sinopse traduzida</label><span class="contador ${cls}" id="contador">${tam} / ${S.limite}</span></div>
          <textarea class="entrada" id="ed-sinopse" rows="6">${esc(e.sinopse)}</textarea></div>
        ${e.original_sinopse ? `<div class="caixa-info compara"><span class="rot">ORIGINAL, PARA COMPARAR</span>
          <span>${marcarNomes(e.original_sinopse)}</span><span class="nomes-check" id="nomes-check"></span></div>` : ''}
        </div>
        <div class="insp-painel" data-painel="original" ${S.aba === 'original' ? '' : 'hidden'}>
        <div class="caixa-info tracejada ${e.original_titulo || e.original_sinopse ? '' : 'sem-original'}" id="caixa-original">
          <span class="rot">ORIGINAL${idiomaOriginal(e)}${e.sinopse_do_plot ? ' · ENREDO (PLOT) — A IA RESUME' : ''}${e.fonte_complemento ? ' (complementado ' + (e.fonte_complemento === 'você' ? 'por você' : 'pelo ' + esc(e.fonte_complemento)) + ')' : ''}
            <button class="btn-mini" id="ed-original" style="height:26px" title="Escrever ou corrigir o texto original (em inglês, espanhol...)">${ic('lapis')} ${e.original_titulo || e.original_sinopse ? 'Editar' : 'Escrever'}</button></span>
          ${e.original_titulo || e.original_sinopse
            ? `${e.tipo === 'temporada' ? '' : `<b>${esc(e.original_titulo) || '<i>sem título</i>'}</b>`}<span>${esc(e.original_sinopse) || '<i>sem sinopse</i>'}</span>`
            : '<span>Este episódio veio sem texto. Se você achar a sinopse (em inglês, espanhol ou outro idioma), escreva aqui: ela entra no próximo “Copiar para traduzir”.</span>'}
        </div>
        </div>
        <div class="insp-painel" data-painel="tmdb" ${S.aba === 'tmdb' ? '' : 'hidden'}>
        ${temRefPt(e) ? `<div class="caixa-info" style="border-color:#2C4A5A"><span class="rot">NO TVDB EM PORTUGUÊS (${esc(S.E.idioma.toUpperCase())}) <button class="btn-mini" id="usar-pt" style="height:26px">Usar este texto</button></span>
          ${refPt(e).titulo && e.tipo !== 'temporada' ? `<b>${esc(refPt(e).titulo)}</b>` : ''}<span>${esc(refPt(e).sinopse) || 'Sem sinopse em português.'}</span></div>` : ''}
        ${tmdbHoje}
        </div>
      </div>
      <div class="insp-rodape"><button id="ep-ant">← Anterior</button><button id="ep-prox">Próximo →</button>
        <button id="ep-remover" title="Tirar este episódio da lista" aria-label="Tirar este episódio da lista" style="flex:0 0 38px">${ic('lixo')}</button></div>`;
    const salvar = (campo, valor) => {
      e[campo] = valor;
      if (['Original', 'Traduzido', 'Enviado', 'Falhou', 'Já preenchido', 'Sem texto', 'Sem sinopse', 'Complementado'].includes(e.situacao)) e.situacao = 'Editado';
      const selo = $('.insp-meta .selo', box);
      selo.className = 'selo ' + classeSelo(e.situacao);
      selo.textContent = e.situacao;
      if (campo === 'titulo') $('.insp-cab h2', box).textContent = valor || 'Sem título';
      if (campo === 'sinopse') {
        const n = valor.length, c = $('#contador');
        c.textContent = `${n} / ${S.limite}`;
        c.className = 'contador ' + (n > S.limite ? 'excesso' : n > S.limite * 0.8 ? 'alerta' : '');
      }
      atualizarLinha(e);
      clearTimeout(tempoEdicao);
      tempoEdicao = setTimeout(() => chamar('editar', e.id, campo, valor), 350);
    };
    $('#ed-titulo').addEventListener('input', (ev) => salvar('titulo', ev.target.value));
    $$('.insp-abas [data-aba]', box).forEach((b) => b.onclick = () => {
      S.aba = b.dataset.aba;
      $$('.insp-abas [data-aba]', box).forEach((x) => x.setAttribute('aria-selected', String(x === b)));
      $$('.insp-painel', box).forEach((p) => { p.hidden = p.dataset.painel !== S.aba; });
    });
    conferirNomes(e);
    $('#ed-sinopse').addEventListener('input', () => conferirNomes(e));
    $('#ed-original').onclick = () => editarOriginal(e);
    $('#insp-fechar').onclick = () => box.classList.remove('aberto');
    $('#usar-pt')?.addEventListener('click', async () => resultado(await chamar('usar_portugues_tvdb', [e.id])));
    $('#ed-sinopse').addEventListener('input', (ev) => salvar('sinopse', ev.target.value));
    const lista = visiveis();
    const i = lista.findIndex((x) => x.id === e.id);
    $('#ep-ant').disabled = i <= 0;
    $('#ep-prox').disabled = i < 0 || i >= lista.length - 1;
    $('#ep-remover').onclick = async () => {
      if (!(await confirmar('Tirar da lista?', `O episódio ${e.numero} sai só da lista do programa (nada muda no TMDB).`, 'Tirar'))) return;
      const prox = lista[i + 1]?.id ?? lista[i - 1]?.id;
      S.sel = prox ?? null;
      resultado(await chamar('remover', [e.id]));
    };
    $('#ep-ant').onclick = () => selecionar(lista[i - 1]?.id);
    $('#ep-prox').onclick = () => selecionar(lista[i + 1]?.id);
  }

  // Nomes próprios: palavras com maiúscula no meio da frase (mesma regra da revisão de envio).
  const PALAVRAS_COMUNS = new Set(['The', 'A', 'An', 'And', 'But', 'When', 'While', 'After', 'Before', 'With', 'As', 'In', 'On', 'At', 'To', 'Of', 'For',
    'From', 'However', 'Meanwhile', 'Then', 'Now', 'His', 'Her', 'Their', 'Its', 'This', 'That', 'These', 'Those', 'He', 'She', 'They', 'It', 'We',
    'I', 'You', 'Can', 'Will', 'One', 'Two', 'Three', 'Episode', 'Part', 'Earth', 'Japan', 'Tokyo', 'Christmas', 'Is', 'Are', 'Was', 'Not', 'No', 'If']);
  function nomesProprios(texto) {
    const nomes = [];
    (texto || '').split(/(?<=[.!?])\s+/).forEach((frase) => {
      const palavras = frase.match(/[A-Za-zÀ-ÿ][\w'\-]*/g) || [];
      palavras.slice(1).forEach((p) => {
        const limpo = p.replace(/'s$/, '');
        if (/^[A-ZÀ-Þ]/.test(limpo) && limpo.length >= 3 && !PALAVRAS_COMUNS.has(limpo) && !nomes.includes(limpo)) nomes.push(limpo);
      });
    });
    return nomes;
  }
  function marcarNomes(texto) {
    const nomes = nomesProprios(texto);
    let html = esc(texto);
    const protege = (t) => t.replace(/[.*+?^$|()[\]{}\\]/g, '\\$&');
    nomes.forEach((n) => { html = html.replace(new RegExp('\\b' + protege(n) + '\\b', 'g'), '<mark class="nome">' + esc(n) + '</mark>'); });
    return html;
  }
  function conferirNomes(e) {
    const caixa = $('#nomes-check');
    if (!caixa) return;
    const trad = ($('#ed-sinopse')?.value || '').toLowerCase();
    const nomes = nomesProprios(e.original_sinopse);
    if (!nomes.length || !trad.trim() || trad === (e.original_sinopse || '').toLowerCase()) { caixa.textContent = ''; return; }
    const faltam = nomes.filter((n) => !trad.includes(n.toLowerCase()));
    caixa.className = 'nomes-check ' + (faltam.length ? 'falta' : 'ok');
    caixa.textContent = faltam.length ? `⚠ Sumiram da tradução: ${faltam.join(', ')}` : `✓ Nomes próprios mantidos: ${nomes.join(', ')}`;
  }

  function idiomaOriginal(e) {
    const c = [...new Set([e.idioma_titulo, e.idioma_sinopse].filter(Boolean))];
    if (!c.length || (c.length === 1 && c[0].startsWith('en'))) return '';
    return ' · ' + c.map((x) => esc(x.split('-')[0].toUpperCase())).join('+');
  }

  // Edição do texto ORIGINAL dentro do painel (para completar um episódio à mão).
  function editarOriginal(e) {
    const caixa = $('#caixa-original');
    const idiomaAtual = e.idioma_sinopse || e.idioma_titulo || 'en-US';
    const opcoes = [['en-US', 'Inglês'], ['es-ES', 'Espanhol'], ['fr-FR', 'Francês'], ['it-IT', 'Italiano'], ['de-DE', 'Alemão'], ['ja-JP', 'Japonês'], ['pt-PT', 'Português (Portugal)']];
    caixa.classList.remove('sem-original');
    caixa.innerHTML = `<span class="rot">EDITAR O ORIGINAL</span>
      <div class="campo" ${e.tipo === 'temporada' ? 'hidden' : ''}><label for="or-titulo">Título original</label>
        <input class="entrada" id="or-titulo" type="text" value="${esc(e.original_titulo || '')}"></div>
      <div class="campo"><label for="or-sinopse">Sinopse original</label>
        <textarea class="entrada" id="or-sinopse" rows="5">${esc(e.original_sinopse || '')}</textarea></div>
      <div class="campo"><label for="or-idioma">Idioma desse texto</label>
        <select class="entrada" id="or-idioma">${opcoes.map(([c, n]) => `<option value="${c}" ${idiomaAtual === c ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
      <div class="linha-flex"><button class="btn-pri" id="or-salvar" style="height:36px">${ic('check')} Salvar original</button>
        <button class="btn-sec" id="or-cancelar" style="height:36px">Cancelar</button></div>`;
    $('#or-sinopse').focus();
    $('#or-cancelar').onclick = () => renderInspetor();
    $('#or-salvar').onclick = async () => {
      const r = await chamar('editar_original', e.id, $('#or-titulo').value, $('#or-sinopse').value, $('#or-idioma').value);
      resultado(r);
    };
  }

  function selecionar(id) {
    if (id == null) return;
    const e = porId(id);
    S.sel = e ? e.id : id;
    $('#inspetor').classList.add('aberto');
    $$('.ep.sel').forEach((el) => el.classList.remove('sel'));
    const el = $(`.ep[data-id="${id}"]`);
    if (el) { el.classList.add('sel'); el.scrollIntoView({ block: 'nearest' }); }
    renderInspetor();
  }

  // ================================================================== rodapé
  function renderRodape() {
    const n = S.E.episodios.filter((e) => e.enviar && !finalizado(e) && temTexto(e)).length;
    const g = new Set(S.E.episodios.filter((e) => e.enviar && !finalizado(e) && temTexto(e)).map(grupoDe)).size;
    $('#txt-enviar').textContent = n ? `Enviar ${n} episódio${n > 1 ? 's' : ''}` : 'Enviar';
    $('#btn-enviar').disabled = S.E.ocupado || !n;
    if (!S.E.ocupado) {
      const feitos = S.E.episodios.filter(finalizado).length, total = S.E.episodios.length;
      $('#prog-seg').textContent = total ? `${feitos} de ${total} já enviados` : '';
      if (total && $('#prog-txt').dataset.fixo !== '1') {
        $('#prog-txt').textContent = n ? `Pronto para enviar · ${n} marcados${g > 1 ? ` em ${g} temporadas` : ''}` : 'Pronto.';
      }
      $('#trilha').classList.remove('indeterminado');
      $('#trilha-barra').style.width = total ? `${Math.round((feitos / total) * 100)}%` : '0';
    }
    $('#sub-titulo').setAttribute('aria-pressed', String(S.sub.t));
    $('#sub-titulo').textContent = S.sub.t ? 'Substituir títulos' : 'Manter títulos';
    $('#sub-sinopse').setAttribute('aria-pressed', String(S.sub.s));
    $('#sub-sinopse').textContent = S.sub.s ? 'Substituir sinopses' : 'Manter sinopses';
  }

  function definirOcupado(valor) {
    S.E.ocupado = valor;
    $$('.trava').forEach((b) => { b.disabled = valor; });
    $('#btn-parar').hidden = !valor;
    $('#btn-enviar').hidden = valor;
    if (!valor) { $('#prog-txt').dataset.fixo = '1'; setTimeout(() => { $('#prog-txt').dataset.fixo = ''; }, 6000); }
    renderRodape();
  }

  // Etapas no topo (opcional): mostram em que ponto do trabalho a lista está.
  function renderEtapas() {
    const caixa = $('#etapas');
    let mostrar = true;
    try { mostrar = localStorage.getItem('mostrarEtapas') !== '0'; } catch (_) {}
    caixa.hidden = !mostrar;
    if (!mostrar) return;
    const eps = S.E.episodios || [];
    const marcados = eps.filter((e) => e.enviar || e.situacao === 'Enviado' || e.situacao === 'Já preenchido');
    const fim = (e) => e.situacao === 'Enviado' || e.situacao === 'Já preenchido';
    const trad = (e) => fim(e) || ['Traduzido', 'Editado', 'Enviando', 'Falhou'].includes(e.situacao);
    const feitos = [
      eps.length > 0,
      marcados.length > 0 && marcados.every(trad),
      marcados.length > 0 && marcados.every(trad) && eps.some((e) => e.situacao === 'Editado' || fim(e)),
      marcados.length > 0 && marcados.every(fim)
    ];
    const atual = feitos.indexOf(false);
    const nomes = [['Importar', 'Traga os textos originais'], ['Traduzir', 'Copiar, traduzir fora e colar'],
      ['Revisar', 'Confira ao lado ou lado a lado'], ['Enviar', 'Mande para o TMDB']];
    caixa.innerHTML = nomes.map(([n, dica], i) => {
      const est = feitos[i] && (atual === -1 || i < atual) ? 'feito' : i === atual ? 'atual' : 'depois';
      return `<li class="etapa ${est}" ${est === 'atual' ? 'aria-current="step"' : ''} title="${dica}">
        <span class="bola">${est === 'feito' ? ic('check') : i + 1}</span><span>${n}</span></li>`;
    }).join('');
  }

  function renderTudo() {
    if (S.sel != null && !porId(S.sel)) S.sel = null;
    renderTopo(); renderEtapas(); renderLista(); renderInspetor(); renderRodape();
  }

  // ============================================================ eventos (Python)
  window.app = {
    evento(ev) {
      switch (ev.tipo) {
        case 'estado': S.E = ev.estado; renderTudo(); break;
        case 'episodio': {
          const e = porId(ev.episodio.id);
          if (!e) break;
          const antes = finalizado(e);
          Object.assign(e, ev.episodio);
          const sai = !antes && finalizado(e) && S.filtro === 'pendentes';
          if (sai) {
            const el = $(`.ep[data-id="${e.id}"]`);
            if (el) {
              atualizarLinha(e);
              const novo = $(`.ep[data-id="${e.id}"]`);
              novo.classList.remove('feito');
              novo.style.background = '#14281D';
              setTimeout(() => novo.classList.add('saindo'), 450);
              setTimeout(() => { if (S.sel === e.id) S.sel = null; renderLista(); renderInspetor(); }, 900);
            }
          } else {
            atualizarLinha(e);
            if (S.sel === e.id) renderInspetor();
          }
          renderRodape();
          break;
        }
        case 'progresso': {
          // Importações terminam com "1 de 1": vira uma notificação de tarefa concluída.
          if (ev.total === 1 && ev.atual === 1 && ev.texto && /importad|complementad|conferid|terminad/i.test(ev.texto)) {
            notificar('Tarefa concluída', ev.texto);
          }
          $('#prog-txt').textContent = ev.texto || '';
          const t = $('#trilha');
          if (!ev.total) { t.classList.add('indeterminado'); $('#prog-seg').textContent = ''; }
          else {
            t.classList.remove('indeterminado');
            $('#trilha-barra').style.width = `${Math.round((ev.atual / ev.total) * 100)}%`;
            $('#prog-seg').textContent = `${ev.atual} de ${ev.total}` + tempoRestante(ev);
          }
          break;
        }
        case 'log': registrar(ev.texto); break;
        case 'aviso': aviso(ev.texto, 5500); registrar(ev.texto); break;
        case 'prefixo': oferecerPrefixo(ev); break;
        case 'mudancas': mostrarMudancas(ev); break;
        case 'ocupado': definirOcupado(ev.valor); break;
        case 'login': S.login = ev.estado; renderLogin(); break;
        case 'pedir_login': pedirLogin('O TMDB não reconheceu seu login (ele pode ter expirado). Nada foi enviado a partir desse episódio.'); break;
        case 'historico_mudou':
          if (historicoAberto && document.body.contains(historicoAberto.fundo)) { historicoAberto.fechar(); abrirHistorico(); }
          break;
        case 'envio_fim': {
          const partes = [`${ev.ok} salvo(s) no TMDB`];
          if (ev.pulados) partes.push(`${ev.pulados} já preenchido(s)`);
          if (ev.falhas) partes.push(`${ev.falhas} com problema (use “Tentar de novo”)`);
          registrar('Envio concluído: ' + partes.join(', ') + '.');
          notificar(ev.falhas ? 'Envio terminado com avisos' : 'Envio concluído', partes.join(' · '), ev.falhas ? 'alerta' : 'ok', 9000);
          // Tira do painel o episódio que já foi enviado e some da lista de pendentes.
          // Recomeça limpo: volta para "Pendentes" e tira do painel o episódio antigo.
          S.filtro = 'pendentes';
          $$('#filtros button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.f === 'pendentes')));
          S.sel = null;
          $('#inspetor').classList.remove('aberto');
          renderTudo();
          break;
        }
      }
    },
  };

  // ================================================================== ações
  function pedirLogin(texto) {
    modal({ icone: 'chave', alerta: true, estreito: true, titulo: 'É preciso entrar no TMDB', texto: esc(texto),
      botoes: [{ txt: 'Agora não' }, { txt: 'Entrar no TMDB', cls: 'btn-pri', acao: () => { chamar('entrar'); } }] });
  }

  async function importarTmdb() {
    if (!S.E.serie?.codigo) { aviso('Escolha a série primeiro: busque pelo nome ou código no topo.'); $('#busca').focus(); return; }
    if (!(await podeSubstituirLista())) return;
    const cfg = await chamar('ler_config');
    if (!cfg.tem_chave || !cfg.analisar_idiomas) { resultado(await chamar('importar_tmdb')); return; }
    aviso('Conferindo em quais idiomas o TMDB tem essa temporada...');
    const r = await chamar('analisar_idiomas');
    if (r.sem_chave) { resultado(await chamar('importar_tmdb')); return; }
    if (r.erro) { resultado(r); return; }
    escolherIdiomas(r);
  }

  // Janela "Idiomas no TMDB": marca quais idiomas usar e em que ordem (o primeiro que
  // tiver o texto ganha). Mostra na hora quantos títulos e sinopses vão ficar completos.
  function escolherIdiomas(r) {
    const total = r.total;
    if (!r.idiomas.length) { aviso('O TMDB não tem textos dessa temporada em nenhum idioma.'); return; }
    const en = r.idiomas.find((i) => i.codigo.startsWith('en'));
    const completoEn = en && en.titulos.length === total && en.sinopses.length === total;
    const ordem = r.idiomas.map((i) => i.codigo);
    const marcados = new Set(completoEn ? [en.codigo] : r.idiomas.slice(0, 1).map((i) => i.codigo));
    // Sugestão: se o inglês não completa tudo, marca também os que preenchem o que falta.
    if (!completoEn) {
      const t = new Set(), s = new Set();
      r.idiomas.forEach((i) => {
        const novos = i.titulos.filter((n) => !t.has(n)).length + i.sinopses.filter((n) => !s.has(n)).length;
        if (marcados.has(i.codigo) || novos > 0) { marcados.add(i.codigo); i.titulos.forEach((n) => t.add(n)); i.sinopses.forEach((n) => s.add(n)); }
      });
    }
    const porCod = Object.fromEntries(r.idiomas.map((i) => [i.codigo, i]));
    const { fundo } = modal({ icone: 'globo', titulo: 'Idiomas disponíveis no TMDB',
      texto: `${esc(r.serie)} · temporada ${esc(r.temporada)} · ${total} episódios. Marque os idiomas que quer usar. A ordem vale: cada título e cada sinopse vem do primeiro idioma marcado que tiver o texto.`,
      corpo: `<div class="idiomas" id="idiomas"></div><div class="nota neutra" id="idi-resumo"></div>`,
      botoes: [{ txt: 'Só inglês', acao: async () => { resultado(await chamar('importar_tmdb')); } },
        { txt: 'Cancelar' },
        { txt: 'Importar', cls: 'btn-pri', icone: 'baixar', acao: async () => {
          const escolha = ordem.filter((c) => marcados.has(c));
          if (!escolha.length) { aviso('Marque pelo menos um idioma.'); return true; }
          resultado(await chamar('importar_tmdb', escolha));
        } }] });
    $('.modal-rodape .btn-sec', fundo).style.marginRight = 'auto';
    const desenhar = () => {
      const t = new Set(), s = new Set();
      let pos = 0;
      $('#idiomas', fundo).innerHTML = ordem.map((cod, idx) => {
        const i = porCod[cod], on = marcados.has(cod);
        let novosT = 0, novosS = 0;
        if (on) {
          pos += 1;
          i.titulos.forEach((n) => { if (!t.has(n)) { t.add(n); novosT += 1; } });
          i.sinopses.forEach((n) => { if (!s.has(n)) { s.add(n); novosS += 1; } });
        }
        const pctT = total ? Math.round(i.titulos.length / total * 100) : 0, pctS = total ? Math.round(i.sinopses.length / total * 100) : 0;
        return `<div class="idioma ${on ? 'on' : ''}">
          <label class="idi-nome"><input type="checkbox" data-cod="${esc(cod)}" ${on ? 'checked' : ''}>
            <span><b>${esc(i.nome)}</b> <small>${esc(cod)}${on ? ` · ${pos}º` : ''}</small></span></label>
          <span class="idi-barras" title="${i.titulos.length} títulos e ${i.sinopses.length} sinopses de ${total}">
            <span class="idi-barra"><i style="width:${pctT}%"></i></span><small>${i.titulos.length}/${total} títulos</small>
            <span class="idi-barra"><i style="width:${pctS}%"></i></span><small>${i.sinopses.length}/${total} sinopses</small></span>
          <span class="idi-ganho">${on && (novosT || novosS) ? `+${novosT} tít. · +${novosS} sin.` : ''}</span>
          <span class="idi-ordem">
            <button class="btn-grupo" data-sobe="${idx}" aria-label="Subir ${esc(i.nome)}" ${idx === 0 ? 'disabled' : ''}>↑</button>
            <button class="btn-grupo" data-desce="${idx}" aria-label="Descer ${esc(i.nome)}" ${idx === ordem.length - 1 ? 'disabled' : ''}>↓</button></span></div>`;
      }).join('');
      const faltamT = total - t.size, faltamS = total - s.size;
      $('#idi-resumo', fundo).innerHTML = `<b>Resultado:</b> ${t.size}/${total} títulos e ${s.size}/${total} sinopses.`
        + (faltamT || faltamS ? ` Ainda faltariam ${faltamT} título(s) e ${faltamS} sinopse(s): dá para usar o Complementar (Wiki/TVDB) depois.` : ' Temporada completa.')
        + ' Os textos que não estiverem em inglês vão com um aviso para a IA.';
      $$('[data-cod]', fundo).forEach((c) => c.onchange = () => { c.checked ? marcados.add(c.dataset.cod) : marcados.delete(c.dataset.cod); desenhar(); });
      $$('[data-sobe]', fundo).forEach((b) => b.onclick = () => { const k = Number(b.dataset.sobe); [ordem[k - 1], ordem[k]] = [ordem[k], ordem[k - 1]]; desenhar(); });
      $$('[data-desce]', fundo).forEach((b) => b.onclick = () => { const k = Number(b.dataset.desce); [ordem[k + 1], ordem[k]] = [ordem[k], ordem[k + 1]]; desenhar(); });
    };
    desenhar();
  }

  async function preencherLink(campo, tipo, codigo) {
    try {
      const r = await chamar('link_salvo', codigo || null);
      if (r[tipo] && !campo.value) { campo.value = r[tipo]; campo.title = 'Último link usado para esta série'; }
    } catch (_) {}
  }

  function importarWiki() {
    const { fundo } = modal({ icone: 'globo', estreito: true, titulo: 'Importar da Wiki', texto: 'Cole o link da página da série (ou da lista de episódios) na Wiki.',
      corpo: `<div class="campo"><label for="url-wiki">Link da página</label>
          <div class="linha-flex"><input class="entrada" id="url-wiki" type="url" placeholder="https://..." style="flex:1">
          <button class="btn-sec" data-sugerir="url-wiki">${ic('busca')} Sugerir link</button></div></div>
        <div class="sugestoes" id="sug-url-wiki"></div>
        <p style="font-size:13px;color:#8C94A8">Os episódios entram na temporada escolhida no topo${S.E.serie?.nome ? ` (${esc(S.E.serie.nome)}, temporada ${esc(S.E.serie.temporada)})` : ''}.</p>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Importar', cls: 'btn-pri', icone: 'baixar', acao: async (f) => {
        const url = $('#url-wiki', f).value.trim();
        if (!/^https?:\/\//i.test(url)) { aviso('O link precisa começar com http.'); return true; }
        if (!(await podeSubstituirLista())) return true;
        resultado(await chamar('importar_wiki', url));
      } }] });
    preencherLink($('#url-wiki', fundo), 'wiki');
  }

  function importarTvdb() {
    const temp = S.E.serie?.temporada || '1';
    const { fundo } = modal({ icone: 'banco', estreito: true, titulo: 'Importar do TVDB',
      texto: 'Cole o link da série no TVDB. O programa lê, com calma, o título e a sinopse em inglês de cada episódio (só leitura).',
      corpo: `<div class="campo"><label for="url-tvdb">Link da série no TVDB</label><input class="entrada" id="url-tvdb" type="url" placeholder="https://thetvdb.com/series/nome-da-serie"></div>
        <div class="campo"><label for="temp-tvdb">Temporada no TVDB</label><input class="entrada" id="temp-tvdb" type="text" value="${esc(temp)}" style="width:120px"></div>
        <div class="nota neutra">Leva cerca de 2 segundos por episódio, para não sobrecarregar o site. ${S.E.serie?.nome ? `Os episódios vão para <b>${esc(S.E.serie.nome)}</b> no envio ao TMDB.` : 'Escolha a série no topo para poder enviar depois.'} Confira se a numeração do TVDB é a mesma do TMDB.</div>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Importar', cls: 'btn-pri', icone: 'baixar', acao: async (f) => {
        const url = $('#url-tvdb', f).value.trim(), t = $('#temp-tvdb', f).value.trim();
        if (!/thetvdb\.com\/series\//i.test(url)) { aviso('Cole um link do TVDB, como https://thetvdb.com/series/nome-da-serie'); return true; }
        if (!/^\d+$/.test(t)) { aviso('A temporada precisa ser um número.'); return true; }
        if (!(await podeSubstituirLista())) return true;
        resultado(await chamar('importar_tvdb', url, t));
      } }] });
    preencherLink($('#url-tvdb', fundo), 'tvdb');
  }

  async function complementar() {
    const r = await chamar('faltando');
    if (!r.grupos.length) { aviso('Não há episódios sem texto para complementar.'); return; }
    const opcoes = r.grupos.map((g, i) => `<option value="${i}">${esc(g.nome)} — ${g.numeros.length} sem texto</option>`).join('');
    const { fundo } = modal({ icone: 'peca', titulo: 'Complementar episódios sem texto',
      texto: 'Cole o link de outro site (TVDB ou Wiki/Fandom). O programa busca só os episódios que estão faltando e preenche apenas o que não tem.',
      corpo: `<div class="campo"><label for="comp-grupo">Temporada a complementar</label><select class="entrada" id="comp-grupo">${opcoes}</select></div>
        <div class="campo"><label for="comp-link">Link da série no outro site</label>
          <div class="linha-flex"><input class="entrada" id="comp-link" type="url" placeholder="https://thetvdb.com/series/... ou https://....fandom.com/wiki/..." style="flex:1">
          <button class="btn-sec" data-sugerir="comp-link">${ic('busca')} Sugerir Wiki</button></div></div>
        <div class="sugestoes" id="sug-comp-link"></div>
        <div class="campo" id="comp-temp-campo"><label for="comp-temp">Temporada nesse site (TVDB)</label><input class="entrada" id="comp-temp" type="text" style="width:120px"></div>
        <div class="nota neutra" id="comp-eps"></div>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Complementar', cls: 'btn-pri', icone: 'peca', acao: async (f) => {
        const g = r.grupos[Number($('#comp-grupo', f).value)];
        const link = $('#comp-link', f).value.trim(), temp = $('#comp-temp', f).value.trim() || g.temporada;
        if (!/^https?:\/\//i.test(link)) { aviso('Cole um link completo (começando com http).'); return true; }
        resultado(await chamar('complementar', link, g.chave, temp));
      } }] });
    const atualizar = () => {
      const g = r.grupos[Number($('#comp-grupo', fundo).value)];
      $('#comp-temp', fundo).value = g.temporada;
      const campo = $('#comp-link', fundo);
      if (campo.dataset.auto === '1') { campo.value = ''; }
      chamar('link_salvo', g.chave.split('|')[0]).then((l) => {
        const v = l.tvdb || l.wiki;
        if (v && !campo.value) { campo.value = v; campo.dataset.auto = '1'; }
      }).catch(() => {});
      $('#comp-eps', fundo).innerHTML = `Episódios que serão procurados: <b>${g.numeros.join(', ')}</b>. Os que já têm texto não são mexidos.`;
      $('#comp-temp-campo', fundo).hidden = !/thetvdb\.com/i.test($('#comp-link', fundo).value) && $('#comp-link', fundo).value.trim() !== '';
    };
    $('#comp-grupo', fundo).addEventListener('change', atualizar);
    $('#comp-link', fundo).addEventListener('input', atualizar);
    atualizar();
  }

  function abrirLocalizar() {
    if (!S.E.episodios.length) { aviso('A lista está vazia.'); return; }
    const { fundo } = modal({ icone: 'busca', titulo: 'Localizar e substituir',
      texto: 'Troque um nome ou palavra em vários episódios de uma vez. Veja a prévia antes de confirmar.',
      corpo: `<div class="grade-2">
          <div class="campo"><label for="loc-busca">Procurar</label><input class="entrada" id="loc-busca" type="text" placeholder="Ex.: Masked Rider"></div>
          <div class="campo"><label for="loc-troca">Trocar por</label><input class="entrada" id="loc-troca" type="text" placeholder="Ex.: Cavaleiro Mascarado"></div></div>
        <div class="linha-flex" style="flex-wrap:wrap;gap:14px;font-size:13px;color:var(--texto-2)">
          <label><input type="checkbox" id="loc-t" checked> Títulos</label>
          <label><input type="checkbox" id="loc-s" checked> Sinopses</label>
          <label><input type="checkbox" id="loc-palavra" checked> Só palavra inteira</label>
          <label><input type="checkbox" id="loc-mai"> Diferenciar maiúsculas</label>
          <label><input type="checkbox" id="loc-marc"> Só nos marcados</label></div>
        <div id="loc-previa" style="display:flex;flex-direction:column;gap:6px"></div>`,
      botoes: [{ txt: 'Fechar' }, { txt: 'Substituir', cls: 'btn-pri', acao: async (f) => {
        const a = args(f);
        if (!a[0]) { aviso('Digite o que procurar.'); return true; }
        const r = await chamar('substituir', ...a);
        resultado(r);
        return !r.ok;
      } }] });
    const args = (f) => [$('#loc-busca', f).value, $('#loc-troca', f).value,
      [$('#loc-t', f).checked && 'titulo', $('#loc-s', f).checked && 'sinopse'].filter(Boolean),
      $('#loc-mai', f).checked, $('#loc-palavra', f).checked, $('#loc-marc', f).checked];
    const escRe = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    let tempo = null;
    const previa = () => {
      clearTimeout(tempo);
      tempo = setTimeout(async () => {
        const a = args(fundo), box = $('#loc-previa', fundo), info = $('.modal-rodape .info', fundo);
        if (!a[0]) { box.innerHTML = ''; info.textContent = ''; return; }
        const r = await chamar('localizar', ...a);
        info.textContent = r.total ? `${r.total} ocorrência(s) em ${r.episodios} episódio(s)` : 'Nada encontrado';
        const fonte = a[4] ? `(?<![\\p{L}\\d_])(${escRe(esc(a[0]))})(?![\\p{L}\\d_])` : `(${escRe(esc(a[0]))})`;
        const re = new RegExp(fonte, a[3] ? 'gu' : 'giu');
        const marcar = (txt) => esc(txt).replace(re, '<mark style="background:#3A2E12;color:#FCD34D">$1</mark>');
        box.innerHTML = r.itens.slice(0, 30).map((i) => `<div class="caixa-info"><span class="rot">${esc(i.serie ? i.serie + ' · ' : '')}T${esc(i.temporada)} E${esc(i.numero)} · ${i.campo === 'titulo' ? 'TÍTULO' : 'SINOPSE'}</span><span>${marcar(i.antes.length > 220 ? i.antes.slice(0, 220) + '…' : i.antes)}</span></div>`).join('')
          + (r.itens.length > 30 ? `<span style="font-size:12px;color:var(--apagado)">... e mais ${r.itens.length - 30}</span>` : '');
      }, 250);
    };
    $$('input', fundo).forEach((i) => i.addEventListener('input', previa));
  }

  function abrirNumeracao() {
    const g = grupos(S.E.episodios);
    if (!g.size) { aviso('A lista está vazia.'); return; }
    const opcoes = [...g.entries()].map(([chave, l]) => `<option value="${esc(chave)}">${esc(nomeGrupo(l[0]))} — episódios ${l[0].numero} a ${l[l.length - 1].numero}</option>`).join('');
    modal({ icone: 'hash', titulo: 'Ajustar numeração',
      texto: 'Use quando a numeração do site de origem não bate com a do TMDB (ex.: a Wiki contou um especial como episódio 1).',
      corpo: `<div class="campo"><label for="num-grupo">Temporada</label><select class="entrada" id="num-grupo">${opcoes}</select></div>
        <div class="grade-2">
          <div class="campo"><label for="num-desl">Somar ao número</label><input class="entrada" id="num-desl" type="number" value="-1" step="1"></div>
          <div class="campo"><label for="num-de">A partir do episódio</label><input class="entrada" id="num-de" type="number" value="1" min="0" step="1"></div></div>
        <div class="nota neutra">Ex.: “-1” a partir do episódio 2 faz o 2 virar 1, o 3 virar 2... Para tirar um episódio que sobrou, selecione-o na lista e use a lixeira no painel lateral.</div>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Aplicar', cls: 'btn-pri', acao: async (f) => {
        const r = await chamar('ajustar_numeracao', $('#num-grupo', f).value, $('#num-desl', f).value, $('#num-de', f).value);
        resultado(r);
        return !r.ok;
      } }] });
  }

  function oferecerPrefixo(ev) {
    registrar(`A Wiki usa o prefixo “${ev.modelo}” nos títulos de ${ev.serie || 'a série'}.`);
    modal({ icone: 'lapis', titulo: 'Prefixo encontrado na Wiki',
      texto: `A Wiki de ${esc(ev.serie || 'a série')} numera os títulos como <b>${esc(ev.modelo.replace('{n}', ev.dois ? '01' : '1'))}</b>, mas o TMDB não traz isso.`,
      corpo: `<div class="nota neutra">Exemplo: <b>${esc(ev.exemplo)}</b></div>
        <div class="nota neutra">Colocando agora, nos títulos originais, a IA traduz o prefixo junto, de acordo com o tema da série (como fez com “Scroll” → “Pergaminho”).</div>`,
      botoes: [{ txt: 'Agora não' }, { txt: 'Colocar prefixo', cls: 'btn-pri', acao: async () => {
        resultado(await chamar('prefixar_titulos', ev.chave, ev.modelo, ev.dois));
      } }] });
  }

  function abrirPrefixo() {
    const g = grupos(S.E.episodios);
    if (!g.size) { aviso('A lista está vazia.'); return; }
    const opcoes = [...g.entries()].map(([chave, l]) => `<option value="${esc(chave)}">${esc(nomeGrupo(l[0]))}</option>`).join('');
    const { fundo } = modal({ icone: 'lapis', titulo: 'Prefixo nos títulos',
      texto: 'Algumas séries numeram os episódios com um nome próprio (Quest 01, Space.1...), mas o TMDB nem sempre traz isso. Aqui você coloca o prefixo em todos os títulos da temporada de uma vez.',
      corpo: `<div class="campo"><label for="pre-grupo">Temporada</label><select class="entrada" id="pre-grupo">${opcoes}</select></div>
        <div class="campo"><label for="pre-modelo">Prefixo ({n} = número do episódio)</label><input class="entrada" id="pre-modelo" type="text" value="Missão {n}:"></div>
        <label class="linha-flex" style="font-size:13px"><input type="checkbox" id="pre-dois" checked> Número com dois dígitos (01, 02...)</label>
        <button class="btn-sec" id="pre-wiki" style="align-self:flex-start">${ic('busca')} Descobrir pela Wiki</button>
        <div class="nota neutra" id="pre-previa"></div>
        <div class="nota neutra">Títulos que já começam com esse prefixo não são mexidos. Para desfazer, use Localizar e substituir.</div>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Aplicar', cls: 'btn-pri', acao: async (f) => {
        const r = await chamar('prefixar_titulos', $('#pre-grupo', f).value, $('#pre-modelo', f).value, $('#pre-dois', f).checked);
        resultado(r);
        return !r.ok;
      } }] });
    const previa = () => {
      const l = g.get($('#pre-grupo', fundo).value) || [];
      const e = l.find((x) => x.tipo !== 'temporada' && (x.titulo || '').trim());
      let m = $('#pre-modelo', fundo).value.trim();
      if (m && !m.includes('{n}')) m += ' {n}:';
      const n = e ? (($('#pre-dois', fundo).checked) ? String(e.numero).padStart(2, '0') : String(e.numero)) : '1';
      $('#pre-previa', fundo).textContent = e && m ? 'Exemplo: ' + m.replace('{n}', n) + ' ' + e.titulo.trim() : 'Exemplo: —';
    };
    $$('input, select', fundo).forEach((i) => { i.addEventListener('input', previa); i.addEventListener('change', previa); });
    previa();
    $('#pre-wiki', fundo).onclick = async () => {
      const chave = $('#pre-grupo', fundo).value;
      $('.modal-rodape button', fundo)?.click();
      aviso('Procurando o prefixo na Wiki salva da série...');
      resultado(await chamar('descobrir_prefixo', chave));
    };
  }

  function abrirLote() {
    const linhaLote = (codigo = '', temporadas = 'todas', wiki = '') => `
      <div class="lote-linha">
        <div class="lote-serie"><div class="poster m" aria-hidden="true"></div><div><b>${codigo ? 'Buscando...' : 'Nova série'}</b><small>Digite o código do TMDB</small></div></div>
        <input class="entrada l-cod" type="text" value="${esc(codigo)}" placeholder="Ex: 1399" aria-label="Código TMDB">
        <input class="entrada l-temp" type="text" value="${esc(temporadas)}" placeholder="todas ou 1-3, 5" aria-label="Temporadas">
        <input class="entrada l-wiki" type="text" value="${esc(wiki)}" placeholder="Opcional: Wiki ou TVDB" aria-label="Link da Wiki ou do TVDB">
        <button class="btn-icone l-rem" style="width:36px;height:36px;border:0" aria-label="Remover linha">${ic('lixo')}</button>
      </div>`;
    const { fundo } = modal({ icone: 'camadas', titulo: 'Importar em lote',
      texto: 'Uma linha por série. Em temporadas, use “todas” ou algo como “1-3, 5”. O link é opcional: Wiki (uma temporada por linha) ou TVDB (aceita várias temporadas). Sem link, os textos vêm do TMDB.',
      corpo: `<div class="lote-cols"><span>SÉRIE</span><span>CÓDIGO</span><span>TEMPORADAS</span><span>LINK (WIKI OU TVDB)</span><span></span></div>
        <div id="lote-linhas" style="display:flex;flex-direction:column;gap:8px">${linhaLote(S.E.serie?.codigo || '')}</div>
        <button class="btn-tracejado" id="lote-mais">${ic('mais')}Adicionar série</button>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Importar tudo', cls: 'btn-pri', icone: 'baixar', acao: async (f) => {
        const itens = $$('.lote-linha', f).map((l) => ({ codigo: $('.l-cod', l).value.trim(), temporadas: $('.l-temp', l).value.trim(), wiki: $('.l-wiki', l).value.trim() }))
          .filter((i) => i.codigo || i.wiki);
        if (!itens.length) { aviso('Adicione pelo menos uma série.'); return true; }
        const c = await chamar('conferir_lote', itens);
        if (c.erro) { aviso(c.erro); return true; }
        if (!(await podeSubstituirLista())) return true;
        resultado(await chamar('importar_lote', itens));
      } }] });
    const caixa = $('#lote-linhas', fundo);
    const ligar = (l) => {
      $('.l-rem', l).onclick = () => { l.remove(); contar(); };
      const cod = $('.l-cod', l);
      const procurar = async () => {
        const v = cod.value.trim();
        const nome = $('.lote-serie b', l), info = $('.lote-serie small', l), pst = $('.poster', l);
        if (!/^\d+$/.test(v)) { nome.textContent = v ? 'Código inválido' : 'Nova série'; info.textContent = 'Digite o código do TMDB'; info.className = v ? 'erro' : ''; return; }
        nome.textContent = 'Buscando...';
        const r = await chamar('buscar_series', v);
        const s = r.resultados?.[0];
        if (!s) { nome.textContent = 'Não encontrada'; info.textContent = r.erro || 'Confira o código'; info.className = 'erro'; return; }
        nome.textContent = `${s.nome}${s.ano ? ' (' + s.ano + ')' : ''}`;
        info.textContent = 'Encontrada'; info.className = 'ok';
        pst.outerHTML = s.poster ? `<img class="poster m" src="${esc(s.poster)}" alt="">` : '<div class="poster m" aria-hidden="true"></div>';
      };
      cod.addEventListener('change', procurar);
      $$('input', l).forEach((i) => i.addEventListener('input', contar));
      if (cod.value) procurar();
    };
    const contar = () => {
      const n = $$('.lote-linha', fundo).filter((l) => $('.l-cod', l).value.trim()).length;
      $('.modal-rodape .info', fundo).textContent = n ? `${n} série${n > 1 ? 's' : ''} no lote` : '';
    };
    $$('.lote-linha', caixa).forEach(ligar);
    $('#lote-mais', fundo).onclick = () => { caixa.insertAdjacentHTML('beforeend', linhaLote()); ligar(caixa.lastElementChild); $('.l-cod', caixa.lastElementChild).focus(); contar(); };
    contar();
  }

  async function abrirPlanilha() {
    if (!(await podeSubstituirLista())) return;
    resultado(await chamar('abrir_planilha'));
  }

  async function abrirConfig() {
    const c = await chamar('ler_config');
    const { fundo } = modal({ icone: 'config', titulo: 'Configurações',
      corpo: `
        <div class="campo"><label for="cfg-chave" style="font-size:14px;color:#E9ECF2">Chave da API do TMDB</label>
          <p style="font-size:13px;color:#8C94A8">Com ela, pôsteres, nomes, temporadas e episódios vêm direto do banco de dados do TMDB, e dá para buscar séries pelo nome. É gratuita.</p>
          <div class="linha-flex"><input class="entrada" id="cfg-chave" type="password" style="flex:1;font-family:var(--mono)" placeholder="${c.tem_chave ? 'Chave salva (termina em ' + esc(c.chave_final) + ') — cole outra para trocar' : 'Cole aqui a chave da API ou o token de leitura'}">
          <button class="btn-sec" id="cfg-testar">${ic('check')} Testar</button></div>
          <span id="cfg-resultado" class="${c.tem_chave ? 'ok-txt' : ''}">${c.tem_chave ? 'Chave salva.' : ''}</span>
          <a href="#" id="cfg-ajuda" style="font-size:13px">Como criar a chave gratuita →</a>
        </div>
        <div class="grade-2">
          <div class="campo"><label for="cfg-idioma">Idioma de destino padrão</label>
            <select class="entrada" id="cfg-idioma">${['pt-BR', 'pt-PT'].map((i) => `<option value="${i}" ${c.idioma === i ? 'selected' : ''}>${i === 'pt-BR' ? 'Português (Brasil) — pt-BR' : 'Português (Portugal) — pt-PT'}</option>`).join('')}</select></div>
          <div class="campo"><label for="cfg-limite">Tamanho máximo da sinopse</label>
            <select class="entrada" id="cfg-limite">${[250, 350, 500].map((n) => `<option value="${n}" ${Number(c.limite) === n ? 'selected' : ''}>${n} caracteres${n === 350 ? ' (cerca de 3 linhas)' : ''}</option>`).join('')}</select></div>
        </div>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-temporada" ${c.sinopse_temporada ? 'checked' : ''} style="margin-top:2px">
          <span><b>Importar também a sinopse da temporada</b> (opcional, precisa da chave da API).<br>
          Aparece como o primeiro item da lista (“TEMP”) e segue o mesmo caminho: traduzir, conferir e enviar. Desmarque o item se não quiser enviá-lo.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-etapas" ${(() => { try { return localStorage.getItem('mostrarEtapas') !== '0'; } catch (_) { return true; } })() ? 'checked' : ''} style="margin-top:2px">
          <span><b>Mostrar as etapas no topo</b><br>Importar → Traduzir → Revisar → Enviar, marcando o que já foi feito.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-animacoes" ${document.body.classList.contains('sem-animacao') ? '' : 'checked'} style="margin-top:2px">
          <span><b>Animações</b><br>Abertura do programa, janelas que surgem e somem, e avisos animados de tarefa concluída.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-claro" ${document.body.classList.contains('claro') ? 'checked' : ''} style="margin-top:2px">
          <span><b>Tema claro</b><br>Fundo branco em vez do escuro. Muda na hora, e o programa lembra da escolha.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-serie" ${c.pagina_serie ? 'checked' : ''} style="margin-top:2px">
          <span><b>Mostrar a página da série no topo da temporada</b> (precisa da chave da API).<br>
          O item “SÉRIE” (nome e sinopse da série) e a sinopse da temporada aparecem antes do E01. Vêm marcados sozinhos só quando a série ainda não tem português no TMDB (sem isso o TMDB não deixa editar os episódios); nos outros casos, marque se quiser traduzir.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-idiomas" ${c.analisar_idiomas ? 'checked' : ''} style="margin-top:2px">
          <span><b>Ver os idiomas disponíveis ao importar do TMDB</b> (precisa da chave da API).<br>
          Mostra em quais idiomas a temporada tem texto e deixa completar o que falta em inglês com outros (ex.: espanhol). Desligado, importa só em inglês.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-prefixo" ${c.conferir_prefixo ? 'checked' : ''} style="margin-top:2px">
          <span><b>Conferir prefixo dos títulos na Wiki</b> (ex.: “Quest 01:”).<br>
          Ao importar do TMDB, se a série já tem um link da Wiki salvo e a Wiki usa prefixo que o TMDB não traz, o programa oferece colocar.</span></label>
        <label class="nota neutra" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" id="cfg-revisar" ${c.revisar_envio ? 'checked' : ''} style="margin-top:2px">
          <span><b>Revisar a tradução antes de enviar</b>.<br>
          Na janela de envio, aponta títulos não traduzidos, sinopses longas, número do prefixo errado e nomes próprios que sumiram.</span></label>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Salvar', cls: 'btn-pri', acao: async (f) => {
        const chave = $('#cfg-chave', f).value.trim();
        if (chave) {
          const t = await chamar('testar_chave', chave);
          if (!t.ok) { $('#cfg-resultado', f).textContent = 'Chave não aceita: ' + t.erro; $('#cfg-resultado', f).className = 'erro-txt'; return true; }
        }
        const r = await chamar('salvar_config', chave || null, $('#cfg-idioma', f).value, $('#cfg-limite', f).value, $('#cfg-temporada', f).checked, $('#cfg-prefixo', f).checked, $('#cfg-revisar', f).checked, $('#cfg-idiomas', f).checked, $('#cfg-serie', f).checked);
        S.temChave = r.tem_chave; S.limite = Number(r.limite); S.E.idioma = r.idioma;
        aplicarTema($('#cfg-claro', f).checked);
        aplicarAnimacoes($('#cfg-animacoes', f).checked);
        try { localStorage.setItem('mostrarEtapas', $('#cfg-etapas', f).checked ? '1' : '0'); } catch (_) {}
        aviso('Configurações salvas.');
        renderTudo();
      } }] });
    $('#cfg-testar', fundo).onclick = async () => {
      const chave = $('#cfg-chave', fundo).value.trim(), out = $('#cfg-resultado', fundo);
      if (!chave) { out.textContent = 'Cole a chave para testar.'; out.className = 'erro-txt'; return; }
      out.textContent = 'Testando...'; out.className = '';
      const t = await chamar('testar_chave', chave);
      out.textContent = t.ok ? 'Chave válida!' : 'Chave não aceita: ' + t.erro;
      out.className = t.ok ? 'ok-txt' : 'erro-txt';
    };
    $('#cfg-ajuda', fundo).onclick = (ev) => {
      ev.preventDefault();
      modal({ icone: 'chave', estreito: true, titulo: 'Como criar a chave da API',
        corpo: `<div class="passos" style="grid-template-columns:1fr">
          <div class="passo"><b><span class="num">1</span>Entre no TMDB</b><span>Abra themoviedb.org e entre com a sua conta.</span></div>
          <div class="passo"><b><span class="num">2</span>Vá em Configurações → API</b><span>Clique no seu avatar → Configurações → API (ou acesse themoviedb.org/settings/api).</span></div>
          <div class="passo"><b><span class="num">3</span>Peça uma chave</b><span>Escolha “Desenvolvedor”, aceite os termos e preencha o formulário (uso pessoal).</span></div>
          <div class="passo"><b><span class="num">4</span>Copie e cole aqui</b><span>Copie a “Chave da API” (ou o “Token de leitura da API”) e cole em Configurações.</span></div></div>`,
        botoes: [{ txt: 'Entendi', cls: 'btn-pri' }] });
    };
  }

  function aplicarAnimacoes(ligadas) {
    document.body.classList.toggle('sem-animacao', !ligadas);
    try { localStorage.setItem('animacoes', ligadas ? '1' : '0'); } catch (_) {}
  }

  function aplicarTema(claro) {
    document.body.classList.toggle('claro', !!claro);
    try { window.pywebview?.api?.tema_janela?.(claro ? 'claro' : 'escuro'); } catch (_) {}
    try { localStorage.setItem('temaClaro', claro ? '1' : '0'); } catch (_) {}
  }

  function abrirLadoALado() {
    const lista = S.E.episodios.filter((e) => e.situacao !== 'Enviado' && e.situacao !== 'Já preenchido');
    if (!lista.length) { aviso('Não há episódios para comparar.'); return; }
    let anterior = null;
    const linhas = lista.map((e) => {
      const g = `${e.codigo}|${e.temporada}`;
      const cab = g !== anterior ? `<div class="lado-grupo">${esc(nomeGrupo(e))}</div>` : '';
      anterior = g;
      const cod = e.tipo === 'serie' ? 'SÉRIE' : e.tipo === 'temporada' ? 'TEMP' : 'E' + String(e.numero).padStart(2, '0');
      return `${cab}<div class="lado-linha" data-id="${esc(e.id)}">
        <span class="cod">${cod}</span>
        <div class="lado-orig"><b>${esc(e.original_titulo || '') || '<i>sem título</i>'}</b><span>${esc(e.original_sinopse || '') || '—'}</span></div>
        <div class="lado-trad"><input class="entrada" data-campo="titulo" value="${esc(e.titulo || '')}" aria-label="Título traduzido ${cod}">
          <textarea class="entrada" data-campo="sinopse" rows="3" aria-label="Sinopse traduzida ${cod}">${esc(e.sinopse || '')}</textarea>
          <small class="lado-tam"></small></div></div>`;
    }).join('');
    const { fundo } = modal({ icone: 'tabela', titulo: 'Comparar lado a lado',
      texto: 'Original à esquerda, tradução à direita. Pode corrigir aqui mesmo: cada mudança é guardada na hora. Episódios já enviados não aparecem.',
      corpo: `<div class="lado-cols"><span></span><span>ORIGINAL</span><span>TRADUÇÃO</span></div><div class="lado">${linhas}</div>`,
      botoes: [{ txt: 'Fechar', cls: 'btn-pri' }] });
    $('.modal', fundo).classList.add('largo');
    const tam = (linha) => {
      const n = $('textarea', linha).value.length, el = $('.lado-tam', linha);
      el.textContent = `${n} caracteres`; el.className = 'lado-tam ' + (n > S.limite ? 'excesso' : n > S.limite * 0.8 ? 'alerta' : '');
    };
    $$('.lado-linha', fundo).forEach((linha) => {
      tam(linha);
      $$('[data-campo]', linha).forEach((c) => {
        let t = null;
        c.addEventListener('input', () => {
          if (c.dataset.campo === 'sinopse') tam(linha);
          clearTimeout(t);
          t = setTimeout(async () => {
            const e = await chamar('editar', linha.dataset.id, c.dataset.campo, c.value);
            if (e) { const i = S.E.episodios.findIndex((x) => x.id === e.id); if (i >= 0) S.E.episodios[i] = e; atualizarLinha(e); }
          }, 400);
        });
      });
    });
    // Ao fechar, redesenha a lista e o painel com as correções feitas aqui.
    $$('.modal-rodape button, .fechar', fundo).forEach((b) => b.addEventListener('click', () => renderTudo()));
  }

  // Tela inicial: cartões das últimas séries enviadas, para continuar com um clique.
  async function preencherInicio() {
    let r;
    try { r = await chamar('minhas_series'); } catch (_) { return; }
    const caixa = $('#inicio-recentes');
    const lista = (r.series || []).slice(0, 4);
    if (!caixa || !lista.length) return;
    caixa.innerHTML = `<span class="recentes-rot">CONTINUAR DE ONDE PAROU</span><div class="inicio-cartoes">` + lista.map((s) => {
      const t = s.temporadas[s.temporadas.length - 1];
      return `<button class="inicio-cartao" data-codigo="${esc(s.codigo)}" data-temp="${esc(t.numero)}">
        <span class="inicio-poster" aria-hidden="true">${ic('filme')}</span>
        <span class="inicio-txt"><b>${esc(s.nome)}</b><small>Temporada ${esc(t.numero)} · ${t.enviados} enviados</small></span></button>`;
    }).join('') + '</div>';
    $$('.inicio-cartao', caixa).forEach((b) => b.onclick = async () => resultado(await chamar('abrir_serie', b.dataset.codigo, b.dataset.temp)));
  }

  async function renderRecentes() {
    const caixa = $('#recentes');
    if (!caixa || !document.body.classList.contains('lateral-aberta')) return;
    let r;
    try { r = await chamar('minhas_series'); } catch (_) { return; }
    const lista = (r.series || []).slice(0, 4);
    caixa.innerHTML = lista.length ? `<span class="recentes-rot">CONTINUAR</span>` + lista.map((s) => {
      const t = s.temporadas[s.temporadas.length - 1];
      return `<button class="recente" data-codigo="${esc(s.codigo)}" data-temp="${esc(t.numero)}" title="Escolher ${esc(s.nome)}, temporada ${esc(t.numero)}">
        <b>${esc(s.nome)}</b><small>T${esc(t.numero)} · ${t.enviados} enviados</small></button>`;
    }).join('') : '';
    $$('.recente', caixa).forEach((b) => b.onclick = async () => {
      if (!(await podeSubstituirLista())) return;
      resultado(await chamar('abrir_serie', b.dataset.codigo, b.dataset.temp));
    });
  }

  function mostrarMudancas(ev) {
    const n = ev.itens.length;
    registrar(n ? `${ev.serie}: ${n} mudança(s) no TMDB depois do seu envio.` : `${ev.serie}: tudo igual ao que você enviou.`);
    modal({ icone: n ? 'alerta' : 'check', alerta: !!n, titulo: n ? `${n} mudança(s) em ${ev.serie}` : 'Tudo certo',
      texto: n ? 'Depois do seu envio, alguém mudou ou apagou estes textos no TMDB. Nada foi alterado: é só para você saber.'
        : `Os ${ev.total} episódios enviados de ${esc(ev.serie)} estão no TMDB do jeito que você mandou.`,
      corpo: n ? `<div class="series-lista">${ev.itens.map((m) => `<div class="caixa-info">
          <span class="rot">T${esc(m.temporada)} ${m.numero ? 'E' + String(m.numero).padStart(2, '0') : 'TEMPORADA'} · ${m.campo === 'titulo' ? 'TÍTULO' : 'SINOPSE'}</span>
          <span><b>Você enviou:</b> ${esc(m.enviado)}</span>
          <span><b>No TMDB hoje:</b> ${m.agora ? esc(m.agora) : '<i>(apagado)</i>'}</span></div>`).join('')}</div>` : '',
      botoes: [{ txt: 'Fechar', cls: 'btn-pri' }] });
  }

  async function abrirMinhasSeries() {
    const r = await chamar('minhas_series');
    const data = (q) => q ? q.slice(8, 10) + '/' + q.slice(5, 7) + '/' + q.slice(0, 4) : '';
    const cartao = (s) => `<div class="serie-cartao" data-codigo="${esc(s.codigo)}">
        <div class="serie-topo"><div><b>${esc(s.nome)}</b><small>Último envio: ${data(s.ultimo)}</small></div>
          ${r.tem_chave ? `<div class="linha-flex"><button class="btn-sec btn-mudancas" title="Ver se alguém mudou ou apagou o que você enviou">${ic('repetir')} Conferir mudanças</button>
            <button class="btn-sec btn-cobertura">${ic('globo')} Conferir no TMDB</button></div>` : ''}</div>
        <div class="serie-temps">${s.temporadas.map((t) => `<button class="temp-chip" data-temp="${esc(t.numero)}" title="Escolher esta temporada no topo">
          T${esc(t.numero)} <span>${t.enviados} enviados</span></button>`).join('')}</div>
        <div class="serie-cob"></div></div>`;
    const { fundo, fechar } = modal({ icone: 'filme', titulo: 'Minhas séries',
      texto: 'O que você já enviou, por série e temporada (a partir do Histórico). Clique numa temporada para escolhê-la no topo e continuar.',
      corpo: r.series.length ? `<div class="series-lista">${r.series.map(cartao).join('')}</div>`
        : '<div class="nota neutra">Nada enviado ainda. Depois do primeiro envio, suas séries aparecem aqui.</div>',
      botoes: [{ txt: 'Fechar', cls: 'btn-pri' }] });
    $('.modal', fundo).classList.add('largo');
    $$('.temp-chip', fundo).forEach((b) => b.onclick = async () => {
      if (!(await podeSubstituirLista())) return;
      const c = b.closest('.serie-cartao').dataset.codigo;
      fechar();
      resultado(await chamar('abrir_serie', c, b.dataset.temp));
    });
    $$('.btn-mudancas', fundo).forEach((b) => b.onclick = async () => {
      const c = b.closest('.serie-cartao').dataset.codigo;
      fechar();
      aviso('Conferindo episódio por episódio no TMDB. Acompanhe a barra de progresso.');
      resultado(await chamar('conferir_mudancas', c));
    });
    $$('.btn-cobertura', fundo).forEach((b) => b.onclick = async () => {
      const cartao = b.closest('.serie-cartao'), caixa = $('.serie-cob', cartao);
      b.disabled = true; caixa.innerHTML = '<span class="apagado">Consultando o TMDB...</span>';
      const c = await chamar('cobertura_tmdb', cartao.dataset.codigo);
      b.disabled = false;
      if (c.erro) { caixa.innerHTML = `<span class="erro-txt">${esc(c.erro)}</span>`; return; }
      caixa.innerHTML = `<div class="cob-cab">No TMDB em ${esc(c.idioma)} (envios das últimas horas podem demorar a aparecer aqui):</div>` + c.temporadas.map((t) => {
        const pct = t.total ? Math.round(Math.min(t.titulos, t.sinopses) / t.total * 100) : 0;
        return `<div class="cob-linha"><span>T${esc(t.numero)}</span><div class="cob-barra"><i style="width:${pct}%"></i></div>
          <span>${t.titulos}/${t.total} títulos · ${t.sinopses}/${t.total} sinopses</span>
          <button class="btn-mini cob-ir" data-temp="${esc(t.numero)}">${pct >= 100 ? 'Completa' : 'Fazer'}</button></div>`;
      }).join('');
      $$('.cob-ir', caixa).forEach((x) => x.onclick = async () => {
        if (!(await podeSubstituirLista())) return;
        fechar();
        resultado(await chamar('abrir_serie', cartao.dataset.codigo, x.dataset.temp));
      });
    });
  }

  async function abrirGlossario() {
    const r = await chamar('ler_glossarios');
    if (!r.series.length) { aviso('Escolha uma série no topo (ou importe episódios) para montar o glossário dela.'); return; }
    const opcoes = r.series.map((x, i) => `<option value="${i}">${esc(x.nome)}</option>`).join('');
    const textos = r.series.map((x) => x.texto);
    let atual = 0;
    const { fundo } = modal({ icone: 'livro', titulo: 'Glossário da série',
      texto: 'Opcional. Anote como você quer certos termos, um por linha. O glossário vai junto no “Copiar para traduzir” e a IA segue as suas escolhas. Fica guardado para as próximas temporadas.',
      corpo: `<div class="campo"><label for="glo-serie">Série</label><select class="entrada" id="glo-serie">${opcoes}</select></div>
        <textarea class="entrada" id="glo-texto" style="min-height:240px;font-size:13px" placeholder="Exemplos:&#10;Scroll = Pergaminho&#10;Quest = Missão&#10;Power Animals (manter em inglês)&#10;Orgs (manter)&#10;Gao Lion (manter)"></textarea>
        <div class="nota neutra">Dica: use “Original = Tradução” para trocar, ou “(manter)” para não traduzir. Deixe vazio para não usar.</div>`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Salvar', cls: 'btn-pri', acao: async (f) => {
        textos[atual] = $('#glo-texto', f).value;
        let ultimo = null;
        for (let i = 0; i < r.series.length; i++) {
          if (textos[i] !== r.series[i].texto) ultimo = await chamar('salvar_glossario', r.series[i].codigo, r.series[i].nome, textos[i]);
        }
        if (ultimo) resultado(ultimo);
      } }] });
    const sel = $('#glo-serie', fundo), txt = $('#glo-texto', fundo);
    txt.value = textos[0];
    sel.onchange = () => { textos[atual] = txt.value; atual = Number(sel.value); txt.value = textos[atual]; };
  }

  async function abrirInstrucoes() {
    const r = await chamar('ler_instrucoes');
    const { fundo } = modal({ icone: 'lapis', titulo: 'Instruções de tradução',
      texto: 'Vão junto com os textos quando você clica em “Copiar para traduzir”. Os trechos {serie}, {ano}, {temporada} e {idioma} são trocados pelos dados da série.',
      corpo: `<textarea class="entrada" id="instr" style="min-height:360px;font-size:13px">${esc(r.texto)}</textarea>`,
      botoes: [{ txt: 'Voltar ao padrão', acao: (f) => { $('#instr', f).value = r.padrao; return true; } },
        { txt: 'Cancelar' }, { txt: 'Salvar', cls: 'btn-pri', acao: async (f) => { await chamar('salvar_instrucoes', $('#instr', f).value); aviso('Instruções salvas.'); } }] });
    $('.modal-rodape .btn-sec', fundo).style.marginRight = 'auto';
  }

  function abrirGuia() {
    modal({ icone: 'livro', titulo: 'Como usar o Sinopse Editor', texto: 'As etapas podem ser feitas em qualquer ordem, e o trabalho é guardado sozinho.',
      corpo: `<div class="passos">
        <div class="passo"><b><span class="num">1</span>Escolha a série</b><span>Busque pelo nome (com a chave da API) ou pelo código do TMDB, no topo. Escolha a temporada nas etiquetas.</span></div>
        <div class="passo"><b><span class="num">2</span>Importe os textos</b><span>Do TMDB em inglês, de uma Wiki, de uma planilha — ou várias temporadas e séries pelo Lote.</span></div>
        <div class="passo"><b><span class="num">3</span>Traduza</b><span>“Copiar para traduzir” leva as instruções prontas. Cole no ChatGPT ou Claude, copie a resposta inteira e clique em “Colar tradução”.</span></div>
        <div class="passo"><b><span class="num">4</span>Confira e envie</b><span>Clique num episódio para revisar ao lado. Escolha manter ou substituir o que já existe e envie.</span></div></div>
        <div class="nota neutra"><b>Atalhos:</b> ↑ ↓ (ou J K) passam de episódio · Espaço marca/desmarca · Enter edita o título · Ctrl+F localiza e substitui · Shift+clique marca uma faixa.</div>
        <div class="nota neutra">Dica: no primeiro envio de uma série, deixe marcados só 1 ou 2 episódios e confira no site do TMDB.</div>
        <p style="margin:0;font-size:12px;color:var(--apagado)">Este programa usa a API do TMDB, mas não é aprovado nem certificado pelo TMDB.</p>`,
      botoes: [{ txt: 'Fechar', cls: 'btn-pri' }] });
  }

  async function abrirTrabalhos() {
    const desenhar = (lista) => lista.length ? lista.map((t) => `
      <div class="caixa-info" style="flex-direction:row;align-items:center;gap:12px">
        <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">
          <b style="color:var(--texto)">${esc(t.nome)}</b>
          <span>${esc(t.grupos.join(' · '))}${t.grupos.length >= 4 ? ' ...' : ''}</span>
          <span>${t.total} episódios · ${t.faltam} pendentes · salvo em ${esc(t.quando)}</span></div>
        <button class="btn-sec" data-abrir="${esc(t.arquivo)}">Abrir</button>
        <button class="btn-icone" data-excluir="${esc(t.arquivo)}" aria-label="Excluir ${esc(t.nome)}" style="width:38px;height:38px">${ic('lixo')}</button>
      </div>`).join('') : '<span style="font-size:13px;color:var(--apagado)">Nenhum trabalho salvo ainda.</span>';
    const r = await chamar('listar_trabalhos');
    const sugestao = S.E.episodios.length ? (grupos(S.E.episodios).size > 1 ? 'Lote ' : '') + (S.E.episodios[0].serie || 'Trabalho') : '';
    const { fundo, fechar } = modal({ icone: 'salvos', titulo: 'Trabalhos salvos',
      texto: 'Guarde a lista atual com um nome para continuar outro dia, e abra outro trabalho quando quiser. O trabalho em andamento continua sendo guardado sozinho.',
      corpo: `<div class="linha-flex"><input class="entrada" id="trab-nome" type="text" placeholder="Nome do trabalho" value="${esc(sugestao)}" style="flex:1">
          <button class="btn-pri" id="trab-salvar">${ic('salvos')} Salvar a lista atual</button></div>
        <div id="trab-lista" style="display:flex;flex-direction:column;gap:8px">${desenhar(r.trabalhos)}</div>`,
      botoes: [{ txt: 'Fechar' }] });
    const lista = $('#trab-lista', fundo);
    $('#trab-salvar', fundo).onclick = async () => {
      const res = await chamar('salvar_trabalho_como', $('#trab-nome', fundo).value);
      resultado(res);
      if (res.ok) lista.innerHTML = desenhar((await chamar('listar_trabalhos')).trabalhos);
    };
    lista.addEventListener('click', async (ev) => {
      const abrir = ev.target.closest('[data-abrir]'), excluir = ev.target.closest('[data-excluir]');
      if (abrir) {
        if (S.E.episodios.length && !(await confirmar('Abrir este trabalho?', 'A lista atual será trocada. Se quiser guardá-la, salve antes.', 'Abrir'))) return;
        resultado(await chamar('abrir_trabalho', abrir.dataset.abrir));
        fechar();
      } else if (excluir) {
        if (await confirmar('Excluir trabalho?', 'O trabalho salvo será apagado (nada muda no TMDB).', 'Excluir'))
          lista.innerHTML = desenhar((await chamar('excluir_trabalho', excluir.dataset.excluir)).trabalhos);
      }
    });
  }

  let historicoAberto = null;
  async function abrirHistorico() {
    const r = await chamar('ler_historico');
    const n = await chamar('estatisticas');
    const numeros = `<div class="numeros">
        <div class="numero"><b>${n.enviados}</b><span>episódios enviados</span></div>
        <div class="numero"><b>${n.series}</b><span>séries · ${n.temporadas} temporadas</span></div>
        <div class="numero"><b>${n.semana}</b><span>nos últimos 7 dias · ${n.hoje} hoje</span></div>
        <div class="numero"><b>${n.sinopses}</b><span>sinopses · ${n.titulos} títulos</span></div></div>`;
    const regs = r.registros || [];
    const corte = (t) => esc((t || '').length > 140 ? t.slice(0, 140) + '…' : (t || ''));
    const mud = (campo, antes, depois) => antes === undefined ? '' :
      `<div class="hist-mud">${campo}: ${antes ? `<del>${corte(antes)}</del>` : '<i>vazio</i>'} → <ins>${depois ? corte(depois) : '<i>vazio</i>'}</ins></div>`;
    const corpo = numeros + (regs.length ? `<div style="display:flex;flex-direction:column;gap:8px">${regs.map((h) => `
      <label class="hist-linha">
        <input type="checkbox" value="${esc(h.id)}" aria-label="Escolher para desfazer">
        <span class="quando">${esc(h.quando.slice(8, 10) + '/' + h.quando.slice(5, 7) + ' ' + h.quando.slice(11, 16))}</span>
        <span><span class="qual">${esc(h.serie || 'Série ' + h.codigo)} · T${esc(h.temporada)} E${esc(h.numero)} <span style="color:#6E778C;font-weight:400">(${esc(h.idioma)})</span></span>
          ${mud('Título', h.antes?.titulo, h.depois?.titulo)}${mud('Sinopse', h.antes?.sinopse, h.depois?.sinopse)}</span>
        <span class="hist-tipo ${h.tipo === 'desfazer' ? 'desfeito' : ''}">${h.tipo === 'desfazer' ? 'Desfeito' : 'Enviado'}</span>
      </label>`).join('')}</div>`
      : '<div class="vazio" style="padding:40px"><div class="icone-grande">' + ic('relogio', 'i-20') + '</div><h3>Nenhum envio ainda</h3><p>Cada episódio enviado aparece aqui, com o texto que havia antes no TMDB.</p></div>');
    const m = modal({ icone: 'relogio', titulo: 'Histórico de envios',
      texto: 'O que foi enviado, quando, e o texto que havia antes. Marque e clique em “Desfazer” para devolver o texto antigo ao TMDB.',
      corpo, info: regs.length ? `${regs.length} envio(s) registrados` : '',
      botoes: [{ txt: 'Fechar' }, ...(regs.length ? [{ txt: 'Desfazer selecionados', cls: 'btn-pri amarelo', icone: 'desfazer', acao: async (f) => {
        const ids = $$('input[type="checkbox"]:checked', f).map((c) => c.value);
        if (!ids.length) { aviso('Marque pelo menos um envio para desfazer.'); return true; }
        if (!(await confirmar('Desfazer envios?', `O texto antigo de ${ids.length} envio(s) vai voltar para o TMDB.`, 'Desfazer', true))) return true;
        const res = await chamar('desfazer', ids);
        if (res.precisa_login) { pedirLogin('Para desfazer no TMDB, o programa precisa da sua conta.'); return true; }
        resultado(res);
        if (res.ok) aviso(`Desfazendo ${res.total} envio(s)... acompanhe pelo rodapé.`);
      } }] : [])] });
    historicoAberto = m;
  }

  async function tentarDeNovo() {
    const falhas = S.E.episodios.filter((e) => e.situacao === 'Falhou');
    if (!falhas.length) return;
    const outros = S.E.episodios.filter((e) => e.enviar && e.situacao !== 'Falhou' && !finalizado(e));
    if (outros.length && !(await confirmar('Tentar de novo só os que falharam?',
      `Os ${outros.length} outros episódios marcados serão desmarcados, e só os ${falhas.length} que falharam serão enviados.`, 'Continuar'))) return;
    await chamar('marcar_varios', outros.map((e) => e.id), false);
    await chamar('marcar_varios', falhas.map((e) => e.id), true);
    S.filtro = 'problema';
    enviar();
  }

  async function enviar() {
    const p = await chamar('preparar_envio');
    if (p.precisa_login) { pedirLogin('Para enviar ao TMDB, o programa precisa da sua conta.'); return; }
    if (!p.total) { aviso(p.sem_codigo ? 'Os episódios marcados estão sem o código da série. Escolha a série no topo.' : 'Nenhum episódio marcado com título ou sinopse.'); return; }
    let regra, amarela = S.sub.t || S.sub.s;
    if (S.sub.t && S.sub.s) regra = 'Títulos e sinopses que já existem no TMDB serão <b>substituídos</b>.';
    else if (S.sub.t) regra = 'Títulos que já existem serão <b>substituídos</b>. Sinopses existentes serão mantidas.';
    else if (S.sub.s) regra = 'Sinopses que já existem serão <b>substituídas</b>. Títulos existentes serão mantidos.';
    else regra = 'O que já existe no TMDB será mantido; só os campos vazios serão preenchidos.';
    let previsao = '';
    if (p.previsao) {
      const ex = p.existentes, trocaT = S.sub.t ? ex.titulo : 0, trocaS = S.sub.s ? ex.sinopse : 0;
      const mantT = S.sub.t ? 0 : ex.titulo, mantS = S.sub.s ? 0 : ex.sinopse;
      const partes = [];
      if (trocaT || trocaS) partes.push(`<b>Serão trocados:</b> ${trocaT} título(s) e ${trocaS} sinopse(s) que já existem no TMDB.`);
      if (mantT || mantS) partes.push(`<b>Serão mantidos:</b> ${mantT} título(s) e ${mantS} sinopse(s) que já existem.`);
      if (!ex.titulo && !ex.sinopse) partes.push('Nenhum desses episódios tem texto em português no TMDB ainda.');
      previsao = `<div class="nota neutra">${partes.join('<br>')}${trocaT || trocaS ? '<br>O texto antigo fica guardado no Histórico e pode ser desfeito.' : ''}</div>`;
    } else if (amarela) {
      previsao = '<div class="nota neutra">O texto antigo de cada campo trocado fica guardado no Histórico e pode ser desfeito.</div>';
    }
    const { fundo: fundoEnvio, fechar: fecharEnvio } = modal({ icone: amarela ? 'alerta' : 'enviar', alerta: amarela, titulo: `Enviar ${p.total} episódio${p.total > 1 ? 's' : ''} em ${p.idioma}?`,
      corpo: `<ul class="lista-grupos">${p.grupos.map((g) => `<li><span>${esc(g.nome)}</span><span>${g.quantidade} ep.</span></li>`).join('')}</ul>
        <div class="nota ${amarela ? 'amarela' : 'neutra'}">${regra}</div>${previsao}
        ${p.sem_codigo ? `<div class="nota neutra">${p.sem_codigo} episódio(s) sem código da série ficarão de fora.</div>` : ''}
        ${(p.revisao || []).length ? `<div class="nota amarela"><b>Revisão: ${p.revisao.length} episódio(s) para dar uma olhada</b> (clique para abrir; você pode enviar assim mesmo)
          <div class="revisao">${p.revisao.slice(0, 40).map((r) => `<button class="rev-item" data-id="${esc(r.id)}"><b>${esc(r.rotulo)}</b> ${r.itens.map(esc).join(' · ')}</button>`).join('')}
          ${p.revisao.length > 40 ? `<span>... e mais ${p.revisao.length - 40}</span>` : ''}</div></div>` : ''}`,
      botoes: [{ txt: 'Cancelar' }, { txt: 'Enviar agora', cls: 'btn-pri verde', icone: 'enviar', acao: async () => {
        resultado(await chamar('enviar', S.sub.t, S.sub.s));
      } }] });
    $$('.rev-item', fundoEnvio).forEach((b) => b.onclick = () => {
      fecharEnvio();
      S.filtro = 'todos';
      $$('#filtros button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.f === 'todos')));
      renderLista(); selecionar(b.dataset.id);
    });
  }

  // ==================================================================== busca
  let tempoBusca = null, ultimaBusca = '';
  async function buscar(texto) {
    const caixa = $('#resultados');
    texto = texto.trim();
    if (!texto) { caixa.classList.remove('aberto'); return; }
    ultimaBusca = texto;
    caixa.innerHTML = '<div class="msg">Buscando...</div>';
    caixa.classList.add('aberto');
    const r = await chamar('buscar_series', texto);
    if (texto !== ultimaBusca) return;
    if (r.erro) { caixa.innerHTML = `<div class="msg">${esc(r.erro)}</div>`; return; }
    if (!r.resultados.length) { caixa.innerHTML = '<div class="msg">Nenhuma série encontrada.</div>'; return; }
    caixa.innerHTML = r.resultados.map((s) => `
      <button class="resultado" role="option" data-codigo="${esc(s.codigo)}">
        ${s.poster ? `<img class="poster m" src="${esc(s.poster)}" alt="">` : '<div class="poster m" aria-hidden="true"></div>'}
        <span><b>${esc(s.nome)}${s.ano ? ' (' + esc(s.ano) + ')' : ''}</b><small>${s.original && s.original !== s.nome ? esc(s.original) + ' · ' : ''}TMDB ${esc(s.codigo)}</small></span>
      </button>`).join('');
    $$('.resultado', caixa).forEach((b) => b.onclick = async () => {
      caixa.classList.remove('aberto');
      $('#busca').value = '';
      resultado(await chamar('escolher_serie', b.dataset.codigo));
    });
  }

  // ==================================================================== início
  function ligarTela() {
    $('#imp-tmdb').onclick = importarTmdb;
    $('#imp-wiki').onclick = importarWiki;
    $('#imp-tvdb').onclick = importarTvdb;
    $('#imp-lote').onclick = abrirLote;
    $('#imp-planilha').onclick = abrirPlanilha;
    $('#btn-copiar').onclick = async () => resultado(await chamar('copiar'));
    $('#btn-colar').onclick = async () => resultado(await chamar('colar'));
    $('#btn-instrucoes').onclick = abrirInstrucoes;
    $('#btn-glossario').onclick = abrirGlossario;
    $('#btn-exportar').onclick = async () => resultado(await chamar('exportar_planilha'));
    $('#btn-modelo').onclick = async () => resultado(await chamar('baixar_modelo'));
    $('#btn-config').onclick = abrirConfig;
    $('#btn-guia').onclick = abrirGuia;
    $('#btn-historico').onclick = abrirHistorico;
    $('#btn-trabalhos').onclick = abrirTrabalhos;
    try { aplicarTema(localStorage.getItem('temaClaro') === '1'); } catch (_) {}
    try { if (localStorage.getItem('animacoes') === '0') document.body.classList.add('sem-animacao'); } catch (_) {}
    requestAnimationFrame(() => document.body.classList.add('pronto'));
    const aplicarCompacta = (on) => { document.body.classList.toggle('compacta', on); $('#btn-compacta').setAttribute('aria-pressed', String(on)); };
    try { aplicarCompacta(localStorage.getItem('listaCompacta') === '1'); } catch (_) {}
    $('#btn-compacta').onclick = () => { const on = !document.body.classList.contains('compacta'); aplicarCompacta(on); try { localStorage.setItem('listaCompacta', on ? '1' : '0'); } catch (_) {} };
    $('#btn-minhas').onclick = abrirMinhasSeries;
    // Lateral aberta (com nomes e séries recentes) ou recolhida (só ícones). Lembra a escolha.
    const aplicarLateral = (aberta) => {
      document.body.classList.toggle('lateral-aberta', aberta);
      const b = $('#btn-lateral');
      b.setAttribute('aria-label', aberta ? 'Recolher a barra lateral' : 'Abrir a barra lateral');
      $('.rot', b).textContent = aberta ? 'Recolher' : 'Abrir';
      if (aberta) renderRecentes();
    };
    try { aplicarLateral(localStorage.getItem('lateralAberta') !== '0'); } catch (_) { aplicarLateral(true); }
    $('#btn-lateral').onclick = () => {
      const aberta = !document.body.classList.contains('lateral-aberta');
      aplicarLateral(aberta);
      try { localStorage.setItem('lateralAberta', aberta ? '1' : '0'); } catch (_) {}
    };
    $('#btn-lado').onclick = abrirLadoALado;
    $('#btn-repetir').onclick = tentarDeNovo;
    $('#btn-complementar').onclick = complementar;
    $('#btn-pt-tvdb').onclick = async () => {
      if (await confirmar('Usar o português do TVDB?', 'O título e a sinopse que o TVDB já tem em português vão para a tradução desses episódios. Você pode revisar antes de enviar.', 'Usar'))
        resultado(await chamar('usar_portugues_tvdb', []));
    };
    $('#btn-localizar').onclick = abrirLocalizar;
    $('#btn-numeracao').onclick = abrirNumeracao;
    $('#btn-prefixo').onclick = abrirPrefixo;
    $('#btn-enviar').onclick = enviar;
    $('#btn-parar').onclick = () => chamar('parar');
    $('#btn-limpar').onclick = async () => {
      if (S.E.episodios.length && await confirmar('Limpar a lista?', 'Todos os episódios da lista serão apagados.', 'Limpar')) chamar('limpar');
    };
    $('#btn-conta').onclick = async () => {
      if (S.login === 'conectado' && !(await confirmar('Você já está conectado', 'Sua conta do TMDB já está conectada. Quer entrar com outra conta?', 'Entrar com outra'))) return;
      chamar('entrar');
    };
    $('#btn-navegador').onclick = async () => { S.E.visivel = await chamar('mostrar_navegador', !S.E.visivel); renderTopo(); };
    $('#btn-mensagens').onclick = () => {
      const m = $('#mensagens'), aberto = !m.classList.contains('aberto');
      m.classList.toggle('aberto', aberto);
      $('#btn-mensagens').setAttribute('aria-pressed', String(aberto));
    };
    $('#fechar-mensagens').onclick = () => { $('#mensagens').classList.remove('aberto'); $('#btn-mensagens').setAttribute('aria-pressed', 'false'); };
    $('#sub-titulo').onclick = () => { S.sub.t = !S.sub.t; renderRodape(); };
    $('#sub-sinopse').onclick = () => { S.sub.s = !S.sub.s; renderRodape(); };
    $$('#filtros button').forEach((b) => b.onclick = () => { S.filtro = b.dataset.f; renderLista(); renderInspetor(); });
    $('#marcar-todos').onchange = (ev) => {
      const ids = visiveis().filter((e) => !finalizado(e)).map((e) => e.id);
      chamar('marcar_varios', ids, ev.target.checked);
    };
    $('#rolagem').addEventListener('click', async (ev) => {
      const tirarGrupo = ev.target.closest('[data-tirar-grupo]');
      if (tirarGrupo) {
        const doGrupo = S.E.episodios.filter((x) => grupoDe(x) === tirarGrupo.dataset.tirarGrupo);
        if (!doGrupo.length) return;
        if (!(await confirmar('Tirar a temporada da lista?', `${esc(nomeGrupo(doGrupo[0]))}: ${doGrupo.length} episódio(s) saem só da lista do programa. Nada muda no TMDB.`, 'Tirar', true))) return;
        if (doGrupo.some((x) => String(x.id) === String(S.sel))) { S.sel = null; $('#inspetor').classList.remove('aberto'); }
        resultado(await chamar('remover', doGrupo.map((x) => x.id)));
        return;
      }
      const tirar = ev.target.closest('[data-tirar]');
      if (tirar) {
        ev.stopPropagation();
        const e = porId(tirar.dataset.tirar);
        if (!e) return;
        if (!(await confirmar('Tirar da lista?', `O episódio ${e.numero} de ${esc(nomeGrupo(e))} sai só da lista do programa (nada muda no TMDB).`, 'Tirar'))) return;
        if (String(e.id) === String(S.sel)) { S.sel = null; $('#inspetor').classList.remove('aberto'); }
        resultado(await chamar('remover', [e.id]));
        return;
      }
      const linha = ev.target.closest('.ep');
      if (linha) selecionar(Number(linha.dataset.id));
    });
    // Shift + clique numa caixa marca/desmarca todo o intervalo desde o último clique.
    let ultimoClicado = null, comShift = false;
    $('#rolagem').addEventListener('click', (ev) => {
      if (ev.target.type === 'checkbox') comShift = ev.shiftKey;
    }, true);
    $('#rolagem').addEventListener('change', (ev) => {
      if (ev.target.type !== 'checkbox') return;
      if (ev.target.dataset.grupo) {
        // Caixa da temporada: marca/desmarca todos dela que ainda não foram enviados.
        const valor = ev.target.checked;
        const doGrupo = S.E.episodios.filter((x) => grupoDe(x) === ev.target.dataset.grupo && !finalizado(x));
        doGrupo.forEach((x) => { x.enviar = valor; });
        chamar('marcar_varios', doGrupo.map((x) => x.id), valor);
        aviso(`${doGrupo.length} episódios ${valor ? 'marcados' : 'desmarcados'} em ${nomeGrupo(doGrupo[0] || {})}.`, 2200);
        renderLista();
        return;
      }
      const id = Number(ev.target.closest('.ep').dataset.id), e = porId(id);
      const valor = ev.target.checked;
      const lista = visiveis().filter((x) => !finalizado(x));
      const a = lista.findIndex((x) => x.id === ultimoClicado), b = lista.findIndex((x) => x.id === id);
      if (comShift && a >= 0 && b >= 0 && a !== b) {
        const faixa = lista.slice(Math.min(a, b), Math.max(a, b) + 1);
        faixa.forEach((x) => {
          x.enviar = valor;
          const caixa = $(`.ep[data-id="${x.id}"] input[type="checkbox"]`);
          if (caixa) caixa.checked = valor;
        });
        chamar('marcar_varios', faixa.map((x) => x.id), valor);
        aviso(`${faixa.length} episódios ${valor ? 'marcados' : 'desmarcados'}.`, 2000);
      } else {
        e.enviar = valor;
        chamar('marcar', id, valor);
      }
      ultimoClicado = id;
      comShift = false;
      renderRodape();
    });
    const busca = $('#busca');
    busca.addEventListener('input', () => {
      clearTimeout(tempoBusca);
      const v = busca.value;
      if (v.trim().length >= 3 && !/^\d+$/.test(v.trim())) tempoBusca = setTimeout(() => buscar(v), 450);
      else if (!v.trim()) $('#resultados').classList.remove('aberto');
    });
    busca.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { clearTimeout(tempoBusca); buscar(busca.value); }
      if (ev.key === 'Escape') $('#resultados').classList.remove('aberto');
    });
    document.addEventListener('mousedown', (ev) => { if (!ev.target.closest('.busca')) $('#resultados').classList.remove('aberto'); });
  }

  function ligarAtalhos() {
    document.addEventListener('keydown', (ev) => {
      const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
      const modalAberto = !!$('.fundo-modal');
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'f' && !modalAberto) { ev.preventDefault(); abrirLocalizar(); return; }
      if (digitando || modalAberto) return;
      const lista = visiveis();
      const i = lista.findIndex((x) => x.id === S.sel);
      if (ev.key === 'ArrowDown' || ev.key === 'j') { ev.preventDefault(); selecionar((lista[i + 1] || lista[0])?.id); }
      else if (ev.key === 'ArrowUp' || ev.key === 'k') { ev.preventDefault(); selecionar((lista[i - 1] || lista[0])?.id); }
      else if (ev.key === ' ' && S.sel != null) {
        ev.preventDefault();
        const e = porId(S.sel);
        if (e && !finalizado(e)) { e.enviar = !e.enviar; chamar('marcar', e.id, e.enviar); atualizarLinha(e); renderRodape(); }
      } else if (ev.key === 'Enter' && S.sel != null) { ev.preventDefault(); $('#ed-titulo')?.focus(); }
    });
  }

  async function iniciar() {
    ligarTela();
    ligarAtalhos();
    const r = await chamar('iniciar');
    S.E = r.estado;
    S.temChave = r.tem_chave;
    S.login = r.login;
    $('#versao').textContent = 'v' + r.versao;
    const c = await chamar('ler_config');
    S.limite = Number(c.limite) || 350;
    renderTudo(); renderLogin();
    if (r.login === 'verificando') chamar('verificar_login');
    if (r.pendente) {
      const p = r.pendente;
      modal({ icone: 'lista', titulo: 'Continuar de onde parou?',
        texto: `${p.faltam} de ${p.total} episódios ainda não foram enviados.`,
        corpo: `<ul class="lista-grupos">${p.grupos.slice(0, 8).map((g) => `<li><span>${esc(g)}</span><span></span></li>`).join('')}${p.grupos.length > 8 ? `<li><span>... e mais ${p.grupos.length - 8}</span><span></span></li>` : ''}</ul>`,
        botoes: [{ txt: 'Começar do zero' }, { txt: 'Continuar', cls: 'btn-pri', acao: async () => { S.E = await chamar('continuar_trabalho'); renderTudo(); } }] });
    }
  }

  if (window.pywebview?.api) iniciar();
  else window.addEventListener('pywebviewready', iniciar);
})();
