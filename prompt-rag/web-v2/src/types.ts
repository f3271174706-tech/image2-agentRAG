export interface PromptDocument {
  id: string;
  title: string;
  description: string;
  prompt: string;
  category: string;
  category_label: string;
  need_reference_images: boolean;
  preview_image: string;
  score: number;
  rank: number;
  can_translate: boolean;
}

export interface QueryResponse {
  question: string;
  rewritten_query: string;
  answer: string;
  documents: PromptDocument[];
  confidence: number;
  language: "zh" | "en";
  analysis_prompt_ids?: string[];
  translation_prompt_id?: string | null;
}

export interface CandidateInsight {
  prompt_id: string;
  personalized_title: string;
  match_reason: string;
  best_for: string;
  adaptation_tip: string;
}

export interface AnalysisResponse {
  summary: string;
  cards: CandidateInsight[];
  generated: boolean;
  cached: boolean;
}

export interface RemixResponse {
  prompt_id: string;
  source_title: string;
  remixed_prompt: string;
  generated: boolean;
}

export interface HealthResponse {
  status: string;
  prompts: number;
  dense_enabled: boolean;
  embedding_provider: string;
  embedding_model: string | null;
  embedding_dimensions: number | null;
  generation_enabled: boolean;
  translation_enabled: boolean;
  analysis_enabled: boolean;
  requirement_understanding_enabled: boolean;
}

export interface AdminPrompt {
  id: string;
  title: string;
  description: string;
  prompt: string;
  category: string;
  categories: string[];
  preview_image: string;
  source_media: string[];
  need_reference_images: boolean;
  arguments: Array<Record<string, unknown>>;
  language: string;
  content_hash: string;
  status: "active" | "inactive";
}

export interface AdminPromptInput {
  id?: string;
  title: string;
  description: string;
  prompt: string;
  category: string;
  categories: string[];
  preview_image: string;
  source_media: string[];
  need_reference_images: boolean;
  arguments: Array<Record<string, unknown>>;
  language: string;
  status: "active" | "inactive";
}

export interface AdminStats {
  prompts: number;
  active_prompts: number;
  inactive_prompts: number;
  embeddings: number;
  embedding_models: Record<string, number>;
  current_embedding_model: string;
  current_embeddings: number;
  categories: Record<string, number>;
  languages: Record<string, number>;
  translations: number;
  workflow_runs: number;
  db_bytes: number;
}

export interface AdminPromptPage {
  items: AdminPrompt[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminSaveResponse {
  document: AdminPrompt;
  embedding_status: "updated" | "pending" | "disabled" | "not_required";
  created: boolean;
}

export interface RequirementSpec {
  query: string;
  useCase: string;
  targetModel: string;
  ratio: string;
  textContent: string;
  referenceMode: "auto" | "required" | "none";
  outputLanguage: "zh" | "en";
}

export interface StructuredRequirementSpec {
  raw_request: string;
  use_case: string;
  subject: { description: string; action: string };
  environment: string;
  style: string[];
  composition: string;
  camera: { shot: string; lens: string };
  lighting: string[];
  palette: string[];
  text: { content: string; must_be_exact: boolean };
  references: Array<{ asset_id: string; role: string; preserve: string[] }>;
  negative_constraints: string[];
  output: {
    model: string;
    ratio: string;
    size: string;
    quality: "low" | "medium" | "high" | "auto";
    count: number;
    format: "png" | "jpeg" | "webp";
    prompt_language: "zh" | "en";
  };
  assumptions: string[];
  missing_fields: string[];
  confidence: number;
  schema_version: number;
}

export interface WorkflowRun {
  id: string;
  status: "requirements_ready" | "requirements_confirmed" | "interrupted";
  requirement_spec: StructuredRequirementSpec;
  generated: boolean;
  cached: boolean;
  model: string;
  schema_version: number;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
}
