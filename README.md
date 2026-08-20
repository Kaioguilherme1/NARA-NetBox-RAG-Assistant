# NARA — NetBox RAG Assistant

NARA é um assistente de IA para suporte operacional e técnico do NetBox, com foco em respostas baseadas em documentação interna e padrões organizacionais. A aplicação combina um agente construído com `deepagents`, ferramentas customizadas, subagentes especializados e um mecanismo de RAG com PostgreSQL + pgvector.

> **Nota:** este repositório contém apenas a aplicação. Documentação institucional,
> credenciais, bases vetoriais e configurações privadas utilizadas em implantações
> específicas não fazem parte do projeto público.

## Visão geral

O projeto foi concebido para:

- responder dúvidas sobre documentação interna e padrões de arquitetura;
- apoiar modelagem de dados e dispositivos no NetBox;
- interpretar documentação Markdown/estrutura institucional;
- facilitar geração de YAML para importação e validação de Device Types;
- reduzir risco de invenção ao exigir evidência na base documental antes de responder.

A arquitetura é orientada a evidência: quando a documentação interna não contém a resposta suficiente, o agente deve sinalizar a limitação e não inventar valores, estruturas ou regras.

## Arquitetura

```text
Usuário
  │
  ▼
Frontend / UI
  │
  ▼
API compatível com OpenAI
  │
  ▼
Agente principal (deepagents)
  │
  ├─ Tool: RAG retrieval
  ├─ Tool: listagem de fontes
  ├─ Tool: status da base
  ├─ Tool: criação de YAML
  └─ Subagentes especializados
        ├─ especialista-netbox
        └─ especialista-importacao-yaml-netbox
  │
  ▼
PostgreSQL + pgvector
  │
  ├─ chunks (conteúdo)
  ├─ source (fonte documental)
  └─ embedding (vetor)
  │
  ▼
Documentação Markdown indexada
```

## Stack tecnológica

- Python 3.11+
- FastAPI
- LangChain / OpenAI-compatible SDK
- deepagents
- PostgreSQL + pgvector
- Docker / Docker Compose
- Next.js UI (opcional)

## Estrutura do repositório

```text
.
├── README.md
├── .gitignore
├── app/
│   ├── .env.example
│   ├── .env
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── agent_core.py
│   ├── server.py
│   ├── app.py
│   ├── documentos_local/
│   │   ├── anexos/
│   │   └── repo/
│   └── README.md
├── ui/
│   ├── Dockerfile
│   └── ...
└── ...
```

## Como funciona o pipeline

1. A documentação é sincronizada em um diretório local (`documentos_local/repo`) por meio de clonagem/atualização do repositório configurado.
2. Arquivos Markdown são coletados recursivamente.
3. O conteúdo é dividido em chunks usando `RecursiveCharacterTextSplitter`.
4. Cada chunk recebe embedding via modelo configurado.
5. Embeddings e trechos são persistidos em PostgreSQL com extensão `vector`.
6. Ao receber uma pergunta, o agente executa:
   - busca semântica via embedding;
   - filtro lexical complementar;
   - recuperação dos chunks mais relevantes;
   - envio do contexto ao modelo para resposta grounded na documentação.

## Principais ferramentas

`agent_core.py` expõe ferramentas que permitem:

- `tool_rag(pergunta: str)`: busca relevante na base vetorial
- `tool_listar_fontes(filtro: str)`: lista fontes indexadas
- `tool_status_base()`: consulta status do índice e sincronização
- `tool_criar_yaml_importacao(nome_arquivo, conteudo_yaml)`: salva YAML em diretório persistente

## Configuração de ambiente

Crie um arquivo `.env` local com as variáveis necessárias para a sua instância. O arquivo real não deve ser versionado.

Exemplo de variáveis (nomes, sem valores reais):

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=
MODELO_CHAT=
MODELO_EMBED=
DB_URI=
DOCS_REPO_URL=
DOCS_REPO_BRANCH=
DOCS_REPO_TOKEN=
DOCS_REPO_USERNAME=
DOCS_LOCAL_DIR=
DOCS_LOCAL_ATTACH_DIR=
NETBOX_IMPORTS_DIR=
TOP_K_RAG_MAIN=
TOP_K_RAG_FALLBACK=
TOP_K_LIST_FONTS=
ENABLE_EXTERNAL_SEARCH=
SERPAPI_API_KEY=
```

Use `app/.env.example` como template seguro para o repositório, sem inserir segredos reais.

## Executando com Docker Compose

Na raiz do projeto, execute:

```bash
docker compose up --build
```

Para executar em background:

```bash
docker compose up -d --build
```

Para verificar serviços:

```bash
docker compose ps
```

Para acompanhar logs:

```bash
docker compose logs -f
```

Para parar tudo:

```bash
docker compose down
```

## Interface gráfica (GUI) e acesso rápido

Além da API compatível com OpenAI, o projeto inclui uma interface gráfica simplificada para uso manual e testes rápidos.

### Opção 1: UI em Docker Compose

A stack do Compose já sobe a interface web principal:

```text
http://localhost:3000
```

Esse frontend envia requisições para o backend do agente em:

```text
http://localhost:18080/v1
```

### Opção 2: interface Gradio local

Pode-se também levantar uma GUI leve diretamente em Python:

```bash
cd app
python app.py
```

A interface Gradio fica em:

```text
http://localhost:7860
```

### Acesso à API

O backend expõe uma interface compatível com OpenAI em:

```text
http://localhost:18080/v1
```

Exemplo de chamada via curl:

```bash
curl -s -X POST "http://localhost:18080/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nara",
    "messages": [
      {"role": "user", "content": "Como definir um Device Type para um switch de 1U?"}
    ]
  }'
```

## Execução local sem Docker

1. Crie o ambiente virtual e instale dependências.
2. Configure `.env` local.
3. Rode o backend:

```bash
cd app
pip install -r requirements.txt
python server.py
```

O serviço ficará disponível em `http://localhost:8000` quando executado diretamente.

## Limitações conhecidas

- O agente depende diretamente da qualidade da documentação indexada.
- Se a documentação não contiver a resposta, a resposta deve indicar ausência de evidência.
- Reindexação é necessária quando a base documental muda significativamente.
- Modelos de embedding locais e online têm trade-offs de latência, custo e ambiente.
- A pesquisa externa é opcional e deve ser habilitada explicitamente.

## Segurança e boas práticas

Nunca versionar:

- `.env`
- tokens e chaves de acesso
- dados sensíveis de produção
- documentação interna privada
- repositórios de código ou dados não públicos

O projeto já inclui `.gitignore` para ignorar arquivos sensíveis e diretórios locais de documentação.

## Perguntas de teste

Use estas perguntas para validar o comportamento do agente:

1. Como cadastrar um Device Type para um switch de 1U no NetBox?
2. Quais campos são obrigatórios para criar um Device segundo a documentação interna?
3. Onde a documentação descreve o fluxo de importação em lote e quais formatos YAML devem ser usados?

Reserve um espaço para registrar a resposta esperada em sua avaliação interna.

## Observações finais

Este projeto foi desenhado para funcionar como base para um assistente interno de conhecimento técnico, com foco em evidência, rastreabilidade e resposta grounded na documentação. Ele é adequado para ambientes organizacionais que precisam padronizar o uso do NetBox e reduzir o risco de interpretação inconsistente da base documental.

Se você quiser expandir o projeto, os próximos passos naturais são:

- melhorar a qualidade do chunking e re-ranking;
- adicionar suporte a embeddings locais;
- criar monitoramento de qualidade de resposta;
- incluir filtros de autorização por usuário ou grupo.


## Escopo do projeto

A NARA foi projetada inicialmente para fornecer assistência especializada ao **NetBox**, porém sua arquitetura permite expansão para outras áreas relacionadas à infraestrutura e automação.

Novos agentes e ferramentas podem ser adicionados para diferentes responsabilidades sem alterar a base principal da aplicação.

A arquitetura busca manter uma separação clara entre:

```text
Código público
      +
Configuração do ambiente
      +
Documentação privada
      +
Base vetorial
```

Isso permite que o projeto seja distribuído publicamente enquanto cada implantação mantém sua própria base documental e suas configurações privadas.

## Aviso

A NARA utiliza modelos de linguagem e, portanto, suas respostas devem ser validadas antes da aplicação em ambientes de produção.

Para informações específicas de uma organização ou implantação, a **documentação disponibilizada ao RAG deve ser considerada a fonte de referência**.