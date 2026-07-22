import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Clock3,
  Copy,
  Database,
  Expand,
  FileImage,
  ImagePlus,
  Languages,
  LoaderCircle,
  Menu,
  MessageSquareText,
  ArrowLeftRight,
  PanelLeftClose,
  Plus,
  RotateCcw,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  AnalysisResponse,
  CandidateInsight,
  HealthResponse,
  PromptDocument,
  QueryResponse,
  RequirementSpec,
  StructuredRequirementSpec,
  WorkflowRun,
} from "./types";

type Stage = "idle" | "understanding" | "review" | "searching" | "analyzing" | "ready" | "composing" | "complete";

interface HistoryItem {
  id: string;
  query: string;
  createdAt: string;
  spec?: RequirementSpec;
  runId?: string;
}

const initialSpec: RequirementSpec = {
  query: "",
  useCase: "",
  targetModel: "GPT Image 2",
  ratio: "1:1",
  textContent: "",
  referenceMode: "auto",
  outputLanguage: "zh",
};

const quickStarts = ["现代电影感游戏画面", "高级产品广告海报", "复古像素角色精灵", "治愈系绘本分镜"];

function App() {
  const [spec, setSpec] = useState<RequirementSpec>(initialSpec);
  const [stage, setStage] = useState<Stage>("idle");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [workflowRun, setWorkflowRun] = useState<WorkflowRun | null>(null);
  const [reviewSpec, setReviewSpec] = useState<StructuredRequirementSpec | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [translations, setTranslations] = useState<Record<string, string>>({});
  const [translating, setTranslating] = useState<Record<string, boolean>>({});
  const [expandedOriginal, setExpandedOriginal] = useState(false);
  const [finalPrompt, setFinalPrompt] = useState("");
  const [finalPromptOriginal, setFinalPromptOriginal] = useState("");
  const [finalPromptLanguage, setFinalPromptLanguage] = useState<"zh" | "en">("zh");
  const [showFinalOriginal, setShowFinalOriginal] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 860);
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth > 1240);
  const [history, setHistory] = useState<HistoryItem[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem("prompt-studio-history") || "[]") as unknown;
      return Array.isArray(parsed) ? parsed as HistoryItem[] : [];
    } catch {
      return [];
    }
  });
  const [referencePreview, setReferencePreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.workflows(8).then((runs) => {
      const saved = runs.map((run) => ({
        id: run.id,
        runId: run.id,
        query: run.requirement_spec.raw_request,
        createdAt: run.created_at,
        spec: workspaceSpecFromWorkflow(run),
      }));
      setHistory((current) => [
        ...current,
        ...saved.filter((item) => !current.some((existing) => existing.runId === item.runId)),
      ].sort((left, right) => historyTimestamp(right.createdAt) - historyTimestamp(left.createdAt)).slice(0, 8));
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    localStorage.setItem("prompt-studio-history", JSON.stringify(history.slice(0, 8)));
  }, [history]);

  useEffect(() => () => {
    if (referencePreview) URL.revokeObjectURL(referencePreview);
  }, [referencePreview]);

  const documents = queryResult?.documents ?? [];
  const selectedDocument = documents.find((item) => item.id === selectedId) ?? documents[0];
  const insightById = useMemo(
    () => new Map((analysis?.cards ?? []).map((item) => [item.prompt_id, item])),
    [analysis],
  );
  const selectedInsight = selectedDocument ? insightById.get(selectedDocument.id) : undefined;

  const activeSteps = useMemo(() => {
    const understood = ["review", "searching", "analyzing", "ready", "composing", "complete"].includes(stage);
    const retrieved = ["ready", "composing", "complete"].includes(stage);
    return [
      { label: "理解需求", done: understood, active: stage === "understanding" || stage === "review" },
      { label: "检索模板", done: retrieved, active: stage === "searching" || stage === "analyzing" },
      { label: "智能编排", done: stage === "complete", active: stage === "composing" },
      { label: "质量检查", done: stage === "complete", active: stage === "complete" },
    ];
  }, [stage]);

  function updateSpec<K extends keyof RequirementSpec>(key: K, value: RequirementSpec[K]) {
    if (stage === "composing") {
      requestIdRef.current += 1;
      if (queryResult) setStage("ready");
    }
    setSpec((current) => ({ ...current, [key]: value }));
    if (stage === "review") {
      setWorkflowRun(null);
      setReviewSpec(null);
      setStage("idle");
    }
    if (finalPrompt) {
      setFinalPrompt("");
      setFinalPromptOriginal("");
      setFinalPromptLanguage(spec.outputLanguage);
      setShowFinalOriginal(false);
      if (queryResult) setStage("ready");
    }
  }

  function selectCandidate(promptId: string) {
    requestIdRef.current += 1;
    setSelectedId(promptId);
    setExpandedOriginal(false);
    setFinalPrompt("");
    setFinalPromptOriginal("");
    setFinalPromptLanguage(spec.outputLanguage);
    setShowFinalOriginal(false);
    setStage("ready");
  }

  async function translatePrompt(promptId: string) {
    if (translations[promptId] || translating[promptId]) return;
    setTranslating((current) => ({ ...current, [promptId]: true }));
    try {
      const result = await api.translate(promptId);
      setTranslations((current) => ({ ...current, [promptId]: result.translation }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "翻译失败，请稍后重试。");
    } finally {
      setTranslating((current) => ({ ...current, [promptId]: false }));
    }
  }

  async function runUnderstanding(input?: string | RequirementSpec) {
    const nextSpec = typeof input === "string" ? { ...spec, query: input } : input ?? spec;
    if (!nextSpec.query.trim()) return;
    const requestId = ++requestIdRef.current;

    setSpec(nextSpec);
    setStage("understanding");
    setError("");
    setWorkflowRun(null);
    setReviewSpec(null);
    setQueryResult(null);
    setAnalysis(null);
    setSelectedId(null);
    setFinalPrompt("");
    setFinalPromptOriginal("");
    setExpandedOriginal(false);

    try {
      const result = await api.understand(nextSpec);
      if (requestId !== requestIdRef.current) return;
      setWorkflowRun(result);
      setReviewSpec(result.requirement_spec);
      setStage("review");
      requestAnimationFrame(() => document.getElementById("requirement-review")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      setStage("idle");
      setError(requestError instanceof Error ? requestError.message : "需求理解失败，请稍后重试。");
    }
  }

  async function confirmAndSearch() {
    if (!workflowRun || !reviewSpec) return;
    const requestId = ++requestIdRef.current;
    setStage("searching");
    setError("");
    try {
      const confirmed = await api.confirmRequirements(workflowRun.id, reviewSpec);
      if (requestId !== requestIdRef.current) return;
      setWorkflowRun(confirmed);
      const nextSpec = { ...spec, query: reviewSpec.raw_request, useCase: reviewSpec.use_case };
      setSpec(nextSpec);
      await runSearch(nextSpec, reviewSpec, confirmed.id);
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      setStage("review");
      setError(requestError instanceof Error ? requestError.message : "确认需求失败，请稍后重试。");
    }
  }

  async function runSearch(
    input?: string | RequirementSpec,
    structured: StructuredRequirementSpec | null = reviewSpec,
    workflowRunId: string | undefined = workflowRun?.id,
  ) {
    const nextSpec = typeof input === "string" ? { ...spec, query: input } : input ?? spec;
    if (!nextSpec.query.trim()) return;
    const requestId = ++requestIdRef.current;

    setSpec(nextSpec);
    setStage("searching");
    setError("");
    setQueryResult(null);
    setAnalysis(null);
    setSelectedId(null);
    setTranslations({});
    setTranslating({});
    setFinalPrompt("");
    setFinalPromptOriginal("");
    setFinalPromptLanguage(nextSpec.outputLanguage);
    setShowFinalOriginal(false);
    setExpandedOriginal(false);

    try {
      const result = await api.query(nextSpec, structured);
      if (requestId !== requestIdRef.current) return;
      setQueryResult(result);
      if (!result.documents.length) {
        setStage("idle");
        setError("没有找到合适的模板，试着补充主体、用途或视觉风格。");
        return;
      }

      const firstId = result.documents[0].id;
      setSelectedId(firstId);
      setStage("analyzing");
      setHistory((current) => [
        { id: crypto.randomUUID(), runId: workflowRunId, query: nextSpec.query.trim(), createdAt: new Date().toISOString(), spec: { ...nextSpec } },
        ...current.filter((item) => item.query !== nextSpec.query.trim()),
      ]);

      const promptIds = result.documents.map((item) => item.id);
      const [analysisResult] = await Promise.allSettled([
        api.analyze(result.question, promptIds),
        result.translation_prompt_id ? translatePrompt(result.translation_prompt_id) : Promise.resolve(),
      ]);
      if (requestId !== requestIdRef.current) return;
      if (analysisResult.status === "fulfilled") setAnalysis(analysisResult.value);
      setStage("ready");
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      setStage("idle");
      setError(requestError instanceof Error ? requestError.message : "服务暂时不可用，请稍后重试。");
    }
  }

  async function restoreHistory(item: HistoryItem) {
    const restoredSpec = item.spec ? { ...initialSpec, ...item.spec } : { ...initialSpec, query: item.query };
    if (!item.runId) {
      await runSearch(restoredSpec, null);
      return;
    }
    const requestId = ++requestIdRef.current;
    setStage("understanding");
    setError("");
    try {
      const run = await api.workflow(item.runId);
      if (requestId !== requestIdRef.current) return;
      setSpec(restoredSpec);
      setWorkflowRun(run);
      setReviewSpec(run.requirement_spec);
      if (run.status === "requirements_ready") {
        setStage("review");
      } else {
        await runSearch(restoredSpec, run.requirement_spec, run.id);
      }
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      setStage("idle");
      setError(requestError instanceof Error ? requestError.message : "历史任务恢复失败。");
    }
  }

  async function deleteHistoryItem(event: React.MouseEvent, item: HistoryItem) {
    event.stopPropagation();
    if (!window.confirm(`确定删除任务“${item.query}”吗？此操作无法撤销。`)) return;
    setError("");
    try {
      if (item.runId) await api.deleteWorkflow(item.runId);
      setHistory((current) => current.filter((entry) => (
        item.runId ? entry.runId !== item.runId : entry.id !== item.id
      )));
      if (item.runId && workflowRun?.id === item.runId) resetWorkspace();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除任务失败，请稍后重试。");
    }
  }

  async function composePrompt() {
    if (!selectedDocument) return;
    const requestId = ++requestIdRef.current;
    setStage("composing");
    setError("");
    try {
      const requirement = [
        spec.query,
        spec.useCase && `用途：${spec.useCase}`,
        spec.targetModel && `目标模型：${spec.targetModel}`,
        spec.ratio && `画幅比例：${spec.ratio}`,
        spec.textContent && `画面文字必须为：${spec.textContent}`,
        selectedInsight?.adaptation_tip && `适配建议：${selectedInsight.adaptation_tip}`,
      ]
        .filter(Boolean)
        .join("；");
      const result = await api.remix(selectedDocument.id, requirement);
      if (requestId !== requestIdRef.current) return;
      setFinalPromptOriginal(result.remixed_prompt);
      let localizedPrompt = result.remixed_prompt;
      let outputLanguage = spec.outputLanguage;
      if (spec.outputLanguage === "zh") {
        try {
          localizedPrompt = (await api.translateText(result.remixed_prompt)).translation;
          if (requestId !== requestIdRef.current) return;
        } catch {
          if (requestId !== requestIdRef.current) return;
          outputLanguage = "en";
          setError("Prompt 已编排完成，但中文翻译暂时失败，当前显示英文原文。");
        }
      }
      setFinalPrompt(localizedPrompt);
      setFinalPromptLanguage(outputLanguage);
      setShowFinalOriginal(false);
      setStage("complete");
      requestAnimationFrame(() => document.getElementById("final-prompt")?.scrollIntoView({ behavior: "smooth" }));
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      setStage("ready");
      setError(requestError instanceof Error ? requestError.message : "编排失败，请稍后重试。");
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("复制失败，请选中文本后手动复制。");
    }
  }

  function resetWorkspace() {
    requestIdRef.current += 1;
    setSpec(initialSpec);
    setStage("idle");
    setWorkflowRun(null);
    setReviewSpec(null);
    setQueryResult(null);
    setAnalysis(null);
    setSelectedId(null);
    setTranslations({});
    setTranslating({});
    setFinalPrompt("");
    setFinalPromptOriginal("");
    setFinalPromptLanguage("zh");
    setShowFinalOriginal(false);
    setError("");
    if (referencePreview) URL.revokeObjectURL(referencePreview);
    setReferencePreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleReference(file?: File) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("请选择图片文件。");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("参考图片不能超过 10 MB。");
      return;
    }
    if (referencePreview) URL.revokeObjectURL(referencePreview);
    setReferencePreview(URL.createObjectURL(file));
    updateSpec("referenceMode", "required");
  }

  function removeReference() {
    if (referencePreview) URL.revokeObjectURL(referencePreview);
    setReferencePreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    updateSpec("referenceMode", "auto");
  }

  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"} ${inspectorOpen ? "" : "inspector-collapsed"}`}>
      <aside className="sidebar" aria-label="任务导航">
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={18} strokeWidth={2.4} /></div>
          <div className="brand-copy">
            <strong>Prompt Studio</strong>
            <span>图像提示词工作台</span>
          </div>
          <button className="icon-button collapse-button" onClick={() => setSidebarOpen(false)} aria-label="收起侧栏">
            <PanelLeftClose size={17} />
          </button>
        </div>

        <button className="new-task-button" onClick={resetWorkspace}>
          <Plus size={17} /> 新建创作任务
        </button>

        <nav className="side-nav">
          <button className="nav-item active"><MessageSquareText size={17} />工作台</button>
          <a className="nav-item" href="/manage"><Database size={17} />知识库管理</a>
        </nav>

        <div className="history-block">
          <div className="section-eyebrow">最近任务</div>
          {history.length ? history.slice(0, 6).map((item) => (
            <div className="history-row" key={item.id}>
              <button className="history-item" onClick={() => void restoreHistory(item)}>
                <span>{item.query}</span>
                <small>{formatRelativeTime(item.createdAt)}</small>
              </button>
              <button className="history-delete" onClick={(event) => void deleteHistoryItem(event, item)} aria-label={`删除任务：${item.query}`} title="删除任务">
                <Trash2 size={13} />
              </button>
            </div>
          )) : <p className="empty-history">你的创作记录会出现在这里。</p>}
        </div>

        <div className="sidebar-footer">
          <div className={`status-dot ${health?.status === "ok" ? "online" : ""}`} />
          <div><strong>{health?.status === "ok" ? "知识库已连接" : "正在连接服务"}</strong><span>{health ? `${health.prompts.toLocaleString()} 条模板` : "请稍候"}</span></div>
        </div>
      </aside>

      {!sidebarOpen && (
        <button className="floating-menu icon-button" onClick={() => setSidebarOpen(true)} aria-label="打开侧栏"><Menu size={18} /></button>
      )}

      <a className="knowledge-manage-fab" href="/manage" aria-label="进入知识库管理中心" title="进入知识库管理中心">
        <Database size={17} />
        <span>知识库管理</span>
      </a>

      <main className="workspace">
        <header className="topbar">
          <a className="frontend-switcher" href="/legacy" title="切换到经典聊天前端">
            <ArrowLeftRight size={13} />
            <span>切换经典前端</span>
          </a>
          <div>
            <div className="topbar-kicker">PROMPT COPILOT</div>
            <h1>把想法，变成可生成的画面</h1>
          </div>
          <div className="topbar-actions">
            <span className="knowledge-pill"><span />混合检索在线</span>
            <button className="icon-button" onClick={() => setInspectorOpen((value) => !value)} aria-label="切换需求面板"><Settings2 size={18} /></button>
          </div>
        </header>

        <section className="stage-strip" aria-label="处理进度">
          {activeSteps.map((step, index) => (
            <div className={`stage-item ${step.done ? "done" : ""} ${step.active ? "active" : ""}`} key={step.label}>
              <span className="stage-index">{step.done && !step.active ? <Check size={13} /> : index + 1}</span>
              <span>{step.label}</span>
              {index < activeSteps.length - 1 && <i />}
            </div>
          ))}
        </section>

        <section className="composer-card">
          <div className="composer-heading">
            <div>
              <span className="section-eyebrow accent">创作需求</span>
              <h2>描述你脑海中的画面</h2>
            </div>
            <span className="keyboard-hint">Ctrl ↵ 发送</span>
          </div>
          <div className="composer-input-wrap">
            <textarea
              value={spec.query}
              onChange={(event) => updateSpec("query", event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void runUnderstanding();
              }}
              placeholder="例如：设计一张现代电影感的科幻游戏主视觉，雨夜霓虹城市，一名孤独的机甲猎人站在画面中央……"
              rows={5}
              maxLength={1000}
            />
            <div className="character-count">{spec.query.length}/1000</div>
          </div>

          <div className="composer-tools">
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={(event) => handleReference(event.target.files?.[0])} />
            <button className={`tool-button ${referencePreview ? "has-file" : ""}`} onClick={() => fileInputRef.current?.click()}>
              {referencePreview ? <Check size={16} /> : <ImagePlus size={16} />}
              {referencePreview ? "已添加参考图" : "添加参考图"}
            </button>
            <label className="inline-select">
              <span>模型</span>
              <select value={spec.targetModel} onChange={(event) => updateSpec("targetModel", event.target.value)}>
                <option>GPT Image 2</option>
                <option>通用图像模型</option>
              </select>
              <ChevronDown size={14} />
            </label>
            <label className="inline-select">
              <span>画幅</span>
              <select value={spec.ratio} onChange={(event) => updateSpec("ratio", event.target.value)}>
                <option>1:1</option><option>16:9</option><option>9:16</option><option>4:3</option><option>3:4</option>
              </select>
              <ChevronDown size={14} />
            </label>
            <button className="primary-button" disabled={!spec.query.trim() || stage === "understanding" || stage === "searching" || stage === "analyzing"} onClick={() => void runUnderstanding()}>
              {stage === "understanding" || stage === "searching" || stage === "analyzing" ? <LoaderCircle className="spin" size={17} /> : <WandSparkles size={17} />}
              {stage === "understanding" ? "正在理解" : stage === "searching" ? "正在检索" : stage === "analyzing" ? "分析候选" : stage === "review" ? "重新理解" : "开始创作"}
            </button>
          </div>

          {referencePreview && (
            <div className="reference-chip">
              <img src={referencePreview} alt="参考图预览" />
              <span><strong>参考图片</strong><small>仅在本机预览，当前不会上传或解析</small></span>
              <button className="icon-button" aria-label="移除参考图片" onClick={removeReference}><X size={15} /></button>
            </div>
          )}

          {!queryResult && stage === "idle" && (
            <div className="quick-starts">
              <span>试试这些</span>
              {quickStarts.map((item) => <button key={item} onClick={() => void runUnderstanding(item)}>{item}<ArrowRight size={13} /></button>)}
            </div>
          )}
        </section>

        {error && <div className="error-banner"><CircleAlert size={17} /><span>{error}</span><button onClick={() => setError("")}><X size={15} /></button></div>}

        {(stage === "understanding" || stage === "searching" || (stage === "analyzing" && !queryResult)) && <LoadingState stage={stage} />}

        {stage === "review" && workflowRun && reviewSpec && (
          <RequirementReview
            run={workflowRun}
            spec={reviewSpec}
            onChange={setReviewSpec}
            onBack={() => setStage("idle")}
            onConfirm={() => void confirmAndSearch()}
          />
        )}

        {queryResult && (
          <div className="results-section" ref={resultsRef}>
            <div className="results-heading">
              <div>
                <span className="section-eyebrow accent">检索结果</span>
                <h2>为你挑出的 {documents.length} 条创作路线</h2>
                <p>{analysis?.summary ?? "正在比较候选模板的构图能力、视觉风格与适配成本……"}</p>
              </div>
              <div className="result-meta"><Search size={15} />向量语义 + BM25</div>
            </div>

            {selectedDocument && (
              <CandidateCard
                document={selectedDocument}
                insight={selectedInsight}
                translated={translations[selectedDocument.id]}
                translating={Boolean(translating[selectedDocument.id])}
                expanded={expandedOriginal}
                onToggleExpanded={() => setExpandedOriginal((value) => !value)}
                onTranslate={() => void translatePrompt(selectedDocument.id)}
                onCompose={() => void composePrompt()}
                composing={stage === "composing"}
              />
            )}

            <div className="candidate-tabs" aria-label="其他候选">
              {documents.filter((item) => item.id !== selectedDocument?.id).map((document) => {
                const insight = insightById.get(document.id);
                return (
                  <button key={document.id} onClick={() => selectCandidate(document.id)}>
                    <span className="candidate-number">0{document.rank}</span>
                    <span><strong>{insight?.personalized_title ?? document.title}</strong><small>{document.category_label} · 匹配 {scorePercent(document.score)}%</small></span>
                    <Expand size={16} />
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {finalPrompt && selectedDocument && (
          <section className="final-card" id="final-prompt">
            <div className="final-card-header">
              <div className="success-mark"><Check size={19} /></div>
              <div><span className="section-eyebrow">编排完成 · {finalPromptLanguage === "zh" ? "中文" : "English"}</span><h2>最终 Prompt</h2></div>
              <button className="secondary-button" onClick={() => void copyText(showFinalOriginal ? finalPromptOriginal : finalPrompt)}>{copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "已复制" : "复制"}</button>
            </div>
            <div className="final-prompt-toolbar">
              <span>{showFinalOriginal ? "编排原文" : finalPromptLanguage === "zh" ? "中文可用版本" : "English ready-to-use version"}</span>
              {finalPromptLanguage === "zh" && finalPromptOriginal && finalPromptOriginal !== finalPrompt && (
                <button className="text-button" onClick={() => setShowFinalOriginal((value) => !value)}><Languages size={15} />{showFinalOriginal ? "查看中文" : "查看编排原文"}</button>
              )}
            </div>
            <div className="final-prompt-body">{showFinalOriginal ? finalPromptOriginal : finalPrompt}</div>
            <div className="quality-grid">
              <QualityItem label="参数完整" detail={`画幅 ${spec.ratio} · ${spec.targetModel}`} />
              <QualityItem label="模板已适配" detail={`来源：${selectedDocument.title}`} />
              <QualityItem label="语言一致" detail={finalPromptLanguage === "zh" ? "最终输出为简体中文" : "最终输出为英文"} />
            </div>
            <div className="final-actions">
              <button className="secondary-button" onClick={() => { setFinalPrompt(""); setStage("ready"); }}><RotateCcw size={16} />重新编排</button>
              <button className="primary-button muted" disabled title="图像生成适配器将在下一阶段接入"><Sparkles size={16} />直接生成图片 <span>即将上线</span></button>
            </div>
          </section>
        )}
      </main>

      <aside className="inspector" aria-label="结构化需求">
        <div className="inspector-header"><div><span className="section-eyebrow">REQUIREMENT SPEC</span><h2>需求结构</h2></div><button className="icon-button" onClick={() => setInspectorOpen(false)}><X size={17} /></button></div>
        <p className="inspector-intro">这些字段会与自然语言需求一起参与检索和提示词编排。</p>

        <div className="field-group">
          <label>用途</label>
          <input value={spec.useCase} onChange={(event) => updateSpec("useCase", event.target.value)} placeholder="如：游戏主视觉、产品海报" />
        </div>
        <div className="field-group two-column">
          <label>目标模型<select value={spec.targetModel} onChange={(event) => updateSpec("targetModel", event.target.value)}><option>GPT Image 2</option><option>通用图像模型</option></select></label>
          <label>画幅比例<select value={spec.ratio} onChange={(event) => updateSpec("ratio", event.target.value)}><option>1:1</option><option>16:9</option><option>9:16</option><option>4:3</option><option>3:4</option></select></label>
        </div>
        <div className="field-group">
          <label>画面文字</label>
          <input value={spec.textContent} onChange={(event) => updateSpec("textContent", event.target.value)} placeholder="没有文字可留空" />
        </div>
        <div className="field-group">
          <label>最终 Prompt 语言</label>
          <div className="segmented-control language-control">
            <button className={spec.outputLanguage === "zh" ? "active" : ""} onClick={() => updateSpec("outputLanguage", "zh")}>中文</button>
            <button className={spec.outputLanguage === "en" ? "active" : ""} onClick={() => updateSpec("outputLanguage", "en")}>English</button>
          </div>
        </div>
        <div className="field-group">
          <label>参考图策略</label>
          <div className="segmented-control">
            {(["auto", "required", "none"] as const).map((value) => <button className={spec.referenceMode === value ? "active" : ""} key={value} onClick={() => updateSpec("referenceMode", value)}>{value === "auto" ? "自动" : value === "required" ? "需要" : "不用"}</button>)}
          </div>
        </div>

        <div className="inspector-divider" />
        <div className="spec-preview">
          <div className="spec-preview-title"><FileImage size={16} /><strong>实时规格</strong></div>
          <SpecRow label="语言" value="中文界面 / 模型适配" />
          <SpecRow label="最终输出" value={spec.outputLanguage === "zh" ? "简体中文" : "English"} />
          <SpecRow label="候选数" value={queryResult ? `${queryResult.documents.length} 个` : "3 个"} />
          <SpecRow label="参考图片" value={spec.referenceMode === "required" ? "需要" : spec.referenceMode === "none" ? "不使用" : "自动判断"} />
          <SpecRow label="状态" value={stageLabel(stage)} highlighted={stage !== "idle"} />
        </div>
        <div className="inspector-note"><Sparkles size={15} /><span>当前版本已接入需求结构化确认、知识库检索、候选分析、翻译和 Prompt 重写。</span></div>
      </aside>
    </div>
  );
}

function CandidateCard({
  document,
  insight,
  translated,
  translating,
  expanded,
  composing,
  onToggleExpanded,
  onTranslate,
  onCompose,
}: {
  document: PromptDocument;
  insight?: CandidateInsight;
  translated?: string;
  translating: boolean;
  expanded: boolean;
  composing: boolean;
  onToggleExpanded: () => void;
  onTranslate: () => void;
  onCompose: () => void;
}) {
  return (
    <article className="candidate-card main-candidate">
      <div className="candidate-accent" />
      <div className="candidate-visual">
        {document.preview_image ? <img src={document.preview_image} alt="" /> : <div className="visual-placeholder"><Sparkles size={24} /><span>Prompt</span></div>}
        <span className="rank-badge">当前路线</span>
      </div>
      <div className="candidate-content">
        <div className="candidate-title-row">
          <div><div className="candidate-kicker"><span>0{document.rank}</span>{document.category_label}</div><h3>{insight?.personalized_title ?? document.title}</h3></div>
          <div className="score-ring" style={{ "--score": `${scorePercent(document.score) * 3.6}deg` } as React.CSSProperties}><span>{scorePercent(document.score)}</span><small>匹配</small></div>
        </div>

        <p className="match-reason">{insight?.match_reason ?? "正在分析这条模板与你的需求有哪些具体契合点……"}</p>

        <div className="insight-grid">
          <div><span>最适合</span><p>{insight?.best_for ?? (document.description || "作为当前创作需求的基础视觉模板。")}</p></div>
          <div><span>建议调整</span><p>{insight?.adaptation_tip ?? "替换主体、场景与画幅参数，让模板更贴合你的描述。"}</p></div>
        </div>

        {translated && <div className="translated-preview"><div><Languages size={15} /><strong>中文提示词预览</strong></div><p>{translated}</p></div>}
        {translating && <div className="translation-loading"><LoaderCircle className="spin" size={15} />正在翻译首选提示词，你可以继续浏览候选……</div>}

        {expanded && (
          <div className="original-prompt" data-testid="expanded-original">
            <div className="original-prompt-head"><span>完整原始提示词</span><small>{document.prompt.length.toLocaleString()} 字符</small></div>
            <p>{document.prompt}</p>
          </div>
        )}

        <div className="candidate-actions">
          <button className="text-button" onClick={onToggleExpanded}>{expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}{expanded ? "收起完整原文" : "展开完整原文"}</button>
          {!translated && <button className="text-button" disabled={translating} onClick={onTranslate}><Languages size={15} />翻译为中文</button>}
          <button className="primary-button" disabled={composing} onClick={onCompose}>{composing ? <LoaderCircle className="spin" size={16} /> : <WandSparkles size={16} />}{composing ? "正在编排" : "采用并智能编排"}</button>
        </div>
      </div>
    </article>
  );
}

function RequirementReview({
  run,
  spec,
  onChange,
  onBack,
  onConfirm,
}: {
  run: WorkflowRun;
  spec: StructuredRequirementSpec;
  onChange: (spec: StructuredRequirementSpec) => void;
  onBack: () => void;
  onConfirm: () => void;
}) {
  function updateRoot<K extends keyof StructuredRequirementSpec>(key: K, value: StructuredRequirementSpec[K]) {
    onChange({ ...spec, [key]: value });
  }

  function updateSubject(key: "description" | "action", value: string) {
    onChange({ ...spec, subject: { ...spec.subject, [key]: value } });
  }

  function updateCamera(key: "shot" | "lens", value: string) {
    onChange({ ...spec, camera: { ...spec.camera, [key]: value } });
  }

  function toList(value: string) {
    return value.split(/[，、,]/).map((item) => item.trim()).filter(Boolean);
  }

  return (
    <section className="requirement-review" id="requirement-review">
      <div className="review-header">
        <div className="review-icon"><Sparkles size={19} /></div>
        <div>
          <span className="section-eyebrow accent">需求理解待确认</span>
          <h2>这是我对创作需求的理解</h2>
          <p>确认或修改下面的结构后，系统才会用它构建检索查询。</p>
        </div>
        <div className="review-confidence"><strong>{Math.round(spec.confidence * 100)}%</strong><span>理解置信度</span></div>
      </div>

      <div className="review-meta">
        <span><Check size={13} />{run.generated ? "模型结构化" : "规则结构化"}</span>
        {run.cached && <span><Clock3 size={13} />已复用缓存</span>}
        <span>Schema v{run.schema_version}</span>
      </div>

      <div className="review-form-grid">
        <label><span>用途</span><input value={spec.use_case} onChange={(event) => updateRoot("use_case", event.target.value)} placeholder="如：游戏主视觉" /></label>
        <label className="wide"><span>主体</span><input value={spec.subject.description} onChange={(event) => updateSubject("description", event.target.value)} placeholder="画面的核心主体" /></label>
        <label><span>动作</span><input value={spec.subject.action} onChange={(event) => updateSubject("action", event.target.value)} placeholder="主体正在做什么" /></label>
        <label className="wide"><span>环境</span><input value={spec.environment} onChange={(event) => updateRoot("environment", event.target.value)} placeholder="场景、地点、天气和时间" /></label>
        <label className="wide"><span>风格</span><input value={spec.style.join("、")} onChange={(event) => updateRoot("style", toList(event.target.value))} placeholder="用顿号分隔多个风格" /></label>
        <label><span>构图</span><input value={spec.composition} onChange={(event) => updateRoot("composition", event.target.value)} placeholder="如：中心构图" /></label>
        <label><span>景别</span><input value={spec.camera.shot} onChange={(event) => updateCamera("shot", event.target.value)} placeholder="如：wide shot" /></label>
        <label><span>镜头</span><input value={spec.camera.lens} onChange={(event) => updateCamera("lens", event.target.value)} placeholder="如：35mm" /></label>
        <label className="wide"><span>光线</span><input value={spec.lighting.join("、")} onChange={(event) => updateRoot("lighting", toList(event.target.value))} placeholder="用顿号分隔" /></label>
        <label><span>配色</span><input value={spec.palette.join("、")} onChange={(event) => updateRoot("palette", toList(event.target.value))} placeholder="主色和辅助色" /></label>
        <label className="wide"><span>禁止项</span><input value={spec.negative_constraints.join("、")} onChange={(event) => updateRoot("negative_constraints", toList(event.target.value))} placeholder="不希望画面出现的内容" /></label>
      </div>

      {(spec.assumptions.length > 0 || spec.missing_fields.length > 0) && (
        <div className="review-diagnostics">
          {spec.assumptions.length > 0 && <div><span>系统假设</span><div>{spec.assumptions.map((item) => <i key={item}>{item}</i>)}</div></div>}
          {spec.missing_fields.length > 0 && <div><span>尚未明确</span><div>{spec.missing_fields.map((item) => <i className="missing" key={item}>{requirementFieldLabel(item)}</i>)}</div></div>}
        </div>
      )}

      <div className="review-output-summary">
        <span>输出规格</span>
        <strong>{spec.output.model}</strong>
        <i>{spec.output.ratio}</i><i>{spec.output.size}</i><i>{spec.output.quality}</i><i>{spec.output.prompt_language === "zh" ? "中文 Prompt" : "English Prompt"}</i>
      </div>

      <div className="review-actions">
        <button className="secondary-button" onClick={onBack}>修改原始需求</button>
        <button className="primary-button" onClick={onConfirm}><Search size={16} />确认并检索模板</button>
      </div>
    </section>
  );
}

function LoadingState({ stage }: { stage: Stage }) {
  const content = stage === "understanding"
    ? ["正在理解你的创作意图", "拆解主体、用途、风格、构图、镜头和限制条件"]
    : stage === "searching"
      ? ["正在构建混合检索查询", "把已确认的结构化需求转换为语义和关键词查询"]
      : ["正在对候选模板重排序", "比较构图能力、风格一致性和修改成本"];
  return <div className="loading-card"><div className="orbital-loader"><span /><i /><b /></div><div><strong>{content[0]}</strong><p>{content[1]}</p></div></div>;
}

function SpecRow({ label, value, highlighted = false }: { label: string; value: string; highlighted?: boolean }) {
  return <div className="spec-row"><span>{label}</span><strong className={highlighted ? "highlighted" : ""}>{value}</strong></div>;
}

function QualityItem({ label, detail }: { label: string; detail: string }) {
  return <div className="quality-item"><span><Check size={13} /></span><div><strong>{label}</strong><small>{detail}</small></div></div>;
}

function scorePercent(score: number) {
  return Math.max(1, Math.min(100, Math.round(score * 100)));
}

function stageLabel(stage: Stage) {
  const labels: Record<Stage, string> = { idle: "等待输入", understanding: "理解需求", review: "等待确认", searching: "检索模板", analyzing: "分析候选", ready: "候选就绪", composing: "智能编排", complete: "质量检查完成" };
  return labels[stage];
}

function requirementFieldLabel(field: string) {
  const labels: Record<string, string> = {
    use_case: "用途",
    "subject.description": "主体",
    "subject.action": "主体动作",
    environment: "环境",
    composition: "构图",
    camera: "镜头设置",
    palette: "配色",
    lighting: "光线",
    references: "参考图片内容",
  };
  return labels[field] ?? field;
}

function formatRelativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "最近";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function historyTimestamp(value: string) {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function workspaceSpecFromWorkflow(run: WorkflowRun): RequirementSpec {
  const structured = run.requirement_spec;
  return {
    query: structured.raw_request,
    useCase: structured.use_case,
    targetModel: structured.output.model === "gpt-image-2" ? "GPT Image 2" : structured.output.model,
    ratio: structured.output.ratio,
    textContent: structured.text.content,
    referenceMode: structured.references.length ? "required" : "auto",
    outputLanguage: structured.output.prompt_language,
  };
}

export default App;
