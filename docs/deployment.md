# 生产部署

## CI/CD 流程

仓库包含 `.github/workflows/ci-cd.yml`：Pull Request 会执行后端迁移、Ruff、Pytest，以及前端 Vitest 和生产构建；`main` 通过后会构建前后端镜像、推送到 GHCR，并通过 GitHub `Production` Environment 部署至 <https://intelligence.ivaris.top>。

## 服务器要求

生产服务器需预先安装 Docker Engine、Docker Compose plugin 2.20+、Nginx 和 Certbot。默认部署路径是 `/opt/intelligence-hub-agents`，可通过 Environment variable `DEPLOY_PATH` 修改；SSH 端口可通过 `DEPLOY_PORT` 修改。应用前端只发布到宿主机 `127.0.0.1:18100`，不会与已有的 `voice-shopping-agents` 端口冲突。

两个项目复用 `voice-shopping-agents` 的 PostgreSQL 16/pgvector 容器，但使用独立的数据库和角色。该容器通过外部 Docker 网络 `ivaris-shared` 暴露为 `ivaris-postgres`；部署脚本会幂等创建 `intelligence_hub` 角色、`intelligence_hub_agents` 数据库和 vector 扩展，不会读取或修改 Voice Shopping 的业务表。

## GitHub Production 配置

在 GitHub 仓库的 **Settings → Environments → Production** 中配置以下 secrets：

| Secret | 内容 |
| --- | --- |
| `DEPLOY_HOST` | 生产服务器 SSH 主机名或 IP |
| `DEPLOY_USER` | 有权运行 Docker 的 SSH 用户 |
| `DEPLOY_SSH_KEY` | 对应用户的 SSH 私钥 |
| `DEPLOY_KNOWN_HOSTS`（可选） | 经人工核验的服务器 `known_hosts` 记录；未配置时，runner 会根据部署主机和 SSH 端口自动获取 |
| `AUTH_SECRET_KEY` | 至少 32 位的独立随机登录令牌签名密钥；工作流会在每次部署时注入 |
| `PRODUCTION_ENV_FILE` | 除 `AUTH_SECRET_KEY` 外的完整生产变量文件，按 `deploy/.env.production.example` 填写 |

建议为 `Production` 配置 required reviewers。

## 首次部署

将 Nginx 配置安装到宿主机并申请证书：

```bash
sudo cp /opt/intelligence-hub-agents/intelligence.ivaris.top.conf \
  /etc/nginx/sites-available/intelligence.ivaris.top.conf
sudo ln -s /etc/nginx/sites-available/intelligence.ivaris.top.conf \
  /etc/nginx/sites-enabled/intelligence.ivaris.top.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d intelligence.ivaris.top
```

应用文件保存在独立的 Docker named volume 中；每次发布会先确保共享数据库和网络存在，再执行 Alembic 迁移，API 与前端健康后才完成部署。
