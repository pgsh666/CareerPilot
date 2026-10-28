# 第三方声明

CareerPilot 使用的开源依赖分别适用各自许可证，依赖版本见 `frontend/package-lock.json`、`backend/requirements.lock` 和 `backend/speech-requirements.lock`。

- Heroicons 2.2.0：选用图标的来源与 MIT 许可证位于 `frontend/src/ui/icons/heroicons/SOURCE.md` 和同目录 `LICENSE`。
- Morphicons 2.0.2：许可证位于 `frontend/public/icon-licenses.txt`。
- Lucide、Vue、FastAPI、SQLAlchemy 等组件的许可随其软件包分发。
- Whisper 离线模型由安装程序从其公开模型源下载，模型权重不包含在本仓库中，使用时需遵循对应模型许可。
- opencc-python-reimplemented 0.1.7：用于本地语音转写的繁体转简体转换，适用 Apache-2.0 许可证；项目来源为 https://github.com/yichen0831/opencc-python ，许可证随依赖包分发。

第三方许可证不替代项目代码本身的授权。
