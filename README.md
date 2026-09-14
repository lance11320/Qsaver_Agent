# Qsaver

面向教师的题库整理工作台：单题录入、多文档提取入库、选题及 DOCX 导出、对话式题库 Co-pilot。

支持 PDF/文档关系识别、印刷答案匹配、题图裁切与人工复核、题库清洗和版本回滚。题图以独立文件保存在 images 文件夹，并由题库 JSON 引用。

## 启动（Windows）

1. 安装 Python 3.12，确保 `py -3.12` 可用。
2. 双击根目录 `setup.bat` 创建环境并安装固定版本依赖。
3. 双击 `fast_dev/start.bat`。默认地址为 http://127.0.0.1:7860。
4. 在界面填写自己的 API Key。仓库不包含可用密钥、题库、PDF 或模型权重。

也可在 PowerShell 中运行：

```powershell
py -3.12 -m venv fast_dev/venv
fast_dev/venv/Scripts/python.exe -m pip install -r fast_dev/requirements-lock.txt
fast_dev/venv/Scripts/python.exe fast_dev/Qsaver.py
```

## 模型及图片设置

默认视觉模型为 Qwen 3.8 Flash，正文文本审核为 Qwen 3.8 Max（思考预算8192）。可在本地配置将 `text_review_model` 设为 `qwen3.8-flash`；使用同一个有效 Qwen 接口，不必准备第二种服务商密钥。接口需实际支持所选模型和参数。

正文 PDF 默认3倍渲染（216dpi），Qwen每图像素上限5,242,880；答案局部复读直接从原始PDF按4倍渲染。图像分辨率提高会增加视觉token用量。API配置示例见 `fast_dev/qsaver_backend_config.example.json`；实际配置由界面保存至同目录 `qsaver_backend_config.json`，已被Git忽略。

模型可能漏字、误读或裁掉图例。自动审查不是准确性保证，带图题仍须人工确认。批次失败或未被明确覆盖的题目保留为待复核，不视为干净批次。

可选本地模型放在 `fast_dev/models/`，或通过 `LLAMA_GGUF_MODEL` 等环境变量指定；本仓库不提供模型文件。

## 测试

```powershell
fast_dev/venv/Scripts/python.exe -m pytest -q
```

仓库仅包含使用临时数据/模拟接口的离线测试，运行它们不需要真实API或私人文档。

## 构建Windows便携包

完成环境安装后，在仓库根目录执行：

```powershell
fast_dev/venv/Scripts/python.exe build_dist.py
```

生成 `dist/`，含Python及依赖。已有dist时脚本会停止以避免覆盖。分发整个dist目录，用户双击其中start.bat启动；构建过程使用源码白名单与空配置，不复制开发者题库及密钥。

## 代码导航

- `fast_dev/Qsaver.py`：主入口；`chat_service.py`、`chat_assets/`：对话界面。
- `agent.py`、`document_map.py`：多文档提取与关系识别。
- `answer_authority.py`、`answer_zoom.py`：答案来源和视觉复读。
- `text_review.py`、`thinking_policy.py`、`image_policy.py`：审核及模型策略。
- `question_media.py`、`figure_refinement.py`、`figure_review.py`：题图定位、裁切和人工复核。
- `bank_cleaning.py`、`bank_versions.py`、`teacher_exports.py`：清洗、版本及导出。

## 上传GitHub

将本目录内容作为仓库根目录上传。请勿混入开发目录的venv、dist、运行数据或实际API配置；`.gitignore`已覆盖常用本地产物。`RELEASE_MANIFEST.json`记录此发布快照的文件哈希。发布副本仅去掉了开发机专用GGUF绝对路径，其余生产模块来自当前fast_dev。
