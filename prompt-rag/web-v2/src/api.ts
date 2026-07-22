import type {
  AnalysisResponse,
  HealthResponse,
  QueryResponse,
  RemixResponse,
  RequirementSpec,
  StructuredRequirementSpec,
  WorkflowRun,
  AdminPromptInput,
  AdminPromptPage,
  AdminSaveResponse,
  AdminStats,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Keep the HTTP fallback when an upstream returns a non-JSON body.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),

  understand: (spec: RequirementSpec) =>
    request<WorkflowRun>("/api/workflow-runs", {
      method: "POST",
      body: JSON.stringify({
        raw_request: spec.query,
        use_case: spec.useCase,
        target_model: spec.targetModel,
        ratio: spec.ratio,
        text_content: spec.textContent,
        reference_mode: spec.referenceMode,
        output_language: spec.outputLanguage,
      }),
    }),

  workflow: (runId: string) => request<WorkflowRun>(`/api/workflow-runs/${runId}`),

  workflows: (limit = 20) => request<WorkflowRun[]>(`/api/workflow-runs?limit=${limit}`),

  deleteWorkflow: (runId: string) =>
    request<void>(`/api/workflow-runs/${runId}`, { method: "DELETE" }),

  confirmRequirements: (runId: string, requirementSpec: StructuredRequirementSpec) =>
    request<WorkflowRun>(`/api/workflow-runs/${runId}/requirements`, {
      method: "PUT",
      body: JSON.stringify({ requirement_spec: requirementSpec }),
    }),

  query: (spec: RequirementSpec, structured?: StructuredRequirementSpec | null) =>
    request<QueryResponse>("/api/query", {
      method: "POST",
      body: JSON.stringify({
        question: [
          spec.query,
          (structured?.use_case || spec.useCase) && `用途：${structured?.use_case || spec.useCase}`,
          structured?.subject.description && `主体：${structured.subject.description}`,
          structured?.subject.action && `动作：${structured.subject.action}`,
          structured?.environment && `环境：${structured.environment}`,
          structured?.style.length && `风格：${structured.style.join("、")}`,
          structured?.composition && `构图：${structured.composition}`,
          structured?.camera.shot && `镜头：${structured.camera.shot}`,
          structured?.camera.lens && `镜头参数：${structured.camera.lens}`,
          structured?.lighting.length && `光线：${structured.lighting.join("、")}`,
          structured?.palette.length && `配色：${structured.palette.join("、")}`,
          structured?.negative_constraints.length && `禁止项：${structured.negative_constraints.join("、")}`,
          spec.targetModel && `目标模型：${spec.targetModel}`,
          spec.ratio && `画幅：${spec.ratio}`,
          spec.textContent && `画面文字：${spec.textContent}`,
          spec.referenceMode === "required" && "需要参考图片",
          spec.referenceMode === "none" && "不使用参考图片",
        ]
          .filter(Boolean)
          .join("；"),
        session_id: crypto.randomUUID(),
        language: "zh",
      }),
    }),

  analyze: (query: string, promptIds: string[]) =>
    request<AnalysisResponse>("/api/analyze-results", {
      method: "POST",
      body: JSON.stringify({ query, prompt_ids: promptIds }),
    }),

  translate: (promptId: string) =>
    request<{ translation: string }>("/api/translate", {
      method: "POST",
      body: JSON.stringify({ prompt_id: promptId, target_language: "zh" }),
    }),

  translateText: (text: string) =>
    request<{ translation: string }>("/api/translate-text", {
      method: "POST",
      body: JSON.stringify({ text, target_language: "zh" }),
    }),

  remix: (promptId: string, requirement: string) =>
    request<RemixResponse>("/api/remix", {
      method: "POST",
      body: JSON.stringify({ prompt_id: promptId, requirement }),
    }),
};

async function adminRequest<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });
}

export const adminApi = {
  login: (password: string) =>
    request<{ token: string; expires_in: number }>("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  session: (token: string) =>
    adminRequest<{ authenticated: boolean }>("/api/admin/session", token),

  stats: (token: string) => adminRequest<AdminStats>("/api/admin/stats", token),

  prompts: (
    token: string,
    options: { query?: string; status?: "active" | "inactive" | "all"; page?: number; pageSize?: number },
  ) => {
    const params = new URLSearchParams({
      query: options.query ?? "",
      status: options.status ?? "all",
      page: String(options.page ?? 1),
      page_size: String(options.pageSize ?? 30),
    });
    return adminRequest<AdminPromptPage>(`/api/admin/prompts?${params}`, token);
  },

  createPrompt: (token: string, prompt: AdminPromptInput) =>
    adminRequest<AdminSaveResponse>("/api/admin/prompts", token, {
      method: "POST",
      body: JSON.stringify(prompt),
    }),

  updatePrompt: (token: string, promptId: string, prompt: AdminPromptInput) =>
    adminRequest<AdminSaveResponse>(`/api/admin/prompts/${encodeURIComponent(promptId)}`, token, {
      method: "PUT",
      body: JSON.stringify(prompt),
    }),
};
