# 后端命令说明

后端基于 Python 3.12、FastAPI 和 MySQL。安装、初始化与启动步骤见[项目 README](../README.md)。运行命令前，先激活安装依赖时使用的 Python 环境，并在仓库根目录执行。

| 命令 | 用途 |
| --- | --- |
| `python backend/manage.py init-env` | 创建本机配置与随机认证密钥，不覆盖已有文件 |
| `python backend/setup_mysql.py --new-database` | 创建独立本机项目库及专用账号 |
| `python backend/manage.py migrate` | 应用数据库迁移 |
| `python backend/manage.py serve` | 启动 127.0.0.1:8000 的 API |
| `python backend/manage.py create-admin` | 交互创建独立管理员 |
| `python backend/manage.py test` | 运行隔离测试，不调用真实模型 |
| `python backend/manage.py lint` | 运行 Ruff |
| `python backend/manage.py model-status` | 只读本地预算与费用状态 |
| `python backend/manage.py backup` | 创建业务备份 |
| `python backend/manage.py maintenance` | 核对到期清理和费用保护 |
| `python backend/manage.py verify-pricing --help` | 查看价格核对参数 |
| `python backend/manage.py reconcile-fee --help` | 查看供应商费用核实参数 |

`model-smoke` 和 `scripts/check_model_quality.py --real` 会在配置及预算允许时产生实际模型费用，普通安装与单元测试不需要执行。付费请求不自动重试，不通过删除本地台账重置累计额度。

本机健康检查为 `/health/live` 和 `/health/ready`，接口文档为 `/docs`。业务路由位于 `/api/v1`，登录使用 HttpOnly Cookie，已登录写操作需 CSRF 令牌；服务端仍校验对象归属和角色权限。

`backend/data/` 包含私有材料、离线模型、临时音频及维护保护记录，不能公开上传。数据库与原文件备份默认位于仓库 `backups/`。恢复使用根目录的交互入口，需停止服务并明确目标；缺少最新控制和费用保护记录时拒绝恢复。
