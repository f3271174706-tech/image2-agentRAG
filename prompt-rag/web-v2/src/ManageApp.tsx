import {
  ArrowLeft,
  BookOpenText,
  Check,
  ChevronLeft,
  ChevronRight,
  Database,
  Languages,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Pencil,
  Plus,
  Search,
  Sparkles,
  ToggleLeft,
  ToggleRight,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { adminApi } from "./api";
import type { AdminPrompt, AdminPromptInput, AdminPromptPage, AdminStats } from "./types";
import "./manage.css";

const TOKEN_KEY = "prompt-rag-admin-token";
const PAGE_SIZE = 30;
const categoryLabels: Record<string, string> = {
  "profile-avatar": "头像 / 肖像",
  "social-media-post": "社交媒体内容",
  "product-marketing": "产品营销",
  "poster-flyer": "海报 / 传单",
  "infographic-edu-visual": "信息图 / 教育视觉",
  "ecommerce-main-image": "电商主图",
  "game-asset": "游戏素材",
  "comic-storyboard": "漫画 / 分镜",
  "youtube-thumbnail": "YouTube 缩略图",
  "app-web-design": "应用 / 网页设计",
  others: "其他",
};

const emptyPrompt: AdminPromptInput = {
  title: "",
  description: "",
  prompt: "",
  category: "others",
  categories: ["others"],
  preview_image: "",
  source_media: [],
  need_reference_images: false,
  arguments: [],
  language: "zh",
  status: "active",
};

function toInput(document: AdminPrompt): AdminPromptInput {
  return {
    id: document.id,
    title: document.title,
    description: document.description,
    prompt: document.prompt,
    category: document.category,
    categories: document.categories,
    preview_image: document.preview_image,
    source_media: document.source_media,
    need_reference_images: document.need_reference_images,
    arguments: document.arguments,
    language: document.language,
    status: document.status,
  };
}

function automaticTitle(prompt: string) {
  const compact = prompt.replace(/\s+/g, " ").trim();
  const firstSentence = compact.split(/[。！？.!?]/, 1)[0] || compact;
  return firstSentence.slice(0, 48) || "未命名提示词";
}

function detectLanguage(prompt: string) {
  const compact = prompt.replace(/\s/g, "");
  if (!compact) return "zh";
  const chineseCount = (compact.match(/[\u3400-\u9fff]/g) ?? []).length;
  const ratio = chineseCount / compact.length;
  if (ratio === 0) return "en";
  if (ratio < 0.35) return "mixed";
  return "zh";
}

function ManageApp() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");
  const [checking, setChecking] = useState(Boolean(token));
  const [password, setPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [pageData, setPageData] = useState<AdminPromptPage | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"active" | "inactive" | "all">("all");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState<AdminPrompt | null | undefined>(undefined);
  const [form, setForm] = useState<AdminPromptInput>(emptyPrompt);
  const [categoryText, setCategoryText] = useState("others");
  const [languageOverride, setLanguageOverride] = useState(false);
  const [saving, setSaving] = useState(false);

  const totalPages = Math.max(1, Math.ceil((pageData?.total ?? 0) / PAGE_SIZE));
  const categoryOptions = useMemo(
    () => Object.keys(stats?.categories ?? {}).sort((left, right) => left.localeCompare(right)),
    [stats],
  );

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }
    adminApi.session(token)
      .then(() => void loadData(token, 1, "", "all"))
      .catch(() => logout())
      .finally(() => setChecking(false));
  }, []);

  async function loadData(
    activeToken = token,
    nextPage = page,
    nextQuery = query,
    nextStatus = status,
  ) {
    if (!activeToken) return;
    setLoading(true);
    setError("");
    try {
      const [nextStats, prompts] = await Promise.all([
        adminApi.stats(activeToken),
        adminApi.prompts(activeToken, {
          query: nextQuery,
          status: nextStatus,
          page: nextPage,
          pageSize: PAGE_SIZE,
        }),
      ]);
      setStats(nextStats);
      setPageData(prompts);
      setPage(nextPage);
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "管理数据加载失败";
      if (message.includes("401") || message.includes("登录已失效")) logout();
      else setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    if (!password.trim()) return;
    setLoggingIn(true);
    setError("");
    try {
      const result = await adminApi.login(password);
      sessionStorage.setItem(TOKEN_KEY, result.token);
      setToken(result.token);
      setPassword("");
      await loadData(result.token, 1, "", "all");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "登录失败");
    } finally {
      setLoggingIn(false);
    }
  }

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setStats(null);
    setPageData(null);
    setEditing(undefined);
  }

  function openCreate() {
    const defaultCategory = categoryOptions.includes("others") ? "others" : categoryOptions[0] ?? "others";
    setForm({ ...emptyPrompt, category: defaultCategory, categories: [defaultCategory] });
    setCategoryText(defaultCategory);
    setLanguageOverride(false);
    setEditing(null);
    setError("");
  }

  function openEdit(document: AdminPrompt) {
    const next = toInput(document);
    setForm(next);
    setCategoryText(next.categories.join("、"));
    setLanguageOverride(true);
    setEditing(document);
    setError("");
  }

  async function savePrompt(event: FormEvent) {
    event.preventDefault();
    if (!form.prompt.trim() || !form.category.trim()) return;
    const categories = categoryText.split(/[，、,]/).map((item) => item.trim()).filter(Boolean);
    const payload = {
      ...form,
      title: form.title.trim() || automaticTitle(form.prompt),
      language: languageOverride ? form.language : detectLanguage(form.prompt),
      categories: categories.length ? categories : [form.category],
    };
    setSaving(true);
    setError("");
    try {
      const result = editing
        ? await adminApi.updatePrompt(token, editing.id, payload)
        : await adminApi.createPrompt(token, payload);
      const embeddingMessage = result.embedding_status === "updated"
        ? "向量已同步"
        : result.embedding_status === "pending"
          ? "内容已保存，向量服务暂时不可用"
          : result.embedding_status === "not_required"
            ? "已停用并移出检索"
            : "内容已保存";
      setNotice(`${result.created ? "新增" : "更新"}成功 · ${embeddingMessage}`);
      setEditing(undefined);
      await loadData(token, page, query, status);
      window.setTimeout(() => setNotice(""), 3200);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function togglePrompt(document: AdminPrompt) {
    const nextStatus = document.status === "active" ? "inactive" : "active";
    setError("");
    try {
      const result = await adminApi.updatePrompt(token, document.id, {
        ...toInput(document),
        status: nextStatus,
      });
      setNotice(nextStatus === "active" ? "提示词已重新启用" : "提示词已停用");
      await loadData(token, page, query, status);
      if (result.embedding_status === "pending") setNotice("已启用，但向量将在服务恢复后补充");
      window.setTimeout(() => setNotice(""), 3200);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "状态更新失败");
    }
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    void loadData(token, 1, query, status);
  }

  if (checking) {
    return <div className="manage-centered"><LoaderCircle className="spin" size={24} /><span>正在验证管理会话</span></div>;
  }

  if (!token) {
    return (
      <main className="manage-login-shell">
        <a className="manage-back-link" href="/v2/"><ArrowLeft size={15} />返回创作工作台</a>
        <section className="manage-login-card">
          <div className="manage-login-mark"><LockKeyhole size={23} /></div>
          <span className="manage-eyebrow">PRIVATE CONSOLE</span>
          <h1>知识库管理中心</h1>
          <p>管理入口独立鉴权。登录后可查看、添加、编辑和停用提示词。</p>
          <form onSubmit={login}>
            <label><span>管理员密码</span><input autoFocus type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="输入服务器配置的管理密码" /></label>
            {error && <div className="manage-error">{error}</div>}
            <button className="manage-primary" disabled={loggingIn || !password.trim()}>{loggingIn ? <LoaderCircle className="spin" size={16} /> : <LockKeyhole size={16} />}{loggingIn ? "正在登录" : "进入管理中心"}</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <div className="manage-shell">
      <header className="manage-header">
        <div className="manage-brand"><span><Database size={18} /></span><div><strong>知识库管理中心</strong><small>Prompt Studio · Private Console</small></div></div>
        <div className="manage-header-actions"><a href="/v2/"><ArrowLeft size={14} />创作工作台</a><button onClick={logout}><LogOut size={14} />退出</button></div>
      </header>

      <main className="manage-content">
        <section className="manage-hero">
          <div><span className="manage-eyebrow">KNOWLEDGE OPERATIONS</span><h1>让知识库保持清晰、可控、可检索</h1><p>第一版支持单条维护；所有变更会即时更新关键词索引和 DashScope 向量。</p></div>
          <button className="manage-primary compact" onClick={openCreate}><Plus size={16} />新增提示词</button>
        </section>

        <section className="manage-stats-grid">
          <StatCard icon={<BookOpenText size={17} />} label="全部提示词" value={stats?.prompts ?? 0} detail={`${stats?.active_prompts ?? 0} 条正在检索`} />
          <StatCard icon={<Sparkles size={17} />} label="向量覆盖" value={stats?.current_embeddings ?? 0} detail={`${stats?.active_prompts ? Math.round(((stats?.current_embeddings ?? 0) / stats.active_prompts) * 100) : 0}% 已完成`} />
          <StatCard icon={<Languages size={17} />} label="语言" value={Object.keys(stats?.languages ?? {}).length} detail={Object.entries(stats?.languages ?? {}).slice(0, 2).map(([key, value]) => `${key} ${value}`).join(" · ") || "暂无"} />
          <StatCard icon={<Database size={17} />} label="数据库" value={formatBytes(stats?.db_bytes ?? 0)} detail={`${Object.keys(stats?.categories ?? {}).length} 个分类`} textValue />
        </section>

        {notice && <div className="manage-notice"><Check size={15} />{notice}</div>}
        {error && <div className="manage-error banner">{error}<button onClick={() => setError("")}><X size={14} /></button></div>}

        <section className="manage-panel">
          <div className="manage-panel-head">
            <div><span className="manage-eyebrow">PROMPTS</span><h2>提示词内容</h2></div>
            <form className="manage-filters" onSubmit={submitSearch}>
              <div className="manage-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、ID、分类或正文" /></div>
              <select value={status} onChange={(event) => { const next = event.target.value as typeof status; setStatus(next); void loadData(token, 1, query, next); }}><option value="all">全部状态</option><option value="active">正在使用</option><option value="inactive">已停用</option></select>
              <button type="submit">搜索</button>
            </form>
          </div>

          <div className="manage-table-wrap">
            <table className="manage-table">
              <thead><tr><th>提示词</th><th>分类</th><th>语言</th><th>状态</th><th aria-label="操作" /></tr></thead>
              <tbody>
                {pageData?.items.map((document) => (
                  <tr key={document.id}>
                    <td><button className="prompt-title" onClick={() => openEdit(document)}><strong>{document.title}</strong><small>{document.id}</small></button></td>
                    <td><span className="category-chip">{document.category}</span></td>
                    <td>{document.language.toUpperCase()}</td>
                    <td><span className={`status-chip ${document.status}`}>{document.status === "active" ? "正在使用" : "已停用"}</span></td>
                    <td><div className="row-actions"><button title="编辑" onClick={() => openEdit(document)}><Pencil size={14} /></button><button title={document.status === "active" ? "停用" : "启用"} onClick={() => void togglePrompt(document)}>{document.status === "active" ? <ToggleRight size={17} /> : <ToggleLeft size={17} />}</button></div></td>
                  </tr>
                ))}
                {!loading && !pageData?.items.length && <tr><td className="manage-empty" colSpan={5}>没有找到符合条件的提示词。</td></tr>}
              </tbody>
            </table>
            {loading && <div className="manage-loading"><LoaderCircle className="spin" size={18} />正在读取知识库</div>}
          </div>

          <div className="manage-pagination"><span>共 {(pageData?.total ?? 0).toLocaleString()} 条</span><div><button disabled={page <= 1 || loading} onClick={() => void loadData(token, page - 1, query, status)}><ChevronLeft size={14} /></button><span>{page} / {totalPages}</span><button disabled={page >= totalPages || loading} onClick={() => void loadData(token, page + 1, query, status)}><ChevronRight size={14} /></button></div></div>
        </section>
      </main>

      {editing !== undefined && (
        <div className="manage-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(undefined); }}>
          <section className="manage-modal" role="dialog" aria-modal="true" aria-label={editing ? "编辑提示词" : "新增提示词"}>
            <div className="manage-modal-head"><div><span className="manage-eyebrow">{editing ? "EDIT PROMPT" : "NEW PROMPT"}</span><h2>{editing ? "编辑提示词" : "新增提示词"}</h2></div><button onClick={() => setEditing(undefined)}><X size={17} /></button></div>
            <form onSubmit={savePrompt}>
              <div className="manage-simple-tip"><Sparkles size={15} /><span>粘贴完整提示词并选择分类就能保存；标题和语言可以自动生成。</span></div>
              <label><span>完整提示词</span><textarea autoFocus={!editing} className="prompt-editor" required rows={12} value={form.prompt} onChange={(event) => setForm({ ...form, prompt: event.target.value })} placeholder="在这里粘贴完整提示词……" /></label>
              <div className="manage-form-grid simple-fields">
                <label><span>分类</span><select required value={form.category} onChange={(event) => { const category = event.target.value; setForm({ ...form, category }); setCategoryText(category); }}>{categoryOptions.map((item) => <option value={item} key={item}>{categoryLabels[item] ?? item}</option>)}</select></label>
                <label><span>标题（可选）</span><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="留空将从提示词自动提取" /></label>
              </div>
              <div className="manage-check-row simple-check"><label><input type="checkbox" checked={form.need_reference_images} onChange={(event) => setForm({ ...form, need_reference_images: event.target.checked })} />生成时需要参考图片</label></div>
              <details className="manage-advanced">
                <summary>高级设置（可选）</summary>
                <div className="manage-advanced-fields">
                  {editing && <label><span>提示词 ID</span><input disabled value={editing.id} /></label>}
                  <label><span>简介</span><textarea rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="适用场景或补充说明" /></label>
                  <div className="manage-form-grid">
                    <label><span>语言（默认自动识别）</span><select value={form.language} onChange={(event) => { setLanguageOverride(true); setForm({ ...form, language: event.target.value }); }}><option value="zh">中文</option><option value="en">English</option><option value="mixed">混合</option></select></label>
                    <label><span>状态</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as "active" | "inactive" })}><option value="active">保存后启用</option><option value="inactive">暂不启用</option></select></label>
                    <label className="wide"><span>额外分类（顿号分隔）</span><input value={categoryText} onChange={(event) => setCategoryText(event.target.value)} placeholder="game-asset、comic-storyboard" /></label>
                    <label className="wide"><span>预览图 URL</span><input value={form.preview_image} onChange={(event) => setForm({ ...form, preview_image: event.target.value })} placeholder="https://..." /></label>
                  </div>
                </div>
              </details>
              <div className="manage-modal-actions"><button type="button" onClick={() => setEditing(undefined)}>取消</button><button className="manage-primary" disabled={saving || !form.prompt.trim() || !form.category.trim()}>{saving ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}{saving ? "保存并生成向量" : "保存到知识库"}</button></div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

function StatCard({ icon, label, value, detail, textValue = false }: { icon: React.ReactNode; label: string; value: number | string; detail: string; textValue?: boolean }) {
  return <article className="manage-stat"><div className="manage-stat-icon">{icon}</div><div><span>{label}</span><strong className={textValue ? "text-value" : ""}>{typeof value === "number" ? value.toLocaleString() : value}</strong><small>{detail}</small></div></article>;
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(0, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export default ManageApp;
