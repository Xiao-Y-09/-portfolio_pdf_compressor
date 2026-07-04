# Portfolio Compressor · Project Brief (v4.0)

> 本文件是给下一个接手项目的 AI agent 看的（Fable 5 或其他）。
> 目的：基于当前 v3.0 代码库，实现 v4.0 升级。
> 融合了 v1.0、v2.0、v3.0 三个版本的经验教训，以及与竞品（Adobe Acrobat 等手动压缩工具）的对比分析。
> Owner: Xiao Yang · 起草日期: 2026-07

---

## 1. 项目背景

### 1.1 一句话说清楚

面向艺术生/设计生的 PDF 作品集智能压缩工具。用户上传 60-100MB 的作品集 PDF，选择目标大小（5/10/15/20MB），工具在这个大小限制内输出最高质量的压缩结果，**优先保证文字清晰度**，次要保证图片质量。

### 1.2 当前状态（v3.0）

- 已部署：前端 Vercel + 后端 Railway
- 已有：混合策略（compression_ratio > 40% 走 v2 图片级压缩，≤ 40% 走 v1 整页栅格化）
- 已知问题：极端压缩比下（比如 101MB → 10MB）会触发 v1 栅格化，导致**文字变糊**——这是用户感知最强烈的缺陷

### 1.3 v4.0 要解决的核心问题

对比 Adobe Acrobat 手动压缩的作品集样本发现：
- 手动压缩：文字**完美矢量清晰**，图片**能看**，10MB
- 你的 v3.0：文字**明显糊**，图片能看，10MB

**核心洞察：手动工具永远保留矢量文字，通过更激进的图片压缩和字体子集化达到目标大小。用户对文字糊的容忍度远低于图片糊。**

---

## 2. v4.0 核心设计决策

### 2.1 策略调整

**从"混合策略自动切换"转向"始终保留矢量文字"：**

- **v1 栅格化策略**：降级为"极端兜底"，只在 `compression_ratio ≤ 5%` 时才触发（几乎不用）
- **v2 图片级压缩**：作为默认策略，处理 95%+ 的场景
- **保存矢量文字**是不可妥协的核心承诺

### 2.2 用户交互升级

**从"一键压缩"变为"两阶段交互"：**

1. **Phase 1：上传与分析**（后端）
   - 用户上传 PDF
   - 后端扫描：生成每页缩略图 + AI 分类（hero/process）
   - 返回缩略图列表和分类结果

2. **Phase 2：用户 Review**（前端）
   - 展示缩略图 grid
   - AI 预标记已勾选的页面（hero 页默认为"重要"）
   - 用户可修改：勾选/取消勾选任意页
   - 用户确认后提交

3. **Phase 3：按标记压缩**（后端）
   - 用户标"重要"的页面 → 图片走 hero 处理（高 PPI + 高 quality）
   - 用户未标记的页面 → 图片走 process 处理（更激进的压缩）
   - 输出结果

### 2.3 图片压缩改进

**从"标准 JPEG + 分类分配"转向"格式智能选择 + 灰度检测 + 更激进参数"：**

1. **JPEG vs JPEG 2000 智能切换**
   - `quality < 40` 时用 **JPEG 2000**（避免块状伪影）
   - `quality ≥ 40` 时用 **JPEG**（兼容性 + CPU 效率）

2. **灰度图检测**
   - 检测图片 RGB 三通道值是否几乎相同
   - 是 → 转成 Grayscale 单通道（**省 66% 空间**）
   - 否 → 保持 RGB

3. **PPI 阈值调整（更激进）**
   - Hero 图 PPI 上限：**150**（原 200，200 是过度设计）
   - Process 图 PPI 下限：**72**（原 96，更激进）

4. **Quality 阈值调整**
   - 配合 JPEG 2000，process 图最低 quality 可降到 **20**
   - Hero 图最低 quality 保持 **45**

### 2.4 非图片部分压缩

**首次加入字体子集化：**

- **无条件启用** `doc.subset_fonts()`（PyMuPDF 内置）
- 通常可省 **3-8MB**（占 101MB 作品集的 3-8%）
- 这是"释放图片预算"的关键改动

---

## 3. 技术规格

### 3.1 图片处理规则表（后端核心）

| 场景 | 处理规则 |
|---|---|
| 用户标记为"重要页"的图片 | Hero 处理：PPI 150 + quality 60-95（二分搜索） |
| 用户未标记页面的图片 | Process 处理：PPI 72-96 + quality 20-75 |
| 图片检测为灰度 | 转 Grayscale 单通道 |
| 计算得到 quality ≥ 40 | 用 JPEG 编码 |
| 计算得到 quality < 40 | 用 JPEG 2000 编码 |
| 图片降 PPI 后 | 必须同步更新 `/Width` `/Height` 元信息 |
| 图片有 SMask | 合成到白底后 `xref_set_key("SMask", "null")` |
| 图片 < 4096 像素或 < 5KB | 跳过（微型装饰图） |

### 3.2 策略切换规则

```python
compression_ratio = target_size / original_size

if compression_ratio > 0.05:
    strategy = "vector_preserving"  # v2 图片级压缩（默认）
else:
    strategy = "page_rasterization"  # v1 兜底，极少触发
```

### 3.3 压缩流程

```
1. 用户上传 PDF
   ↓
2. 后端 scan_pdf：
   - 提取每页缩略图（低 DPI 渲染）
   - 扫描所有图片元信息
   - 缓存原始图片 bytes
   ↓
3. 后端 classify_pages：
   - 每页分类为 hero / process
   - 返回缩略图 + 分类结果给前端
   ↓
4. 前端展示 Review 界面：
   - Grid 展示所有缩略图
   - hero 页默认勾选"重要"
   - 用户可修改
   ↓
5. 用户确认，前端提交 selected_pages 列表
   ↓
6. 后端 compress：
   - 遍历所有图片
   - 图片所在页在 selected_pages 中 → Hero 参数
   - 否则 → Process 参数
   - 灰度检测 + JPEG/JPEG2000 智能选择
   - 二分搜索 quality 命中目标
   ↓
7. 后端 doc.subset_fonts()  # 字体子集化
   ↓
8. 后端 doc.save(garbage=4, deflate=True, clean=True)
   ↓
9. 返回压缩后 PDF
```

---

## 4. 需求清单

### 4.1 后端改动（Python）

**必做：**

- [ ] **T4.1**：`config.py` 更新配置常量
  - `strategy_switch_ratio: 0.05`（从 0.4 改）
  - `hero_max_ppi: 150`（从 200 改）
  - `process_min_ppi: 72`（从 96 改）
  - `process_min_quality: 20`（从 25 改）
  - `jpeg2000_quality_threshold: 40`（新增）
  - `enable_font_subsetting: True`（新增）
  - `enable_grayscale_detection: True`（新增）

- [ ] **T4.2**：`pdf_io.py` 加入缩略图生成
  - `generate_thumbnails(doc) -> list[bytes]`：每页低 DPI 渲染为 JPEG bytes
  - 返回 base64 编码字符串给前端展示

- [ ] **T4.3**：`strategy_v2.py` 加入灰度检测
  - `is_grayscale_image(pil_img) -> bool`：判断 RGB 三通道是否几乎相同
  - 若是 → `pil_img.convert("L")` 转单通道

- [ ] **T4.4**：`strategy_v2.py` 加入 JPEG 2000 支持
  - 根据 quality 阈值决定 format
  - `pil_img.save(buffer, format="JPEG2000", quality_mode="rates", quality_layers=[compression_ratio])`
  - 注意：JPEG 2000 的 quality 参数与 JPEG 不同，需要转换

- [ ] **T4.5**：`strategy_v2.py` 支持用户 selected_pages
  - 修改 `compress_v2` 签名：`compress_v2(doc, images, cfg, selected_pages: set[int] | None)`
  - 若图片所在页在 `selected_pages` 中 → 强制 hero 参数
  - 若 `selected_pages` 为 None → fallback 到 AI 分类

- [ ] **T4.6**：`pipeline.py` 更新流程
  - 新增函数 `run_analysis(pdf_path) -> AnalysisResult`（返回缩略图 + 分类）
  - 修改函数 `run_compression(pdf_path, selected_pages, target_mb) -> bytes`
  - 更新策略切换阈值

- [ ] **T4.7**：`pipeline.py` 集成字体子集化
  - 压缩完图片后、保存前调用 `doc.subset_fonts()`
  - 加 try/except 保护（字体子集化失败不应导致整体失败）

- [ ] **T4.8**：`server/routes.py` 拆分为两阶段 API
  - `POST /api/jobs` 现在只做上传 + 分析，返回 job_id + 缩略图 + 分类
  - `POST /api/jobs/{id}/confirm` 接收 selected_pages，触发压缩
  - `GET /api/jobs/{id}` 返回压缩进度和结果
  - `GET /api/jobs/{id}/download` 下载压缩后文件

**保留不变：**

- [ ] hero/process 分类算法（AI）
- [ ] 二分搜索 quality 逻辑
- [ ] 精确目标大小控制
- [ ] `garbage=4, deflate=True, clean=True` 保存
- [ ] 所有已知坑的处理（Width/Height 同步、SMask 处理、xref 检查等）

### 4.2 前端改动（Next.js + TypeScript）

**必做：**

- [ ] **T4.9**：`app/page.tsx` 拆分为多阶段流程
  - Phase 1：上传文件 + 选择目标大小
  - Phase 2：Review 界面（缩略图 grid）
  - Phase 3：压缩进度
  - Phase 4：下载结果

- [ ] **T4.10**：新建 `app/components/ThumbnailGrid.tsx`
  - Props：`thumbnails: string[]`（base64）、`classifications: PageType[]`、`onSelectionChange`
  - 每个缩略图带 checkbox
  - AI 分类为 hero 的默认已勾选
  - 显示页码、"AI 建议：重要 / 一般"标签
  - 支持"全选 / 全不选 / 反选"

- [ ] **T4.11**：更新 API 调用逻辑
  - 上传 → 轮询 analysis → 展示 review → 提交 confirm → 轮询 compression → 下载
  - 加载状态、错误处理

- [ ] **T4.12**：UI 视觉升级（参考 Smallpdf 风格）
  - 更干净的排版
  - 更明显的品牌感（可以用一个简单的 logo）
  - Review 页面的缩略图 grid 要美观（阴影、间距、hover 效果）
  - 移动端响应式

**保留不变：**

- [ ] Next.js 16 + Tailwind v4 技术栈
- [ ] 拖拽上传交互
- [ ] 目标大小选择（5/10/15/20 MB）

### 4.3 明确不做

- ❌ 用户账户 / 登录 / 数据库
- ❌ 支付 / 订阅
- ❌ Cloud 存储
- ❌ 多语言 i18n（先只做英文）
- ❌ Ghostscript 或其他外部依赖
- ❌ 视觉大模型（Gemma、CLIP 等）
- ❌ 图片级 review（用户 toggle 每张图）——太复杂，只做页面级

---

## 5. 数据模型

### 5.1 新增：`AnalysisResult`

```python
class AnalysisResult(BaseModel):
    job_id: str
    page_count: int
    original_size_mb: float
    thumbnails: list[str]  # base64 encoded JPEG bytes
    page_classifications: list[PageType]  # HERO or PROCESS per page
    ai_suggested_pages: list[int]  # 页码列表，AI 建议的重要页
```

### 5.2 修改：`CompressionRequest`

```python
class CompressionRequest(BaseModel):
    target_size_mb: float
    selected_pages: list[int]  # 用户标记的重要页页码（1-indexed）
```

### 5.3 修改：`ImageInfo`（保留 v3.0 的字段，无变化）

### 5.4 修改：`CompressionConfig`

```python
class CompressionConfig(BaseModel):
    target_size_mb: float
    tolerance_mb: float = 0.3

    # 策略切换（v4.0 更保守）
    strategy_switch_ratio: float = 0.05  # 从 0.4 改
    
    # 图片级压缩参数
    hero_max_ppi: int = 150  # 从 200 改
    hero_min_ppi: int = 120
    process_min_ppi: int = 72  # 从 96 改
    process_max_ppi: int = 96
    
    hero_max_quality: int = 95
    hero_min_quality: int = 45
    process_max_quality: int = 75
    process_min_quality: int = 20  # 从 25 改
    
    # v4.0 新增
    jpeg2000_quality_threshold: int = 40
    enable_font_subsetting: bool = True
    enable_grayscale_detection: bool = True
    grayscale_channel_diff_threshold: int = 5  # RGB 三通道差异阈值
    
    # 保存选项
    garbage_level: int = 4
    deflate: bool = True
    clean: bool = True
    
    # 二分搜索
    max_iterations_per_image: int = 8
```

---

## 6. 已知的坑（务必保留）

v3.0 已经踩过并修复了这些坑，v4.0 必须继续避免：

### 坑 1：图片 xref 不都是标准 stream
- 症状：`update_stream` 报 `object is no PDF dict`
- 解决：调用前 `if not doc.xref_is_stream(xref): continue`

### 坑 2：图片降 PPI 后 Width/Height 不同步
- 症状：图片下半部显示为红色/黑色方块
- 解决：`update_stream` 后必须 `xref_set_key(xref, "Width", ...)` 和 Height

### 坑 3：SMask 处理不当
- 症状：透明图片压缩后完全变白
- 解决：合成到白底后 `xref_set_key(xref, "SMask", "null")`

### 坑 4：`tobytes(garbage=4)` 使 xref 失效
- 症状：测量大小后再压缩报 bad xref
- 解决：在快照副本上做测量，原文档不动

### 坑 5：从压过的图再压无法恢复质量
- 症状：想给 hero 图回调质量却上不去
- 解决：`scan_pdf` 阶段把 `original_data` 缓存到内存

### 坑 6：微型图片浪费流程时间
- 症状：一页 100+ 张 3x2 装饰元素
- 解决：过滤 `width * height < 4096` 或 `bytes < 5120`

### 坑 7：字体子集化可能失败（v4.0 新增）
- 症状：`doc.subset_fonts()` 报错，比如遇到无法识别的字体
- 解决：用 try/except 包裹，失败时打 log 并跳过，不阻断整体压缩

### 坑 8：JPEG 2000 参数与 JPEG 不同（v4.0 新增）
- JPEG：`quality=50` 是常见参数
- JPEG 2000：用 `quality_mode="rates"` + `quality_layers=[N]`（N 是压缩率）
- 需要建立 JPEG quality → JPEG2000 rate 的映射表

---

## 7. 项目文件结构

保持 v3.0 的结构，新增/修改标记：

```
portfolio-compressor/
├── PROJECT_BRIEF.md               # (被此 v4 版本替换)
├── PROJECT_BRIEF_v4.md            # (本文件)
├── PROGRESS.md                    # agent 每完成一步更新
├── README.md
├── pyproject.toml
├── .python-version                # 3.11
├── .gitignore
│
├── src/
│   └── compressor/
│       ├── __init__.py
│       ├── cli.py                 # (轻微修改，支持 --selected-pages)
│       ├── pipeline.py            # (重大修改，拆分 analysis/compression)
│       ├── config.py              # (修改，加 v4.0 参数)
│       ├── schemas.py             # (修改，加 AnalysisResult 等)
│       ├── exceptions.py
│       │
│       ├── strategy_v1.py         # (保留，作为兜底)
│       ├── strategy_v2.py         # (重大修改，加灰度检测/JPEG2000/selected_pages)
│       │
│       ├── pdf_io.py              # (修改，加缩略图生成)
│       └── classifier.py          # (保留)
│
├── server/
│   ├── main.py                    # (保留)
│   ├── routes.py                  # (重大修改，拆分为 analysis + confirm)
│   ├── jobs.py                    # (修改，job 状态机加"waiting_confirm")
│   └── ratelimit.py               # (保留)
│
├── web/
│   ├── app/
│   │   ├── page.tsx               # (重大修改，多阶段流程)
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   └── components/
│   │       ├── ThumbnailGrid.tsx  # (新建)
│   │       ├── UploadZone.tsx     # (新建，从 page.tsx 拆出)
│   │       └── ProgressBar.tsx    # (新建)
│   ├── vercel.json                # (保留)
│   ├── package.json               # (保留)
│   └── ...
│
├── tests/
│   ├── conftest.py
│   ├── test_pdf_io.py
│   ├── test_classifier.py
│   ├── test_strategy_v1.py
│   ├── test_strategy_v2.py        # (修改，加灰度/JPEG2000/selected_pages 测试)
│   ├── test_pipeline.py           # (修改，测试两阶段流程)
│   └── test_server.py             # (修改，测试新 API)
│
├── Dockerfile                     # (保留)
└── data/
    ├── uploads/
    ├── outputs/
    └── logs/
```

---

## 8. Agent 强制约束

### 一定要做

1. **每次改动前先读 PROJECT_BRIEF_v4.md 相关章节**
2. **每完成一个 T 任务在 PROGRESS.md 打勾并简短记录做了什么**
3. **所有函数标注 Python 3.11 style type hints**（`list[int]` 不是 `List[int]`）
4. **用 Pydantic 而不是 dataclass**
5. **异常用自定义类**（`CompressionError`, `ClassificationError`, `PDFParseError`）
6. **所有阈值/权重放 `config.py`**，不 hardcode
7. **写代码前先给 owner 3-5 句的实现计划，等确认再写**
8. **不确定时问，不要自由发挥**
9. **改完立即跑相关测试**
10. **v3.0 已经踩过的 8 个坑必须全部保留处理**

### 一定不要做

1. ❌ 不引入禁做的功能（账户、支付、DB 等）
2. ❌ 不装 pyproject.toml 里没写的库，需要新库先问
3. ❌ 不写 500+ 行的单文件，超过就拆
4. ❌ 不写没有测试的复杂逻辑
5. ❌ **绝对不加"兼容壳"或"兼容别名"**——v2.0 因为这个吃了很多苦
6. ❌ 不删除 v3.0 已经工作的功能，除非明确要求（如 v1 策略降级）
7. ❌ 不改本文件，需要改设计先和 owner 讨论

### 代码风格

- Python: black + ruff 默认
- 命名: `snake_case` 函数变量, `PascalCase` 类, `SCREAMING_SNAKE_CASE` 常量
- 注释：中英混合都可以，公共 API 的 docstring 用英文
- 不写多余注释

---

## 9. 分阶段实施

**Phase A：后端核心（先做，因为影响所有）**
- T4.1 Config 更新
- T4.7 字体子集化（**先做这个，一行代码，立刻见效**）
- T4.3 灰度检测
- T4.4 JPEG 2000
- 测试：用 Xiang_Yi_Portfolio.pdf（101MB）压到 10MB，验证文字清晰

**Phase B：两阶段流程（后端）**
- T4.2 缩略图生成
- T4.5 支持 selected_pages
- T4.6 pipeline 拆分
- T4.8 API 拆分
- 测试：curl 走完整两阶段流程

**Phase C：前端 Review 界面**
- T4.9 多阶段流程
- T4.10 ThumbnailGrid 组件
- T4.11 API 调用逻辑
- 测试：本地开发环境走通

**Phase D：UI 视觉升级**
- T4.12 参考 Smallpdf 风格调整
- 移动端适配
- 部署到 Vercel

---

## 10. 测试策略

### 单元测试

- `test_strategy_v2.py`：
  - 加：灰度图检测函数测试
  - 加：JPEG vs JPEG 2000 切换测试
  - 加：selected_pages 影响预算分配的测试

- `test_pipeline.py`：
  - 加：run_analysis 返回结构测试
  - 加：字体子集化前后大小对比测试

### 集成测试

- **关键测试**：用 `Xiang_Yi_Portfolio.pdf`（101MB）
  - 目标 5MB：文字清晰、图片能看
  - 目标 10MB：文字清晰、图片较好
  - 目标 15MB：文字清晰、图片好
  - 目标 20MB：文字清晰、图片很好
  - 全程无 v1 栅格化触发
  - 每次输出大小 ∈ [target - 0.3MB, target]

### 人工验证

- 打开压缩后 PDF，Chrome / Adobe Reader / macOS Preview
- 无红色方块、无图片截断、无白屏
- 缩放到 400% 检查文字是否仍为矢量清晰

---

## 11. 提示词模板（agent 使用）

Owner 在 VSCode 里唤起 agent 时，通常这样开头：

```
读 PROJECT_BRIEF_v4.md 里 Section [X] 和 T4.[Y] 的要求。
先给我一个 3-5 句话的实现计划，不要写代码。
我确认后你再写。
```

或者：

```
按 PROJECT_BRIEF_v4.md T4.7 实现字体子集化。
先展示改动的文件和函数 signature，我 review 后你再填函数体。
```

---

_End of PROJECT_BRIEF_v4.md_