# GPT Image 2 提示词知识库

从 [YouMind-OpenLab/gpt-image-2-prompts-search](https://github.com/YouMind-OpenLab/gpt-image-2-prompts-search) 构建的结构化提示词知识库。

## 数据源

- **主数据源**：`gpt-image-2-prompts-search/references/` — 公开结构化 JSON，无需 API Key
- **旧版兼容**：`awesome-gpt-image-2/README.md` — 已迁移至 `legacy-readme/`

## 目录结构

```
knowledge-base/
├── normalized/
│   ├── prompts.jsonl                 # 主知识库（12,569 条，66MB）
│   ├── prompts-by-category/          # 按分类拆分（11 个文件）
│   ├── deltas/                       # 增量文件
│   │   ├── added.jsonl
│   │   ├── updated.jsonl
│   │   └── inactive.jsonl
│   └── legacy-readme/                # 旧版120条 README 数据
├── metadata/
│   ├── sync-state.json               # 同步状态
│   ├── categories.json               # 分类定义
│   └── statistics.json               # 统计信息
├── scripts/
│   ├── config.py                     # 配置管理
│   ├── normalize.py                  # JSON 标准化器
│   ├── sync.py                       # 同步脚本
│   └── validate.py                   # 数据验证
├── logs/
├── .env                              # 配置文件
└── requirements.txt
```

## 命令

```bash
# 首次导入 / 全量重建
python scripts/normalize.py

# 每日增量同步
python scripts/sync.py

# 数据验证
python scripts/validate.py
```

## JSONL 记录格式

```json
{
  "id": "youmind-gpt-image-2-12345",
  "content": "完整原始提示词",
  "prompt": "完整原始提示词",
  "title": "标题",
  "description": "描述",
  "category": "profile-avatar",
  "source_media": ["https://...jpg"],
  "preview_image": "https://...jpg",
  "need_reference_images": false,
  "arguments": [{"name": "xxx", "default": "yyy"}],
  "language": "en",
  "source_repo": "YouMind-OpenLab/gpt-image-2-prompts-search",
  "content_hash": "a1b2c3...",
  "status": "active",
  "metadata": {
    "source_id": 12345,
    "title": "",
    "description": "",
    "primary_category": "profile-avatar",
    "categories": ["profile-avatar", "product-marketing"],
    "source_media": [],
    "preview_image": "",
    "need_reference_images": false,
    "arguments": [],
    "source_repo": "",
    "source_updated_at": "",
    "content_hash": "完整SHA-256",
    "status": "active"
  }
}
```

## 增量更新逻辑

1. `git pull` 更新仓库
2. 对比 `manifest.json` 的 `updatedAt`
3. 如有变化，读取所有分类 JSON
4. 按 `source_id` 聚合去重
5. 用 `content_hash` 判断新增/修改/未变化
6. 上游删除的记录标记为 `inactive`
7. 幂等执行，不产生重复记录
