"""知识库同步脚本

从公开仓库 gpt-image-2-prompts-search 同步结构化 JSON 数据。

同步逻辑：
1. clone 或 pull 目标仓库
2. 读取 manifest.json，检查 updatedAt
3. 如有变化，读取所有分类 JSON
4. 按 source_id 聚合去重
5. 用 content_hash 判断新增/修改/未变化
6. 上游删除的记录标记为 inactive
7. 生成增量文件
8. 幂等：重复执行不产生重复记录
"""
import subprocess
import sys
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    SEARCH_REPO_URL,
    SEARCH_REPO_BRANCH,
    SEARCH_REPO_DIR,
    SYNC_STATE_FILE,
    LOG_DIR,
    LOG_LEVEL,
)
from normalize import (
    read_manifest,
    aggregate_and_dedup,
    save_jsonl,
    save_by_category,
    save_deltas,
    save_categories_meta,
    generate_statistics,
    PROMPTS_JSONL,
    PROMPTS_BY_CATEGORY_DIR,
    DELTAS_DIR,
    STATISTICS_FILE,
)

# ── 日志 ──────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def load_sync_state() -> dict:
    """加载同步状态"""
    if SYNC_STATE_FILE.exists():
        return json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
    return {
        "last_sync_at": None,
        "last_manifest_updated_at": None,
        "total_prompts": 0,
    }


def save_sync_state(state: dict) -> None:
    """保存同步状态"""
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_existing_records() -> dict[str, dict]:
    """加载现有知识库记录（key: source_id）"""
    records = {}
    if PROMPTS_JSONL.exists():
        with open(PROMPTS_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    sid = str(r.get("metadata", {}).get("source_id", ""))
                    if sid:
                        r["_source_id"] = sid
                        r["_content_hash_full"] = r.get("metadata", {}).get("content_hash", "")
                        r["_categories"] = r.get("metadata", {}).get("categories", [])
                        r["_primary_category"] = r.get("metadata", {}).get("primary_category", "")
                        r["_is_raycast"] = len(r.get("arguments", [])) > 0
                        records[sid] = r
                except json.JSONDecodeError:
                    pass
    return records


def update_repo() -> bool:
    """clone 或 pull 目标仓库"""
    if not (SEARCH_REPO_DIR / ".git").exists():
        log.info(f"📥 克隆仓库: {SEARCH_REPO_URL}")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", SEARCH_REPO_BRANCH,
             SEARCH_REPO_URL, str(SEARCH_REPO_DIR)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.error(f"❌ 克隆失败: {result.stderr}")
            return False
        log.info("✅ 克隆完成")
    else:
        log.info("🔄 拉取最新代码...")
        result = subprocess.run(
            ["git", "-C", str(SEARCH_REPO_DIR), "pull", "--ff-only"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning(f"⚠️  拉取失败，使用本地版本: {result.stderr}")
            return False
        log.info("✅ 仓库已更新")
    return True


def sync() -> dict:
    """执行同步"""
    log.info("=" * 60)
    log.info("🔄 知识库同步")
    log.info("=" * 60)

    state = load_sync_state()

    # 更新仓库
    update_repo()

    # 读取 manifest
    manifest = read_manifest(SEARCH_REPO_DIR)
    manifest_updated_at = manifest.get("updatedAt", "")
    log.info(f"📋 Manifest: updatedAt={manifest_updated_at}, totalPrompts={manifest['totalPrompts']}")

    # 检查是否有变化
    if state.get("last_manifest_updated_at") == manifest_updated_at and PROMPTS_JSONL.exists():
        log.info("⏭️  上游未更新，跳过同步")
        state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        save_sync_state(state)
        return state

    # 加载现有记录
    old_records = load_existing_records()
    log.info(f"📦 现有记录: {len(old_records)} 条")

    # 聚合去重
    log.info("📥 读取分类文件...")
    new_records, categories_map = aggregate_and_dedup(SEARCH_REPO_DIR, manifest)
    log.info(f"📊 去重后唯一记录: {len(new_records)} 条")

    # 生成增量
    delta_stats = save_deltas(old_records, new_records, DELTAS_DIR)
    log.info(f"📝 增量: +{delta_stats['added']} ~{delta_stats['updated']} ={delta_stats['unchanged']} -{delta_stats['inactive']}")

    # 保存主 JSONL
    count = save_jsonl(new_records, PROMPTS_JSONL)
    log.info(f"💾 主 JSONL: {count} 条")

    # 按分类保存
    category_counts = save_by_category(new_records, PROMPTS_BY_CATEGORY_DIR)
    log.info(f"📁 分类文件: {len(category_counts)} 个")

    # 保存元数据
    save_categories_meta(new_records, manifest)

    stats = generate_statistics(new_records, category_counts, manifest, delta_stats)
    STATISTICS_FILE.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 更新同步状态
    state.update({
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "last_manifest_updated_at": manifest_updated_at,
        "total_prompts": count,
    })
    save_sync_state(state)

    # 打印摘要
    log.info("=" * 60)
    log.info("📋 同步摘要")
    log.info(f"  Manifest updatedAt: {manifest_updated_at}")
    log.info(f"  主知识库唯一记录: {count}")
    log.info(f"  新增: {delta_stats['added']}")
    log.info(f"  修改: {delta_stats['updated']}")
    log.info(f"  未变化: {delta_stats['unchanged']}")
    log.info(f"  停用: {delta_stats['inactive']}")
    log.info("=" * 60)
    log.info("✅ 同步完成！")

    return state


def main():
    sync()


if __name__ == "__main__":
    main()
