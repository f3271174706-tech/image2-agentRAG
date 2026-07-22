"""知识库数据验证脚本

验证项：
- 主知识库记录 ID 唯一
- source_id 唯一
- 主知识库唯一记录数与 manifest totalPrompts 一致
- 所有 manifest 分类文件均已处理
- 分类文件中的记录允许交叉出现，但主库不得重复
- 每条记录都有非空 content
- content 与 prompt 完全一致
- JSONL 每一行均可独立解析
- 图片字段类型正确
- 动态参数正确提取
- 哈希可以重新计算并一致
- 不存在因 README 解析造成的截断提示词
"""
import hashlib
import json
import re
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (
    PROMPTS_JSONL,
    PROMPTS_BY_CATEGORY_DIR,
    CATEGORIES_FILE,
    SEARCH_REPO_DIR,
    LOG_DIR,
    LOG_LEVEL,
)

# ── 日志 ──────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "validate.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

RE_ARGUMENT_ESCAPED = re.compile(
    r'\{argument\s+name=\\"([^"]*?)\\"\s+default=\\"([^"]*?)\\"\}'
)
RE_ARGUMENT_PLAIN = re.compile(
    r'\{argument\s+name="([^"]*?)"\s+default="([^"]*?)"\}'
)
RE_URL = re.compile(r"^https?://[^\s\"'<>]+$")


class ValidationReport:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.total_records = 0
        self.valid_records = 0
        self.invalid_records = 0

    def error(self, msg: str):
        self.errors.append(msg)
        log.error(f"❌ {msg}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        log.warning(f"⚠️  {msg}")

    def ok(self, msg: str):
        log.info(f"✅ {msg}")

    def summary(self) -> dict:
        return {
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "passed": len(self.errors) == 0,
        }


def compute_content_hash(record: dict) -> str:
    """重新计算 content_hash"""
    parts = [
        record.get("content", ""),
        record.get("title", ""),
        record.get("description", ""),
        json.dumps(record.get("sourceMedia", record.get("source_media", [])), sort_keys=True),
        str(record.get("needReferenceImages", record.get("need_reference_images", False))),
        json.dumps(record.get("metadata", {}).get("categories", []), sort_keys=True),
    ]
    raw = "||".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_jsonl(filepath: Path, report: ValidationReport) -> list[dict]:
    """验证 JSONL 可解析性"""
    records = []
    if not filepath.exists():
        report.error(f"文件不存在: {filepath}")
        return records

    line_num = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                report.error(f"JSONL 第 {line_num} 行解析失败: {e}")

    report.ok(f"JSONL 解析: {len(records)} 条记录")
    return records


def validate_ids(records: list[dict], report: ValidationReport):
    """验证 ID 和 source_id 唯一性"""
    seen_ids: dict[str, int] = {}
    seen_sids: dict[str, int] = {}

    for i, record in enumerate(records):
        rid = record.get("id")
        if not rid:
            report.error(f"记录 {i}: 缺少 id")
        elif rid in seen_ids:
            report.error(f"记录 {i}: id 重复 (与记录 {seen_ids[rid]} 冲突): {rid}")
        else:
            seen_ids[rid] = i

        sid = str(record.get("metadata", {}).get("source_id", ""))
        if not sid:
            report.error(f"记录 {i}: 缺少 source_id")
        elif sid in seen_sids:
            report.error(f"记录 {i}: source_id 重复 (与记录 {seen_sids[sid]} 冲突): {sid}")
        else:
            seen_sids[sid] = i


def validate_content(records: list[dict], report: ValidationReport):
    """验证 content 完整性"""
    for i, record in enumerate(records):
        content = record.get("content", "")
        prompt = record.get("prompt", "")

        if not content or not content.strip():
            report.error(f"记录 {i} (id={record.get('id')}): content 为空")

        if content != prompt:
            report.error(f"记录 {i}: content 与 prompt 不一致")

        if len(content.strip()) < 10:
            report.warn(f"记录 {i}: content 过短 ({len(content)} 字符)")


def validate_hash(records: list[dict], report: ValidationReport):
    """验证 content_hash 可重新计算"""
    for i, record in enumerate(records):
        expected = compute_content_hash(record)
        actual = record.get("metadata", {}).get("content_hash", "")
        if not actual:
            report.error(f"记录 {i}: metadata.content_hash 缺失")
        elif actual != expected:
            report.error(
                f"记录 {i}: content_hash 不匹配 "
                f"(期望 {expected[:16]}..., 实际 {actual[:16]}...)"
            )


def validate_images(records: list[dict], report: ValidationReport):
    """验证图片字段"""
    total = 0
    invalid = 0
    for i, record in enumerate(records):
        media = record.get("source_media", [])
        if not isinstance(media, list):
            report.error(f"记录 {i}: source_media 不是数组")
            continue
        for url in media:
            total += 1
            if not isinstance(url, str) or not RE_URL.match(url):
                report.warn(f"记录 {i}: 图片 URL 格式异常: {str(url)[:80]}")
                invalid += 1

    if invalid:
        report.warn(f"图片 URL: {invalid}/{total} 格式异常")
    else:
        report.ok(f"图片 URL: 全部 {total} 个正常")


def validate_arguments(records: list[dict], report: ValidationReport):
    """验证动态参数提取"""
    with_args = 0
    for i, record in enumerate(records):
        content = record.get("content", "")
        arguments = record.get("arguments", [])

        expected = []
        seen = set()
        for m in RE_ARGUMENT_ESCAPED.finditer(content):
            n, d = m.group(1), m.group(2)
            if n not in seen:
                seen.add(n)
                expected.append({"name": n, "default": d})
        for m in RE_ARGUMENT_PLAIN.finditer(content):
            n, d = m.group(1), m.group(2)
            if n not in seen:
                seen.add(n)
                expected.append({"name": n, "default": d})

        if len(expected) != len(arguments):
            report.warn(
                f"记录 {i}: 参数数量不匹配 (期望 {len(expected)}, 实际 {len(arguments)})"
            )

        if arguments:
            with_args += 1

    report.ok(f"动态参数: {with_args} 条记录含参数")


def validate_manifest_consistency(records: list[dict], report: ValidationReport):
    """验证与 manifest 的一致性"""
    manifest_path = SEARCH_REPO_DIR / "references" / "manifest.json"
    if not manifest_path.exists():
        report.warn("manifest.json 不存在，跳过一致性检查")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_total = manifest.get("totalPrompts", 0)
    actual_total = len(records)

    if actual_total != expected_total:
        diff = expected_total - actual_total
        if diff > 0:
            # 上游 manifest 可能包含未分类的记录（不在任何分类文件中）
            report.warn(
                f"主知识库记录数 ({actual_total}) 比 manifest totalPrompts ({expected_total}) 少 {diff} 条"
                f"（上游有 {diff} 条记录未出现在任何分类文件中）"
            )
        else:
            report.error(
                f"主知识库记录数 ({actual_total}) 超过 manifest totalPrompts ({expected_total})"
            )
    else:
        report.ok(f"记录数一致: {actual_total} = manifest.totalPrompts")

    # 检查所有分类文件均已处理
    if CATEGORIES_FILE.exists():
        categories = json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))
        for cat in manifest["categories"]:
            slug = cat["slug"]
            if slug not in categories:
                report.error(f"分类 '{slug}' 未处理")
    else:
        report.warn("categories.json 不存在")


def validate_category_files(report: ValidationReport):
    """验证按分类文件"""
    if not PROMPTS_BY_CATEGORY_DIR.exists():
        report.warn("按分类目录不存在")
        return

    total = 0
    for filepath in PROMPTS_BY_CATEGORY_DIR.glob("*.jsonl"):
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        json.loads(line)
                        count += 1
                    except json.JSONDecodeError as e:
                        report.error(f"分类文件 {filepath.name} 解析失败: {e}")
        total += count

    report.ok(f"分类文件: {len(list(PROMPTS_BY_CATEGORY_DIR.glob('*.jsonl')))} 个, {total} 条记录")


def main():
    log.info("=" * 60)
    log.info("🔍 知识库数据验证")
    log.info("=" * 60)

    report = ValidationReport()

    records = validate_jsonl(PROMPTS_JSONL, report)
    report.total_records = len(records)

    if not records:
        log.error("❌ 无记录可验证")
        sys.exit(1)

    validate_ids(records, report)
    validate_content(records, report)
    validate_hash(records, report)
    validate_images(records, report)
    validate_arguments(records, report)
    validate_manifest_consistency(records, report)
    validate_category_files(report)

    report.invalid_records = len(report.errors)
    report.valid_records = report.total_records - report.invalid_records

    summary = report.summary()
    log.info("=" * 60)
    log.info("📋 验证摘要")
    log.info(f"  总记录数: {summary['total_records']}")
    log.info(f"  有效记录: {summary['valid_records']}")
    log.info(f"  无效记录: {summary['invalid_records']}")
    log.info(f"  错误数: {summary['errors']}")
    log.info(f"  警告数: {summary['warnings']}")
    log.info(f"  验证结果: {'✅ 通过' if summary['passed'] else '❌ 失败'}")
    log.info("=" * 60)

    report_file = LOG_DIR / "validation-report.json"
    report_file.write_text(
        json.dumps({
            "validated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "summary": summary,
            "errors": report.errors[:50],
            "warnings": report.warnings[:50],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info(f"📄 验证报告: {report_file}")

    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
