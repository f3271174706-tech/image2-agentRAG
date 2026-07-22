"""知识库配置管理"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(KNOWLEDGE_BASE_DIR / ".env")


def _resolve(path: str) -> Path:
    """将相对路径解析为绝对路径（基于 knowledge-base 目录）"""
    p = Path(path)
    if p.is_absolute():
        return p
    return KNOWLEDGE_BASE_DIR / p


# ── 公开结构化数据源（默认） ──
SEARCH_REPO_URL: str = os.getenv(
    "SEARCH_REPO_URL",
    "https://github.com/YouMind-OpenLab/gpt-image-2-prompts-search.git",
)
SEARCH_REPO_BRANCH: str = os.getenv("SEARCH_REPO_BRANCH", "main")
SEARCH_REPO_DIR: Path = _resolve(os.getenv("SEARCH_REPO_DIR", "../search-source"))

# ── 旧版 README 数据源（兼容） ──
AWESOME_REPO_URL: str = os.getenv(
    "AWESOME_REPO_URL",
    "https://github.com/YouMind-OpenLab/awesome-gpt-image-2.git",
)
AWESOME_REPO_DIR: Path = _resolve(os.getenv("AWESOME_REPO_DIR", "../data-source"))

# ── CMS API（可选高级模式） ──
CMS_HOST: str = os.getenv("CMS_HOST", "")
CMS_API_KEY: str = os.getenv("CMS_API_KEY", "")

# ── 知识库路径 ──
PROMPTS_JSONL: Path = _resolve(os.getenv("PROMPTS_JSONL", "normalized/prompts.jsonl"))
PROMPTS_BY_CATEGORY_DIR: Path = _resolve(
    os.getenv("PROMPTS_BY_CATEGORY_DIR", "normalized/prompts-by-category")
)
DELTAS_DIR: Path = _resolve(os.getenv("DELTAS_DIR", "normalized/deltas"))
METADATA_DIR: Path = _resolve(os.getenv("METADATA_DIR", "metadata"))
SYNC_STATE_FILE: Path = _resolve(os.getenv("SYNC_STATE_FILE", "metadata/sync-state.json"))
CATEGORIES_FILE: Path = _resolve(os.getenv("CATEGORIES_FILE", "metadata/categories.json"))
STATISTICS_FILE: Path = _resolve(os.getenv("STATISTICS_FILE", "metadata/statistics.json"))

# ── 日志 ──
LOG_DIR: Path = _resolve(os.getenv("LOG_DIR", "logs"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── 源仓库标识 ──
SOURCE_REPO: str = "YouMind-OpenLab/gpt-image-2-prompts-search"
