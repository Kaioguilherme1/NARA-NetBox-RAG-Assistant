"""Nucleo do assistente interno NetBox com RAG (Postgres + pgvector)."""

import glob
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import psycopg
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

DB_URI = os.environ.get("DB_URI", "******localhost:5432/rag")
MODELO_CHAT = os.environ.get("MODELO_CHAT", "gpt-5.4")
MODELO_EMBED = os.environ.get("MODELO_EMBED", "text-embedding-3-small")

# RAG top-k configuration (configuravel via .env)
TOP_K_RAG_MAIN = int(os.environ.get("TOP_K_RAG_MAIN", "8"))
TOP_K_RAG_FALLBACK = int(os.environ.get("TOP_K_RAG_FALLBACK", "5"))
TOP_K_LIST_FONTS = int(os.environ.get("TOP_K_LIST_FONTS", "200"))
RAG_CACHE_TTL_SECONDS = int(os.environ.get("RAG_CACHE_TTL_SECONDS", "300"))
RAG_CACHE_MAX_ENTRIES = int(os.environ.get("RAG_CACHE_MAX_ENTRIES", "256"))
MAX_RAG_CONTEXT_CHUNKS = int(os.environ.get("MAX_RAG_CONTEXT_CHUNKS", "6"))

DOCS_REPO_URL = os.environ.get("DOCS_REPO_URL", "https://example.com/your-org/netbox-docs.git")
DOCS_REPO_BRANCH = os.environ.get("DOCS_REPO_BRANCH", "main")
DOCS_REPO_TOKEN = os.environ.get("DOCS_REPO_TOKEN", "").strip()
DOCS_REPO_USERNAME = os.environ.get("DOCS_REPO_USERNAME", "oauth2").strip() or "oauth2"
DOCS_LOCAL_DIR = os.environ.get("DOCS_LOCAL_DIR", "/tmp/docs-netbox")
DOCS_LOCAL_ATTACH_DIR = os.environ.get("DOCS_LOCAL_ATTACH_DIR", "documentos_local/anexos")
NETBOX_IMPORTS_DIR = os.environ.get("NETBOX_IMPORTS_DIR", "documentos_local/imports")

SYSTEM_PROMPT = (
    "Voce e a NARA (Network Automation & Reference Assistant), uma assistente interna especializada em NetBox, "
    "arquitetura, automacao e padroes institucionais. "
    "Sua persona e tecnica, objetiva, confiavel e orientada a evidencias. "
    "Responda como uma especialista que consulta primeiro a documentacao interna antes de concluir qualquer recomendacao. "
    "Use a documentacao como autoridade principal; nao invente padroes, valores, modelos, configuracoes ou procedimentos. "
    "Se a informacao for parcial, ambigua ou incompleta, diga exatamente o que foi confirmado e o que nao foi possivel confirmar. "
    "Quando faltar informacao, indique quais dados ou documentos seriam necessarios para responder melhor. "
    "Nao utilize conhecimento externo sem autorizacao explicitamente informada pelo usuario. "
    "Quando se basear na documentacao interna, finalize sempre com a secao 'Fontes:' e liste apenas as referencias efetivamente usadas. "
    "Mantenha tom profissional, claro e direto, com foco em acuracia, padroes e operacao segura."
)

emb = OpenAIEmbeddings(model=MODELO_EMBED)

_conn = None
RAG_CACHE = {}

LIGHT_ROUTE_KEYWORDS = (
    "oi",
    "olá",
    "bom dia",
    "boa tarde",
    "boa noite",
    "como vai",
    "obrigado",
    "obrigada",
    "tudo bem",
    "ajuda",
)

SPECIALIST_ROUTE_KEYWORDS = (
    "yaml",
    "device type",
    "device-type",
    "importacao",
    "importação",
    "valide",
    "validar",
    "netbox",
    "modelo",
    "configuracao",
    "configuração",
    "padrao",
    "padrão",
    "arquitetura",
    "regras",
    "documentacao",
    "documentação",
)


def _log(msg: str):
    print(msg, flush=True)


def decidir_rota(pergunta: str) -> str:
    """Classifica a pergunta para reduzir custo de tokens sem quebrar o fluxo principal."""
    texto = (pergunta or "").strip().lower()
    if not texto:
        return "light"
    if any(kw in texto for kw in LIGHT_ROUTE_KEYWORDS):
        return "light"
    if any(kw in texto for kw in SPECIALIST_ROUTE_KEYWORDS):
        return "specialist"
    return "rag"


def resposta_rapida() -> str:
    return (
        "Posso ajudar com NetBox e documentação interna do NARA. "
        "Se quiser, descreva o caso técnico e eu te orientarei com a base documental correta."
    )


def _normalize_query(pergunta: str) -> str:
    return re.sub(r"\s+", " ", (pergunta or "").strip()).lower()


def _cache_rag_result(pergunta: str, conteudo: str):
    chave = _normalize_query(pergunta)
    if not chave:
        return
    RAG_CACHE[chave] = {"time": time.monotonic(), "value": conteudo}
    if len(RAG_CACHE) > RAG_CACHE_MAX_ENTRIES:
        oldest_key = min(RAG_CACHE, key=lambda k: RAG_CACHE[k]["time"])
        RAG_CACHE.pop(oldest_key, None)


def _get_cached_rag_result(pergunta: str):
    chave = _normalize_query(pergunta)
    if not chave:
        return None
    entry = RAG_CACHE.get(chave)
    if not entry:
        return None
    if time.monotonic() - entry["time"] > RAG_CACHE_TTL_SECONDS:
        RAG_CACHE.pop(chave, None)
        return None
    return entry["value"]


def conectar(tentativas=15):
    for _ in range(tentativas):
        try:
            return psycopg.connect(DB_URI, autocommit=True)
        except Exception as erro:
            _log(f"Aguardando o Postgres... {erro}")
            time.sleep(3)
    raise RuntimeError("Nao consegui conectar ao Postgres em " + DB_URI)


def pg():
    global _conn
    if _conn is None or _conn.closed:
        _conn = conectar()
    return _conn


def _git_run(args, repo_dir=None):
    cmd = ["git"]
    if DOCS_REPO_TOKEN:
        cmd += ["-c", f"http.extraHeader=PRIVATE-TOKEN: {DOCS_REPO_TOKEN}"]
    if repo_dir:
        cmd += ["-C", repo_dir]
    cmd += args
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as erro:
        stderr = (erro.stderr or "").strip()
        if stderr:
            _log(stderr)
        raise RuntimeError("Falha ao sincronizar repositorio de documentacao.")


def _sincronizar_repo_docs() -> tuple[str, str]:
    if not DOCS_REPO_URL:
        raise RuntimeError("DOCS_REPO_URL nao configurado.")

    repo_dir = Path(DOCS_LOCAL_DIR)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    auth_url = _repo_url_autenticada(DOCS_REPO_URL)
    _log(f"[docs] Sincronizando repositorio: {DOCS_REPO_URL} (branch={DOCS_REPO_BRANCH})")
    _log(f"[docs] Diretorio local do clone: {repo_dir}")

    if (repo_dir / ".git").exists():
        _log("[docs] Repositorio local ja existe. Atualizando com fetch/pull...")
        if DOCS_REPO_TOKEN:
            _git_run(["remote", "set-url", "origin", auth_url], str(repo_dir))
        _git_run(["fetch", "--depth", "1", "origin", DOCS_REPO_BRANCH], str(repo_dir))
        _git_run(["checkout", DOCS_REPO_BRANCH], str(repo_dir))
        _git_run(["pull", "--ff-only", "origin", DOCS_REPO_BRANCH], str(repo_dir))
    else:
        _log("[docs] Repositorio local nao existe. Clonando...")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        _git_run(
            ["clone", "--depth", "1", "--branch", DOCS_REPO_BRANCH, auth_url, str(repo_dir)],
        )

    sha = _git_run(["rev-parse", "HEAD"], str(repo_dir)).stdout.strip()
    _log(f"[docs] Sincronizacao concluida. Commit atual: {sha}")
    return str(repo_dir), sha


def _strip_front_matter(md: str) -> str:
    if not md.startswith("---\n"):
        return md
    end = md.find("\n---\n", 4)
    if end == -1:
        return md
    return md[end + 5 :]


def _secoes_markdown(md: str):
    texto = _strip_front_matter(md)
    secoes = []
    titulo = "Sem secao"
    buffer = []

    for linha in texto.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", linha)
        if m:
            if buffer:
                bloco = "\n".join(buffer).strip()
                if bloco:
                    secoes.append((titulo, bloco))
            titulo = m.group(2).strip()
            buffer = []
        else:
            buffer.append(linha)

    if buffer:
        bloco = "\n".join(buffer).strip()
        if bloco:
            secoes.append((titulo, bloco))

    return secoes


def _listar_md_recursivo(base_dir: str):
    arquivos = sorted(glob.glob(os.path.join(base_dir, "**/*.md"), recursive=True))
    return [a for a in arquivos if "/.git/" not in a]


def _coletar_fontes_markdown():
    repo_mds = []
    repo_sha = "sem-repo"
    try:
        repo_dir, repo_sha = _sincronizar_repo_docs()
        repo_mds = _listar_md_recursivo(repo_dir)
    except RuntimeError as erro:
        _log(f"Aviso: {erro}")
        _log("Continuando ingestao apenas com documentos locais anexados.")

    local_dir = Path(DOCS_LOCAL_ATTACH_DIR)
    if not local_dir.is_absolute():
        local_dir = Path(__file__).resolve().parent / local_dir
    local_mds = _listar_md_recursivo(str(local_dir)) if local_dir.exists() else []

    fontes = []
    for caminho in repo_mds:
        rel = str(Path(caminho).relative_to(repo_dir))
        fontes.append(("repo:" + rel, caminho))
    for caminho in local_mds:
        rel = str(Path(caminho).relative_to(local_dir))
        fontes.append(("anexo:" + rel, caminho))

    _log(f"[docs] Fontes encontradas: repo={len(repo_mds)} anexo={len(local_mds)}")
    return fontes, repo_sha


def _repo_url_autenticada(repo_url: str) -> str:
    if not DOCS_REPO_TOKEN or not repo_url.startswith("https://") or "@" in repo_url:
        return repo_url
    username = quote(DOCS_REPO_USERNAME, safe="")
    token = quote(DOCS_REPO_TOKEN, safe="")
    return repo_url.replace("https://", f"https://{username}:{token}@", 1)


def _imports_dir_path() -> Path:
    p = Path(NETBOX_IMPORTS_DIR)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parent / p


def preparar_base():
    cur = pg().cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS chunks "
        "(id bigserial PRIMARY KEY, content text, source text, embedding vector(1536));"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS docs_sync "
        "(repo_url text PRIMARY KEY, branch text, commit_sha text, local_doc_count int, synced_at timestamptz DEFAULT now());"
    )

    fontes, repo_sha = _coletar_fontes_markdown()
    if not fontes:
        _log("Nenhum arquivo Markdown encontrado para ingestao.")
        return

    local_docs = [src for src, _ in fontes if src.startswith("anexo:")]
    cur.execute(
        "SELECT commit_sha, local_doc_count FROM docs_sync WHERE repo_url=%s AND branch=%s",
        (DOCS_REPO_URL, DOCS_REPO_BRANCH),
    )
    sync_ant = cur.fetchone()
    if sync_ant and sync_ant[0] == repo_sha and int(sync_ant[1] or 0) == len(local_docs):
        cur.execute("SELECT count(*) FROM chunks;")
        if cur.fetchone()[0] > 0:
            _log(f"[docs] Sem mudancas de docs (commit={repo_sha}), pulando reingestao.")
            return

    _log(f"[docs] Reingerindo base vetorial (commit={repo_sha})...")
    cur.execute("DELETE FROM chunks;")
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    total = 0

    for source_prefix, caminho in fontes:
        with open(caminho, "r", encoding="utf-8", errors="ignore") as f:
            conteudo = f.read()

        for secao, texto_secao in _secoes_markdown(conteudo):
            pedacos = splitter.split_text(texto_secao)
            if not pedacos:
                continue
            vetores = emb.embed_documents(pedacos)
            for trecho, vetor in zip(pedacos, vetores):
                source = f"{source_prefix} > {secao}"
                cur.execute(
                    "INSERT INTO chunks (content, source, embedding) VALUES (%s, %s, %s::vector)",
                    (trecho, source, str(vetor)),
                )
                total += 1

    cur.execute(
        """
        INSERT INTO docs_sync (repo_url, branch, commit_sha, local_doc_count)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (repo_url)
        DO UPDATE SET
          branch=EXCLUDED.branch,
          commit_sha=EXCLUDED.commit_sha,
          local_doc_count=EXCLUDED.local_doc_count,
          synced_at=now()
        """,
        (DOCS_REPO_URL, DOCS_REPO_BRANCH, repo_sha, len(local_docs)),
    )
    _log(f"[docs] Ingeridos {total} chunks de {len(fontes)} arquivos Markdown.")


def tool_rag(pergunta: str) -> str:
    """Recupera trechos semanticos e lexicais da base vetorial para responder perguntas."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return "Pergunta vazia. Forneca um termo ou contexto para busca."

    cache = _get_cached_rag_result(pergunta)
    if cache is not None:
        return cache

    vetor = str(emb.embed_query(pergunta))
    p = pergunta.lower()
    cur = pg().cursor()
    resultados = {}

    cur.execute(
        f"SELECT id, content, source FROM chunks ORDER BY embedding <=> %s::vector LIMIT {TOP_K_RAG_MAIN}",
        (vetor,),
    )
    for cid, conteudo, fonte in cur.fetchall():
        resultados[cid] = (conteudo, fonte)

    stop = {
        "qual",
        "quais",
        "como",
        "para",
        "sobre",
        "voce",
        "netbox",
        "configuracao",
        "documentacao",
        "interna",
    }
    palavras = [w for w in re.findall(r"[a-zà-ÿ]{5,}", p) if w not in stop][:5]
    if palavras:
        like = " OR ".join(["content ILIKE %s"] * len(palavras))
        curingas = ["%" + w + "%" for w in palavras]
        cur.execute(
            f"SELECT id, content, source FROM chunks WHERE ({like}) "
            f"ORDER BY embedding <=> %s::vector LIMIT {TOP_K_RAG_FALLBACK}",
            tuple(curingas + [vetor]),
        )
        for cid, conteudo, fonte in cur.fetchall():
            resultados.setdefault(cid, (conteudo, fonte))

    trechos = [
        "[Fonte: " + (fonte or "documento") + "]\n" + conteudo
        for conteudo, fonte in list(resultados.values())[:MAX_RAG_CONTEXT_CHUNKS]
    ]
    resposta = "\n\n".join(trechos) if trechos else "Nenhum trecho encontrado na base."
    _cache_rag_result(pergunta, resposta)
    return resposta


def tool_listar_fontes(filtro: str = "") -> str:
    """Lista as fontes disponiveis no indice para facilitar citacao e auditoria."""
    cur = pg().cursor()
    if filtro:
        cur.execute(
            f"SELECT DISTINCT source FROM chunks WHERE source ILIKE %s ORDER BY source LIMIT {TOP_K_LIST_FONTS}",
            ("%" + filtro + "%",),
        )
    else:
        cur.execute(f"SELECT DISTINCT source FROM chunks ORDER BY source LIMIT {TOP_K_LIST_FONTS}")
    fontes = [row[0] for row in cur.fetchall()]
    return "\n".join(fontes) if fontes else "Nenhuma fonte indexada."


def tool_status_base() -> str:
    """Retorna status da base RAG, sincronizacao e contagem de chunks."""
    cur = pg().cursor()
    cur.execute("SELECT count(*) FROM chunks")
    total_chunks = cur.fetchone()[0]
    cur.execute(
        "SELECT branch, commit_sha, local_doc_count, synced_at FROM docs_sync "
        "WHERE repo_url=%s ORDER BY synced_at DESC LIMIT 1",
        (DOCS_REPO_URL,),
    )
    row = cur.fetchone()
    if not row:
        return f"Chunks: {total_chunks}\nSincronizacao: ainda nao registrada."
    branch, sha, local_count, synced_at = row
    return (
        f"Chunks: {total_chunks}\n"
        f"Repo: {DOCS_REPO_URL}\n"
        f"Branch: {branch}\n"
        f"Commit: {sha}\n"
        f"Docs locais anexados: {local_count}\n"
        f"Ultima sincronizacao: {synced_at}"
    )


def tool_criar_yaml_importacao(nome_arquivo: str, conteudo_yaml: str) -> str:
    """Cria arquivo YAML de importacao NetBox em pasta persistente local."""
    if not conteudo_yaml.strip():
        return "Conteudo YAML vazio. Nada foi salvo."

    seguro = Path(nome_arquivo).name.strip() or "import-netbox.yaml"
    if not (seguro.endswith(".yaml") or seguro.endswith(".yml")):
        seguro += ".yaml"

    destino_dir = _imports_dir_path()
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / seguro
    destino.write_text(conteudo_yaml.strip() + "\n", encoding="utf-8")
    return f"Arquivo YAML salvo em: {destino}"


SUBAGENTS = [
    {
        "name": "especialista-netbox",
        "description": (
            "Especialista em NetBox para analises tecnicas, configuracao, modelagem "
            "e interpretacao da documentacao interna."
        ),
        "system_prompt": (
            "Voce e um subagente especialista em NetBox. "
            "Consulte prioritariamente as tools de documentacao antes de responder. "
            "Use a documentacao interna como fonte principal para configuracoes, "
            "padroes e decisoes institucionais. "
            "Nao invente configuracoes ou padroes. "
            "Se houver informacao parcial, apresente apenas o que foi confirmado. "
            "Sinalize inferencias e finalize respostas baseadas na documentacao com 'Fontes:'."
        ),
        "tools": [
            tool_rag,
            tool_listar_fontes,
            tool_status_base,
        ],
    },


    {
        "name": "especialista-importacao-yaml-netbox",
        "description": (
            "Especialista em criar, revisar e validar YAMLs de Device Types do NetBox."
        ),
        "system_prompt": (
            "Voce cria YAMLs de importacao para NetBox. "
            "Consulte tool_rag para aplicar os padroes internos de modelagem. "
            "Utilize especificacoes de hardware confirmadas pelo pesquisador quando fornecidas. "
            "Nao invente campos, componentes ou valores ausentes. "
            "Sempre entregue o YAML completo em bloco ```yaml, pronto para copiar e colar. "
            "Nao use reticencias nem omita componentes. "
            "Se o usuario solicitar arquivo, utilize tool_criar_yaml_importacao alem de "
            "mostrar o YAML na resposta. "
            "Finalize com 'Fontes:' contendo apenas as referencias efetivamente utilizadas."
        ),
        "tools": [
            tool_rag,
            tool_listar_fontes,
            tool_criar_yaml_importacao,
        ],
    },
]


def construir_agente(persistente: bool = True):
    preparar_base()
    modelo = ChatOpenAI(model=MODELO_CHAT, temperature=0)
    tools = [tool_rag, tool_listar_fontes, tool_status_base, tool_criar_yaml_importacao]

    if persistente:
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.store.postgres import PostgresStore

        store = PostgresStore(conectar())
        store.setup()
        checkpointer = PostgresSaver(conectar())
        checkpointer.setup()
        return create_deep_agent(
            model=modelo,
            tools=tools,
            subagents=SUBAGENTS,
            system_prompt=SYSTEM_PROMPT,
            backend=CompositeBackend(
                default=StateBackend(),
                routes={"/memories/": StoreBackend(namespace=lambda ctx: ("memories",))},
            ),
            store=store,
            checkpointer=checkpointer,
        )

    return create_deep_agent(
        model=modelo,
        tools=tools,
        subagents=SUBAGENTS,
        system_prompt=SYSTEM_PROMPT,
    )
