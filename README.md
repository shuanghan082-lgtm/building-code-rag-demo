# 建筑规范条文检索与模型导读 Demo

个人独立开发的 AI 大模型应用作品集项目。它把真实规范资料的**来源校验 → 条文切分 → 检索 → 带出处展示 → 可选模型导读 → 离线评测**连成一条可运行流程。目标是帮助定位原文；**不作建筑设计合规判断，也不能代替现行规范核验与专业审查**。

当前可运行的主语料是《民用建筑通用规范》GB 55031-2022 的[北京市规划和自然资源委员会公开 PDF](https://ghzrzyw.beijing.gov.cn/biaozhunguanli/bzzl/202209/P020220929592779805981.pdf)中的第 12–16 页，共提取 47 个带编号的节选条文。该 PDF 同时包含其他标准，**这 5 页不是规范全文**。项目会校验整个来源 PDF 的 SHA-256；若文件内容变化，会停止运行而不是沿用旧页码和评测结果。规范的现行状态及具体适用条件仍须另行核对。

另有[三明市住建局公开的完整扫描版 PDF](https://zjj.sm.gov.cn/xxgk/fgwj/jsbz/202209/P020220909629255603704.pdf)的独立 OCR 导入工具。24 页扫描版可用于**试验性页码定位**，但 OCR 正文、表格及跨页条文尚未逐条人工核验，**没有进入条文回答或模型导读语料**。详见 [来源检查](SOURCE_AUDIT.md)与[核验流程](QA_PROTOCOL.md)。

## 已实现的链路

```text
政府节选 PDF ── SHA-256 校验 ── PyMuPDF 提取 ── 条文号与 PDF 页码
                                              │
                    ┌──────── 字符 n-gram / BM25 风格检索（离线）
                    └──────── 可选嵌入 API → 本地向量文件 → 余弦检索
                                              │
                         候选条文 + 官方 PDF 原页链接
                                              │
                         可选聊天模型 → JSON 导读 → 引用与数值检查

完整扫描版 PDF ── SHA-256 校验 ── 三组 OCR 观察 ── 独立页码定位
                                                   └── 不输出 OCR 正文答案
```

- 默认字词检索无需模型或付费 API。可选向量模式通过兼容 Embeddings 的接口创建本地索引，索引绑定语料指纹与模型名；文档或模型变化必须重建。47 条语料采用精确余弦计算，没有使用 FAISS。
- 可选模型导读通过兼容 Chat Completions 的接口调用模型。返回的条文号必须属于本次检索结果；回答出现引用中没有的数值/单位会被拦截。**这些是程序级检查，不保证语义正确或法规范畴正确**，因此界面始终标为“待核验”。
- 本地 FastAPI 网页展示候选条文、PDF 页码、原页链接和资料边界；浏览器不会获取 API 密钥。选择模型导读时，检索到的条文文字会发送给用户配置的模型服务。
- 可选加载完整扫描版的 OCR 观察文件，在同一网页中查找**候选原页**；此入口只给出 PDF 页码和候选编号，不生成条文答案，也不能宣称已验证全文覆盖。
- 29 道自编离线题的基线评测与失败样例见 [评测记录](EVALUATION.md)。评测只测节选内的检索定位，不测生成答案正确率。
- [自动测试](.github/workflows/ci.yml)在 Linux/Python 3.10 和 Windows/Python 3.13 上运行合成语料与模拟接口测试，不下载规范 PDF，也不需要 API 密钥；线上测试是否通过，以仓库实际运行记录为准。

## Windows 快速运行

在本项目目录打开终端，使用 Python 3.10 或更新版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web]"
.\.venv\Scripts\python.exe -m building_code_demo.demo prepare
.\.venv\Scripts\python.exe -m building_code_demo.demo serve --pdf data\official_excerpt.pdf
```

浏览器打开 `http://127.0.0.1:8765`。`prepare` 从政府链接下载 PDF 到被 Git 忽略的 `data/`，只接受已核对的 SHA-256。如果政府文件已更新，它会停止并要求重新检查；也可自行从上方政府链接获取相同 PDF，放入 `data/official_excerpt.pdf`。不要把 PDF 提交到公开仓库。

离线命令与评测：

```powershell
.\.venv\Scripts\python.exe -m building_code_demo.demo search --pdf data\official_excerpt.pdf --query "阳台栏杆高度"
.\.venv\Scripts\python.exe -m building_code_demo.demo eval --pdf data\official_excerpt.pdf
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

评测明细保存在本地 `data/eval_report.json`，包括每题的预期条文、实际 Top-3 和失败案例。

## 可选模型与向量检索

没有密钥时，离线检索与评测可正常运行；模型导读按钮保持关闭。需要模型时安装可选依赖，并在本机环境中设置 `RAG_API_KEY`、`RAG_CHAT_MODEL`。`RAG_BASE_URL` 可指定兼容接口地址；未设置时使用 SDK 默认端点。也接受 `OPENAI_API_KEY` 作为密钥。不要提交密钥或真实 `.env`。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,llm]"
$env:RAG_API_KEY = "在本机设置自己的密钥"
$env:RAG_CHAT_MODEL = "填写实际可用的聊天模型名"
.\.venv\Scripts\python.exe -m building_code_demo.demo serve --pdf data\official_excerpt.pdf
```

向量检索还需设置实际可用的 `RAG_EMBED_MODEL`，然后运行：

```powershell
.\.venv\Scripts\python.exe -m building_code_demo.demo index --pdf data\official_excerpt.pdf
.\.venv\Scripts\python.exe -m building_code_demo.demo serve --pdf data\official_excerpt.pdf --mode vector
```

嵌入和聊天接口按[OpenAI 官方 Embeddings 文档](https://developers.openai.com/api/docs/guides/embeddings)及[Chat Completions API 参考](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions/methods/create)实现；其他供应商的兼容程度须用其实际服务单独验证。当前已用本地模拟 HTTP 服务验证请求与响应链路，**尚未用真实付费模型运行，也没有向量检索效果指标**。

## 扫描版全文的研究分支

完整扫描版只作为独立页码定位与核验分支。复现命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,ocr]"
.\.venv\Scripts\python.exe -m building_code_demo.demo prepare --source full
.\.venv\Scripts\python.exe -m building_code_demo.ocr_import --pdf data\full_standard.pdf --source-url "https://zjj.sm.gov.cn/xxgk/fgwj/jsbz/202209/P020220909629255603704.pdf"
.\.venv\Scripts\python.exe -m building_code_demo.demo scan-search --ocr data\full_standard.ocr.json --query "阳台栏杆高度"
.\.venv\Scripts\python.exe -m building_code_demo.demo serve --pdf data\official_excerpt.pdf --ocr-catalog data\full_standard.ocr.json
```

OCR 三组图像处理结果以 `unverified_ocr_observations` 状态保存在被忽略的 `data/`。运行 `python -m building_code_demo.review_queue --ocr data/full_standard.ocr.json` 可生成待核验清单。页码定位使用 OCR 文字近似匹配，**未做正式定位评测**；候选编号数量不是规范全文条文数或识别准确率。原始 PDF、OCR 全文、向量文件与人工誊录正文均不随代码仓库发布。

## 当前限制

节选的文字层存在数字字体映射错误，表格结构也不能保证准确。检索命中只代表候选，链接中的 PDF 页码是**文件页序**，可能不同于规范印刷页码。扫描版页码定位也会给出无关页面，不能被当成全文条文检索质量。模型引用检查不能证明回答真的被条文支持；界面要求用户打开原页核对。当前没有完整规范可验证的条文答案、线上部署、真实用户数据、模型回答准确率或可用于简历的业务收益数字。
