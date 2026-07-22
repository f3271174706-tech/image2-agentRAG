# Prompt RAG

面向 GPT Image 提示词知识库的专用混合检索系统。它直接读取
`../knowledge-base/normalized/prompts.jsonl`，不重复导入分类副本、增量文件或旧版数据。

## 设计原则

- 一条提示词就是一个检索单元，完整原文永不被固定长度切碎。
- SQLite 保存原文、元数据与 FTS5 索引；12,569 条数据不需要 Milvus/MySQL 集群。
- 关键词召回与多语种向量召回使用 RRF 融合，避免直接比较不可比的分数。
- 图片 URL、分类、动态参数和参考图要求均作为结构化字段返回。
- LLM 只负责解释推荐或重混提示词，不参与基础检索，未配置时系统仍可运行。
- 检索结果先返回，再异步生成候选差异分析；模型输出经过结构化校验后才进入前端卡片。

## 环境

项目使用独立 `.venv`：

```powershell
cd D:\mycode\image2\prompt-rag
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
Copy-Item .env.example .env
```

## 快速开始

只构建 FTS5 索引：

```powershell
.\.venv\Scripts\prompt-rag.exe ingest
.\.venv\Scripts\prompt-rag.exe search "cyberpunk avatar" --top-k 3
.\.venv\Scripts\prompt-rag.exe serve
```

服务启动后可打开：

- `http://127.0.0.1:8010/v2/`：新版 Prompt Studio 工作台。
- `http://127.0.0.1:8010/`：原临时聊天页面。
- `http://127.0.0.1:8010/legacy`：原临时页面的固定别名。
- `http://127.0.0.1:8010/docs`：API 文档。

新版前端使用 React、TypeScript 和 Vite，生产构建由 FastAPI 挂载：

```powershell
cd D:\mycode\image2\prompt-rag\web-v2
npm install
npm run build
cd ..
.\.venv\Scripts\prompt-rag.exe serve
```

前端开发时运行 `npm run dev`，Vite 会把 `/api` 请求代理到 8010 端口。

当前仍会在 `http://127.0.0.1:8010/` 临时挂载旧 LangChain 聊天页面，并通过
`/api/query` 兼容层连接 Prompt RAG。该页面只保证文本检索可用；上传、图片分析、
联网搜索和深度思考仍属于旧系统能力，不在此兼容层中。

页面右上角可切换“中文 / English”。默认使用中文；中文模式先立即返回检索结果，
再通过小米 MiMo 2.5 异步翻译首选英文提示词，翻译完成后自动填入页面并缓存到
SQLite。每条引用来源也有“翻译成中文 / 查看原文”按钮。引用区保留知识库原文，
便于核对；已是中文的提示词不会重复翻译。

中文页面会把前三个候选渲染成独立卡片。每张卡包含匹配理由、最佳使用场景、
个性化调整建议、完整原始提示词和按需中文翻译。智能分析与译文分别缓存，重复查询
无需再次等待模型生成。

翻译默认从 `.env` 指定的 MiMo 配置文件读取 OpenAI 兼容接口配置。API 密钥只保存在
本地配置中，不应提交到版本库或写进前端代码。

## 多语种向量检索

中文需求检索英文提示词时，建议启用多语种向量。轻量本地方案：

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[local,dev]"
```

然后在 `.env` 中设置：

```dotenv
PROMPT_RAG_EMBEDDING_PROVIDER=sentence-transformers
PROMPT_RAG_EMBEDDING_MODEL=intfloat/multilingual-e5-small
PROMPT_RAG_MODEL_CACHE_DIR=./data/models
```

执行：

```powershell
.\.venv\Scripts\prompt-rag.exe ingest --with-embeddings
```

也可以把 `PROMPT_RAG_EMBEDDING_PROVIDER` 设置为 `openai-compatible`，配置兼容
OpenAI `/v1/embeddings` 的地址、密钥和模型。

阿里云百炼推荐配置：

```dotenv
PROMPT_RAG_EMBEDDING_PROVIDER=openai-compatible
PROMPT_RAG_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
PROMPT_RAG_EMBEDDING_MODEL=text-embedding-v4
PROMPT_RAG_EMBEDDING_DIMENSIONS=1024
PROMPT_RAG_EMBEDDING_BATCH_SIZE=10
```

密钥使用 `PROMPT_RAG_EMBEDDING_API_KEY` 或进程环境变量 `DASHSCOPE_API_KEY` 提供，
不要写入源码。向量入库前和查询时都会归一化，点积即余弦相似度。

## API

- `GET /api/health`：健康状态和索引能力。
- `GET /api/stats`：提示词、分类与向量数量。
- `GET /api/prompts/{id}`：按稳定 ID 读取完整提示词。
- `POST /api/workflow-runs`：理解自然语言需求，创建可持久化的 RequirementSpec 草稿。
- `GET /api/workflow-runs/{id}`：读取工作流记录，服务重启后仍可恢复。
- `PUT /api/workflow-runs/{id}/requirements`：保存用户确认或修改后的 RequirementSpec。
- `POST /api/search`：混合检索，支持分类和参考图过滤。
- `POST /api/translate`：按提示词 ID 翻译为中文，自动复用 SQLite 缓存。
- `POST /api/translate-text`：翻译重写后的 Prompt，同样复用受控翻译缓存。
- `POST /api/analyze-results`：结合用户需求分析至多三个候选，返回安全的结构化卡片数据。
- `POST /api/recommend`：检索并可选调用 LLM 解释推荐理由。
- `POST /api/remix`：基于选中的完整模板生成定制英文提示词。

新版工作台可在需求结构面板中选择最终 Prompt 输出为中文或英文。中文模式会先完成
模板重写，再翻译最终结果，同时保留“查看编排原文”入口；翻译暂时失败时会明确回退
到英文原文，不会丢失已经完成的编排结果。

新任务会先调用需求理解接口，展示主体、动作、环境、风格、构图、镜头、光线、配色、
系统假设和缺失字段。用户确认后，结构化字段才会参与混合检索。理解结果和确认状态保存在
SQLite `workflow_runs` 中；相同输入的模型解析会复用 `requirement_analyses` 缓存。

示例：

```json
{
  "query": "做一个霓虹赛博朋克头像",
  "top_k": 3,
  "categories": ["profile-avatar"],
  "need_reference_images": false,
  "use_dense": true
}
```

## 与旧项目的取舍

此项目没有复制 `D:\mycode\LangChain` 的通用文档解析、多 Agent、网页搜索和会话记忆。
它保留混合召回与重排思想，但用单一可安装包、依赖注入、SQLite 和可测试服务边界实现，
避免两套运行时、全局组件、`sys.path` 注入以及 Milvus/BM25/MySQL 三份状态不一致的问题。
