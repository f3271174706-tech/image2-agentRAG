# Prompt RAG 私有服务器部署

本方案面向 Ubuntu 22.04/24.04、4 核 CPU、4GB 内存的单用户服务器。应用由
systemd 管理，Nginx 提供 HTTPS、Basic Auth 和 API 限流。生产环境继续使用项目
自己的 `.venv`，服务器不需要 Node.js、Docker、Qdrant 或 MySQL。

## 1. 本地生成脱敏发布包

先确保前端已构建并且测试通过：

```powershell
cd D:\mycode\image2\prompt-rag\web-v2
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest
powershell -ExecutionPolicy Bypass -File .\deploy\prepare-release.ps1
```

输出文件为 `release\prompt-rag-release.zip`。发布数据库只保留 12,569 条知识库和
`text-embedding-v4` 的 1024 维向量；本地任务历史、分析缓存、翻译缓存、测试日志、
`.env` 和 API Key 不会进入发布包。

## 2. 域名与上传

先把域名 A 记录指向服务器公网 IP，再上传：

```powershell
scp .\release\prompt-rag-release.zip root@SERVER_IP:/tmp/
```

服务器执行：

```bash
sudo apt-get update && sudo apt-get install -y unzip
sudo mkdir -p /opt/prompt-rag
sudo unzip -o /tmp/prompt-rag-release.zip -d /opt/prompt-rag
cd /opt/prompt-rag
DOMAIN=rag.example.com AUTH_USER=owner sudo -E bash deploy/install-ubuntu.sh
```

安装脚本会交互式创建工作台访问密码。不要使用弱密码。

## 3. 配置密钥

```bash
sudoedit /etc/prompt-rag/prompt-rag.env
```

至少替换以下值：

- `PROMPT_RAG_EMBEDDING_API_KEY`
- `PROMPT_RAG_LLM_API_KEY`
- `PROMPT_RAG_CORS_ORIGINS`

请在正式部署前重新生成 API Key。已经出现在聊天、截图或终端历史中的密钥不要继续用于生产。

## 4. 启动与 HTTPS

```bash
sudo systemctl start prompt-rag
sudo systemctl status prompt-rag --no-pager
curl http://127.0.0.1:8010/api/health
sudo certbot --nginx -d rag.example.com
```

浏览器访问 `https://rag.example.com/v2/`，先输入 Basic Auth 用户名和密码。

## 5. 验证

```bash
curl -u owner https://rag.example.com/api/health
sudo journalctl -u prompt-rag -n 100 --no-pager
sudo nginx -t
systemctl list-timers prompt-rag-backup.timer
```

健康响应应显示：

- `embedding_provider: openai-compatible`
- `embedding_model: text-embedding-v4`
- `embedding_dimensions: 1024`
- `prompts: 12569`
- `dense_enabled: true`

## 6. 备份与恢复

SQLite 每天自动备份到 `/opt/prompt-rag/backups`，保留 14 天。手动备份：

```bash
sudo systemctl start prompt-rag-backup.service
ls -lh /opt/prompt-rag/backups
```

恢复前先停止服务，把备份解压覆盖到 `/opt/prompt-rag/data/prompt_rag.db`，再修复所有权并启动：

```bash
sudo systemctl stop prompt-rag
sudo gunzip -c /opt/prompt-rag/backups/SELECTED.db.gz > /opt/prompt-rag/data/prompt_rag.db
sudo chown prompt-rag:prompt-rag /opt/prompt-rag/data/prompt_rag.db
sudo systemctl start prompt-rag
```

## 7. 常用维护命令

```bash
sudo systemctl restart prompt-rag
sudo systemctl stop prompt-rag
sudo journalctl -u prompt-rag -f
sudo nginx -t && sudo systemctl reload nginx
```
