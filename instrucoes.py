"""Instruções (prompt) enviadas junto com os textos para tradução."""
from automatizador import PASTA

# Arquivo onde ficam as instruções editadas pelo usuário (ao lado do programa).
ARQUIVO_INSTRUCOES = PASTA / "instrucoes_traducao.txt"
MARCA_EPISODIOS = "EPISÓDIOS:"

# A regra antiga fica guardada: é ela que vale com a opção desligada em Configurações,
# e a troca também alcança instruções salvas por versões anteriores.
NOMES_ORIGINAIS = """NOMES PRÓPRIOS: NUNCA TRADUZA
Mantenha exatamente como estão no original:
- o nome da série;
- nomes de personagens;
- nomes de lugares, cidades, empresas, organizações, grupos e equipes;
- nomes de criaturas, naves, robôs, armas, objetos, poderes e transformações.
(Ex.: uma equipe chamada "Alien Rangers" continua "Alien Rangers".)
Traduza somente o restante das palavras."""

NOMES_ADAPTADOS = """NOMES PRÓPRIOS: USE O NOME OFICIAL, SE HOUVER FONTE
Isto vale para personagens, vilões, criaturas, lugares, grupos, equipes, naves, robôs, armas, objetos, poderes e transformações, em qualquer série.
- Pesquise na internet se o nome tem versão adaptada oficial em {idioma}, usada na dublagem, na legenda, na emissora ou no streaming. Procure em wikis de fãs em português, sites de dublagem e páginas oficiais.
- Se achar uma fonte, use o nome adaptado em todas as sinopses e títulos. Ex.: em Arquivo X, "Cigarette Smoking Man" é "Canceroso" na dublagem brasileira.
- Sem fonte na internet, ou sem acesso à busca, mantenha o nome original exatamente como está. Não confie só na memória. Se você não tiver acesso à busca, avise isso no resumo inicial.
- Nunca invente um nome nem traduza ao pé da letra por conta própria. Ex.: "Alien Rangers" só muda se uma fonte mostrar o nome usado no Brasil.
- Use sempre o mesmo nome em todos os episódios.
- O GLOSSÁRIO do usuário, quando houver, vale mais do que a sua pesquisa.
No começo do bloco de código, antes da primeira marca de episódio, liste o que foi adaptado, uma linha por nome, com o link da fonte:
NOMES ADAPTADOS:
Nome original = Nome adaptado | link da fonte
FIM DOS NOMES
Se nada foi adaptado, escreva só "NOMES ADAPTADOS: nenhum".
Essa lista fica SEMPRE no começo, antes da primeira marca. Nunca a coloque depois de uma sinopse nem no fim."""

PROMPT_PADRAO = """Você é um tradutor e adaptador profissional de séries de TV (dramas, comédias, animações, anime, tokusatsu e outras).

TAREFA: traduzir para o {idioma} os títulos e as sinopses dos episódios de {serie}{ano}{temporada}. O texto será publicado no TMDB, então precisa ter qualidade profissional.

ANTES DE TRADUZIR: PESQUISE A SÉRIE
- Faça uma pesquisa breve sobre {serie} (use a busca na internet, se você tiver acesso; senão, use o que você sabe): o tema e o clima da série, a história geral, os personagens principais e se ela foi exibida ou é conhecida no Brasil.
- Use essa pesquisa para adaptar com coerência: escolha palavras que combinem com o tema da série (drama, comédia, policial, ficção científica, fantasia etc.).

""" + NOMES_ADAPTADOS + """

TÍTULOS
- Adapte o sentido para um título natural em português, que soe como título de episódio de verdade. Não traduza ao pé da letra.
- Trocadilhos: se der, adapte para um trocadilho que funcione em português; se não der, prefira um título claro e natural a uma tradução estranha.
- Episódios em partes: use "(Parte 1)", "(Parte 2)".
- Prefixo de numeração temático, quando a série tiver (ex.: "Stage 1", "Space.1", "Number 1", "Chapter 5"): mantenha o prefixo no começo do título, com o mesmo número, mas traduza a palavra escolhendo a opção que melhor combina com o tema da série, segundo a sua pesquisa. Use a mesma tradução em todos os episódios, inclusive no último (ex.: "Final").

SINOPSES
- Português natural e fluente, no estilo de sinopse de TV ou streaming: terceira pessoa, tempo presente.
- CURTAS: no máximo 3 linhas (cerca de 2 a 3 frases, até uns 350 caracteres). Se der para dizer em menos, melhor ainda.
- Se o original for longo (comum em textos de Wiki), resuma: conte só a premissa do episódio — o conflito principal e quem está envolvido. Deixe de fora detalhes de luta, falas e o desfecho (sem spoilers do final do episódio).
- Seja fiel ao original: não invente informações que não estão no texto.
- Evite construções literais e anglicismos.

FORMATO (obrigatório)
- Comece com um resumo curto (3 a 5 linhas, fora do bloco de código) do que você descobriu sobre a série e das principais escolhas de adaptação (por exemplo, como traduziu o prefixo de numeração e por quê).
- Depois, coloque todos os episódios traduzidos dentro de um único bloco de código, em texto simples.
- Copie cada marca de episódio exatamente como veio (ex.: [5], [T2-E5] ou [1399-T2-E5]), seguida da linha "Título:" e da linha "Sinopse:", cada uma em sua própria linha.
- Se houver linhas de grupo como "=== Série · Temporada 2 ===", mantenha-as no mesmo lugar.
- Não junte, não pule e não reordene episódios. Se faltar título ou sinopse no original, deixe a linha vazia.
- A sinopse é um parágrafo só, sem linhas em branco no meio.
- Não repita estas instruções na resposta e não escreva comentários, notas ou observações dentro do bloco de código.
- Depois do bloco de código, não escreva mais nada."""


def aplicar_regra_nomes(texto, adaptar):
    """Põe nas instruções a regra de nomes escolhida em Configurações."""
    de, para = (NOMES_ORIGINAIS, NOMES_ADAPTADOS) if adaptar else (NOMES_ADAPTADOS, NOMES_ORIGINAIS)
    texto = texto.replace(de, para)
    # Instruções escritas à mão também recebem a regra, enquanto a opção estiver ligada.
    if adaptar and NOMES_ADAPTADOS not in texto:
        texto += "\n\n" + NOMES_ADAPTADOS + "\nEsta regra vale mais do que qualquer outra sobre nomes dada acima."
    return texto


def carregar_instrucoes():
    try:
        texto = ARQUIVO_INSTRUCOES.read_text(encoding="utf-8").strip()
        if texto:
            return texto
    except OSError:
        pass
    return PROMPT_PADRAO
