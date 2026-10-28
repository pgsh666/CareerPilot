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


## 业务规则与诊断

当前数据库迁移包含 `0008_operation_diagnostics`。模型业务使用 DeepSeek Flash 非思考模式；训练保存材料、题目、参考要点和评分版本快照。完整规则见[出题、评分、报告及语音标准](../docs/出题与评测依据.md)。

- 报告以主问题题组组织全组实际作答，以原文片段编号绑定证据；服务端校验并计算分数。兼容同组关联修正和完全相同的重复评分，不合并冲突档位、不跨组改绑或修改原话。
- 失败重试先核对本人私有缓存；报告最多检查同一任务最近20次已记录失败调用。通过校验可恢复结果，原失败与费用仍保留；缓存不可用时，新增调用继续检查预算和费用状态。
- 管理中心的 `GET /api/v1/admin/tasks/{task_id}`、`GET /api/v1/admin/usage/{spend_id}` 展示逐次运行、错误码、校验位置及脱敏诊断；不展示其他用户材料、回答全文或密钥。
- 新录音由本机 Whisper small 转写，OpenCC转为简体，并从本场问题和已确认材料提取最多32项英文术语。原始音频仅临时处理，历史已提交文字和成功报告不回写；真人专业词识别已纳入本机功能人工验收；不同口音与噪声下仍可能误识别。

## 当前验证状态

截至2026-10-28，AI产品经理方向102项本机功能人工验收均已通过，采用最新人工复测确认。隔离测试、合成语音和人工验收分别说明；本结论不等于七方向专业评测、所有口音或公网部署全部通过。
