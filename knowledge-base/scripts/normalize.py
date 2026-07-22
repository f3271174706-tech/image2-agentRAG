"""结构化 JSON 标准化器

从 gpt-image-2-prompts-search 仓库的公开 JSON 文件中读取提示词数据，
按 source_id 去重，输出标准化 JSONL 知识库。

README 解析仅作为备用兼容模式。
"""
import hashlib
import json
import re
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    SEARCH_REPO_DIR,
    PROMPTS_JSONL,
    PROMPTS_BY_CATEGORY_DIR,
    DELTAS_DIR,
    CATEGORIES_FILE,
    METADATA_DIR,
    STATISTICS_FILE,
    SOURCE_REPO,
    LOG_DIR,
    LOG_LEVEL,
)

# ── 日志 ──────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "normalize.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── 动态参数正则 ──────────────────────────────────────────────────────
RE_ARGUMENT_ESCAPED = re.compile(
    r'\{argument\s+name=\\"([^"]*?)\\"\s+default=\\"([^"]*?)\\"\}'
)
RE_ARGUMENT_PLAIN = re.compile(
    r'\{argument\s+name="([^"]*?)"\s+default="([^"]*?)"\}'
)


def compute_content_hash(record: dict) -> str:
    """基于影响知识内容的稳定字段计算完整 SHA-256 哈希"""
    parts = [
        record.get("content", ""),
        record.get("title", ""),
        record.get("description", ""),
        json.dumps(record.get("sourceMedia", []), sort_keys=True),
        str(record.get("needReferenceImages", False)),
        json.dumps(record.get("categories", []), sort_keys=True),
    ]
    raw = "||".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def short_hash(full_hash: str) -> str:
    """截断哈希用于展示（16字符）"""
    return full_hash[:16]


def extract_arguments(prompt_text: str) -> list[dict]:
    """从 prompt 中提取动态参数（同时处理转义和非转义引号格式）"""
    args = []
    seen = set()
    for match in RE_ARGUMENT_ESCAPED.finditer(prompt_text):
        name = match.group(1)
        default = match.group(2)
        if name not in seen:
            seen.add(name)
            args.append({"name": name, "default": default})
    for match in RE_ARGUMENT_PLAIN.finditer(prompt_text):
        name = match.group(1)
        default = match.group(2)
        if name not in seen:
            seen.add(name)
            args.append({"name": name, "default": default})
    return args


def make_stable_id(source_id: int) -> str:
    """生成稳定 ID，不依赖排列顺序"""
    return f"youmind-gpt-image-2-{source_id}"


def read_manifest(repo_dir: Path) -> dict:
    """读取 manifest.json"""
    manifest_path = repo_dir / "references" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json 不存在: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def read_category_file(repo_dir: Path, filename: str) -> list[dict]:
    """读取单个分类 JSON 文件"""
    filepath = repo_dir / "references" / filename
    if not filepath.exists():
        log.warning(f"⚠️  分类文件不存在: {filepath}")
        return []
    return json.loads(filepath.read_text(encoding="utf-8"))


def normalize_record(raw: dict, categories: list[str], primary_category: str) -> dict:
    """将上游原始记录标准化为知识库格式"""
    content = raw.get("content", "")
    title = raw.get("title", "")
    description = raw.get("description", "")
    source_media = raw.get("sourceMedia", [])
    need_ref = raw.get("needReferenceImages", False)
    source_id = raw.get("id", 0)

    arguments = extract_arguments(content)
    content_hash = compute_content_hash({
        "content": content,
        "title": title,
        "description": description,
        "sourceMedia": source_media,
        "needReferenceImages": need_ref,
        "categories": categories,
    })

    now = datetime.now(timezone.utc).isoformat()

    record = {
        # ── 顶层兼容字段 ──
        "id": make_stable_id(source_id),
        "content": content,
        "prompt": content,
        "title": title,
        "description": description,
        "category": primary_category,
        "source_media": source_media,
        "preview_image": source_media[0] if source_media else "",
        "need_reference_images": need_ref,
        "arguments": arguments,
        "language": "en",
        "source_repo": SOURCE_REPO,
        "content_hash": short_hash(content_hash),
        "status": "active",

        # ── RAG 兼容 metadata 块 ──
        "metadata": {
            "source_id": source_id,
            "title": title,
            "description": description,
            "primary_category": primary_category,
            "categories": categories,
            "source_media": source_media,
            "preview_image": source_media[0] if source_media else "",
            "need_reference_images": need_ref,
            "arguments": arguments,
            "source_repo": SOURCE_REPO,
            "source_updated_at": "",
            "content_hash": content_hash,
            "status": "active",
        },

        # ── 内部管理字段 ──
        "_source_id": source_id,
        "_content_hash_full": content_hash,
        "_categories": categories,
        "_primary_category": primary_category,
        "_is_raycast": len(arguments) > 0,
        "_created_at": now,
        "_updated_at": now,
    }

    return record


def aggregate_and_dedup(
    repo_dir: Path, manifest: dict
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """遍历所有分类 JSON，按 source_id 去重聚合

    Returns:
        (deduped_records, category_map)
        - deduped_records: {source_id: normalized_record}
        - category_map: {source_id: [category_slug, ...]}
    """
    records: dict[str, dict] = {}      # source_id → raw record (first seen)
    categories_map: dict[str, list[str]] = {}  # source_id → [slug, ...]
    primary_cat: dict[str, str] = {}   # source_id → first category slug

    for cat in manifest["categories"]:
        slug = cat["slug"]
        filename = cat["file"]
        raw_list = read_category_file(repo_dir, filename)
        log.info(f"  📂 {slug}: {len(raw_list)} 条")

        for raw in raw_list:
            sid = str(raw.get("id", 0))
            if sid not in categories_map:
                categories_map[sid] = []
                primary_cat[sid] = slug
                records[sid] = raw
            if slug not in categories_map[sid]:
                categories_map[sid].append(slug)

    # 标准化
    deduped: dict[str, dict] = {}
    for sid, raw in records.items():
        cats = categories_map[sid]
        primary = primary_cat[sid]
        deduped[sid] = normalize_record(raw, cats, primary)

    return deduped, categories_map


def save_jsonl(records: dict[str, dict], output_path: Path) -> int:
    """保存为 JSONL（覆盖写入）"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records.values():
            # 写入时去掉内部管理字段
            clean = {k: v for k, v in record.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return len(records)


def save_by_category(
    records: dict[str, dict], output_dir: Path
) -> dict[str, int]:
    """按分类保存 JSONL（同一记录可出现在多个分类文件中）"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 先清理旧文件
    for old_file in output_dir.glob("*.jsonl"):
        old_file.unlink()

    # 按分类分组
    by_category: dict[str, list[dict]] = {}
    for record in records.values():
        for cat in record.get("_categories", []):
            by_category.setdefault(cat, []).append(record)

    category_counts = {}
    for cat, cat_records in by_category.items():
        filepath = output_dir / f"{cat}.jsonl"
        with open(filepath, "w", encoding="utf-8") as f:
            for r in cat_records:
                clean = {k: v for k, v in r.items() if not k.startswith("_")}
                f.write(json.dumps(clean, ensure_ascii=False) + "\n")
        category_counts[cat] = len(cat_records)

    return category_counts


def save_deltas(
    old_records: dict[str, dict],
    new_records: dict[str, dict],
    deltas_dir: Path,
) -> dict[str, int]:
    """生成增量文件"""
    deltas_dir.mkdir(parents=True, exist_ok=True)

    added = []
    updated = []
    inactive = []

    old_sids = set(old_records.keys())
    new_sids = set(new_records.keys())

    # 新增
    for sid in new_sids - old_sids:
        clean = {k: v for k, v in new_records[sid].items() if not k.startswith("_")}
        added.append(clean)

    # 修改和未变化
    unchanged = 0
    for sid in old_sids & new_sids:
        old_hash = old_records[sid].get("_content_hash_full", "")
        new_hash = new_records[sid].get("_content_hash_full", "")
        if old_hash != new_hash:
            clean = {k: v for k, v in new_records[sid].items() if not k.startswith("_")}
            updated.append(clean)
        else:
            unchanged += 1

    # 停用
    for sid in old_sids - new_sids:
        record = old_records[sid].copy()
        record["status"] = "inactive"
        record["metadata"]["status"] = "inactive"
        record["_updated_at"] = datetime.now(timezone.utc).isoformat()
        clean = {k: v for k, v in record.items() if not k.startswith("_")}
        inactive.append(clean)

    # 写入文件
    for name, data in [("added", added), ("updated", updated), ("inactive", inactive)]:
        filepath = deltas_dir / f"{name}.jsonl"
        with open(filepath, "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "added": len(added),
        "updated": len(updated),
        "unchanged": unchanged,
        "inactive": len(inactive),
    }


def save_categories_meta(records: dict[str, dict], manifest: dict) -> None:
    """保存分类元数据"""
    categories = {}
    for cat in manifest["categories"]:
        slug = cat["slug"]
        categories[slug] = {
            "slug": slug,
            "title": cat["title"],
            "file": cat["file"],
            "manifest_count": cat["count"],
            "unique_records": 0,
        }

    # 统计每个分类的唯一记录数
    for record in records.values():
        for cat in record.get("_categories", []):
            if cat in categories:
                categories[cat]["unique_records"] += 1

    CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATEGORIES_FILE.write_text(
        json.dumps(categories, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def generate_statistics(
    records: dict[str, dict],
    category_counts: dict[str, int],
    manifest: dict,
    delta_stats: dict[str, int],
) -> dict:
    """生成统计信息"""
    total = len(records)
    with_preview = sum(1 for r in records.values() if r.get("preview_image"))
    with_args = sum(1 for r in records.values() if r.get("arguments"))
    need_ref = sum(1 for r in records.values() if r.get("need_reference_images"))
    raycast = sum(1 for r in records.values() if r.get("_is_raycast"))

    # 按语言统计
    by_language = {}
    for r in records.values():
        lang = r.get("language", "en")
        by_language[lang] = by_language.get(lang, 0) + 1

    # 分类记录总和（含重复）
    category_sum = sum(cat["count"] for cat in manifest["categories"])

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_updated_at": manifest.get("updatedAt", ""),
        "manifest_total_prompts": manifest.get("totalPrompts", 0),
        "total_prompts": total,
        "category_sum": category_sum,
        "cross_category_duplicates": category_sum - total,
        "with_preview_image": with_preview,
        "with_arguments": with_args,
        "need_reference_images": need_ref,
        "raycast_friendly": raycast,
        "by_language": by_language,
        "by_category": category_counts,
        "sync_stats": delta_stats,
    }

    return stats


def main():
    """主入口"""
    log.info("=" * 60)
    log.info("🚀 结构化 JSON 知识库标准化")
    log.info("=" * 60)

    # 检查数据源
    if not SEARCH_REPO_DIR.exists():
        log.error(f"❌ 数据源目录不存在: {SEARCH_REPO_DIR}")
        log.error("   请先克隆: git clone https://github.com/YouMind-OpenLab/gpt-image-2-prompts-search.git search-source")
        sys.exit(1)

    # 读取 manifest
    manifest = read_manifest(SEARCH_REPO_DIR)
    log.info(f"📋 Manifest: updatedAt={manifest['updatedAt']}, totalPrompts={manifest['totalPrompts']}")
    log.info(f"   分类数: {len(manifest['categories'])}")

    # 加载现有记录（用于增量比对）
    old_records: dict[str, dict] = {}
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
                        # 重建内部字段
                        r["_source_id"] = sid
                        r["_content_hash_full"] = r.get("metadata", {}).get("content_hash", "")
                        r["_categories"] = r.get("metadata", {}).get("categories", [])
                        r["_primary_category"] = r.get("metadata", {}).get("primary_category", "")
                        r["_is_raycast"] = len(r.get("arguments", [])) > 0
                        old_records[sid] = r
                except json.JSONDecodeError:
                    pass
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
    log.info(f"💾 主 JSONL: {count} 条 → {PROMPTS_JSONL}")

    # 按分类保存
    category_counts = save_by_category(new_records, PROMPTS_BY_CATEGORY_DIR)
    log.info(f"📁 分类文件: {len(category_counts)} 个")

    # 保存元数据
    save_categories_meta(new_records, manifest)

    stats = generate_statistics(new_records, category_counts, manifest, delta_stats)
    STATISTICS_FILE.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 打印摘要
    log.info("=" * 60)
    log.info("📋 导入摘要")
    log.info(f"  Manifest updatedAt: {stats['manifest_updated_at']}")
    log.info(f"  Manifest totalPrompts: {stats['manifest_total_prompts']}")
    log.info(f"  主知识库唯一记录: {stats['total_prompts']}")
    log.info(f"  分类记录总和: {stats['category_sum']}")
    log.info(f"  跨分类重复: {stats['cross_category_duplicates']}")
    log.info(f"  含预览图: {stats['with_preview_image']}")
    log.info(f"  含动态参数: {stats['with_arguments']}")
    log.info(f"  需参考图: {stats['need_reference_images']}")
    log.info(f"  Raycast 友好: {stats['raycast_friendly']}")
    log.info(f"  同步增量: +{delta_stats['added']} ~{delta_stats['updated']} ={delta_stats['unchanged']} -{delta_stats['inactive']}")
    log.info("=" * 60)
    log.info("✅ 标准化完成！")

    return stats


if __name__ == "__main__":
    main()
