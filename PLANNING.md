# Portfolio Compressor · Project Brief (v3.0)

> 这份文档是给下一个接手项目的 AI agent 看的。
> 目的：让 agent 在没有任何上下文的情况下，理解**做什么、为什么、以及绝对不要做什么**。
> 融合了 v1.0（整页栅格化）和 v2.0（图片级压缩）两个版本的所有经验教训。
> Owner: Xiao Yang · 起草日期: 2026-07

---

## 1. 一句话说清楚这个项目

**面向艺术生/设计生的 PDF 作品集智能压缩工具。用户上传 60-100MB 的作品集 PDF，选择目标大小（5/10/15/20MB），工具在这个大小限制内输出最高质量的压缩结果。**

核心卖点：**在硬性大小限制下，最大化视觉质量**（尤其是关键图片的清晰度）。

---

## 2. 用户是谁，他们为什么需要这个工具

**目标用户**：递交留学申请或求职的艺术生、建筑生、设计生。

**他们的困境**：
- 学校/公司系统硬性要求作品集不超过 5/10/15/20MB
- 他们的作品集通常 60-100MB（InDesign/Illustrator 导出，含高分辨率渲染图）
- 市面上的免费工具（Pi7、Imresizer、ToolShelf 等）都是一刀切降低全局质量，关键效果图和填充页面被同等程度压缩
- 付费工具太贵（Adobe Acrobat Pro）或功能不专业（针对普通文档，不懂作品集）

**他们最在意的顺序**：
1. **一定要压到目标大小以下**（这是硬性要求，压不下去直接废掉，卖点就在这里）
2. **关键图片（渲染图、效果图）清晰**（作品集的核心价值）
3. **文字可读**（次要，但不能完全糊掉）
4. **时间**（60-120 秒可以接受，不是核心痛点）

---

## 3. 用户上传的 PDF 长什么样（重要）

**典型文件特征**：
- 由 Adobe InDesign 或 Illustrator 导出
- 30-60 页
- 60-100MB
- 内容混合：
  - **矢量文字**（页面说明、标题、图注）
  - **矢量线稿**（Illustrator 画的技术图、平面图、hatch pattern）
  - **PNG/JPEG 渲染图**（3D 效果图，通常带透明 smask）
  - **单反相机拍的实景照片**
  - **偶尔有整页大图**（作品展示页）

**典型页面布局**：
- 一半图 + 一半文字说明
- 或几张图 + 文字标注
- 或线稿 + 说明
- **很少是"整页都是一张大图"**

**PDF 内部结构的关键事实**（v2.0 踩过坑）：
- 图片对象可能有 `SMask`（透明遮罩），SMask 本身是独立的 PDF 对象
- 有些 xref 通过 `page.get_images()` 返回，但不是标准的 stream 对象（inline image、form XObject 等），无法用 `update_stream` 写回
- 图片对象的 `/Width` `/Height` 元信息独立存储，修改图片流后必须同步更新，否则渲染会截断
- 修改后必须用 `garbage=4, deflate=True, clean=True` 保存才能真正清理孤立对象

---

## 4. 两次尝试的经验教训（务必阅读）

### v1.0：整页栅格化压缩

**做法**：把每一页整体渲染成一张 JPEG，通过分类（hero/process）给每页不同的 quality，二分搜索找到能命中目标大小的全局 quality multiplier。

**优点**：
- ✅ 大小控制精确
- ✅ 逻辑简单，稳定
- ✅ 图片画质在极端压缩比下依然可用（因为每页有相对充足的字节预算）

**缺点**：
- ❌ 文字变成像素，放大明显糊化
- ❌ 矢量线稿失去清晰度
- ❌ 分类粒度太粗（页面级）

### v2.0：图片级压缩

**做法**：只压缩 PDF 里的嵌入图片对象，保留矢量文字和线稿。按图片级 hero/process 分类，按显示面积和分类权重分配预算，先降 PPI 再降 quality。

**优点**：
- ✅ 文字保持矢量清晰度
- ✅ 图片级精细控制
- ✅ 温和压缩比（原大小的 30-50%）下效果非常好

**致命缺点**：
- ❌ 极端压缩比下（原大小的 20% 以下）非图片开销占目标预算太多，图片能用的预算几乎没有，画质惨不忍睹
- ❌ 大量边界情况：SMask 处理、非标准 xref、update_stream 后 Width/Height 不同步导致图片截断显示红色/黑色方块
- ❌ 修图片元信息（/Width /Height /Filter /ColorSpace）容易出错，任何一处遗漏都会渲染错乱

### v3.0（本项目）要做的是

**根据目标压缩比自动切换策略：**
- **温和压缩**（目标 > 原始的 40%）：走 v2.0 路径，保留矢量文字，只压图片
- **激进压缩**（目标 <= 原始的 40%）：走 v1.0 路径，整页栅格化

这样在两种场景下都能给出最优质量。

---

## 5. v3.0 的核心架构决策

### 决策 1：混合策略，自动切换

不让用户选"高质量/低质量"这种模糊的档位，而是**根据文件大小和目标大小的比例自动决定**：

```python
compression_ratio = target_size / original_size

if compression_ratio > 0.4:
    strategy = "vector_preserving"  # v2.0 路径
else:
    strategy = "page_rasterization"  # v1.0 路径
```

这个阈值（0.4）需要在实际测试中调整。

### 决策 2：不为了减少非图片开销做字体子集化

看起来字体子集化能省 2-5MB 的非图片开销，但：
- PyMuPDF 支持不完善
- 增加代码复杂度和 bug 面
- 阈值切换到 v1.0 路径本身就绕开了这个问题

**不做。**

### 决策 3：不集成 Ghostscript

虽然 Ghostscript 更成熟，但：
- 增加部署依赖
- 不能精确控制目标大小（只有档位）
- 用二分搜索 Ghostscript 参数会让流程慢 3-5 倍

**不做。用纯 PyMuPDF + Pillow 完成所有压缩工作。**

### 决策 4：分类保留，但作用于策略选择

hero/process 分类的价值：
- 在 v1.0 路径下，决定每页的 quality（hero 页高，process 页低）
- 在 v2.0 路径下，决定每张图的预算（hero 图多分配，process 图少）

分类算法用 OpenCV 启发式（v2.0 已经跑通），不引入视觉大模型。

---

## 6. 技术栈约束（必用）

**后端**（不变）：
- Python 3.11+
- FastAPI + Uvicorn
- PyMuPDF (`import fitz`)
- OpenCV + Pillow
- Pydantic v2
- pytest

**前端**（Phase 2）：
- Next.js 14+ App Router
- Tailwind + shadcn/ui

**禁用**：
- ❌ Ghostscript / mutool 等外部命令
- ❌ Django / Flask
- ❌ pypdf / pdfplumber / pikepdf（用 PyMuPDF 一个库就够）
- ❌ Celery / Redis / 任何消息队列
- ❌ SQLAlchemy / 任何 ORM
- ❌ 任何视觉大模型（Gemma、CLIP 等）

---

## 7. MVP 范围

### 一定要做

- [ ] CLI 工具：`python -m compressor input.pdf --target 15 --output out.pdf`
- [ ] 混合策略：根据压缩比自动选择 v1.0 或 v2.0 路径
- [ ] v1.0 路径：整页栅格化，页面级 hero/process 分类，quality 二分搜索
- [ ] v2.0 路径：图片级压缩，图片级 hero/process 分类，预算分配 + PPI 降级 + JPEG quality 二分搜索
- [ ] FastAPI 服务层
- [ ] 简单 Next.js 前端（上传 → 选大小 → 下载）
- [ ] IP-based 限流

### 明确不做

- [ ] 用户账户 / 登录 / 数据库
- [ ] 支付 / 订阅
- [ ] Cloud 存储
- [ ] 图片级 review（用户单独 toggle 每张图）——太复杂，v2.0 试过，UI 负担大
- [ ] 页面级 review（用户 toggle 每页）——先跳过，MVP 直接用 AI 分类
- [ ] i18n / 多语言
- [ ] 花哨动画

**⚠️ 如果 agent 想加以上任何一项，拒绝。**

---

## 8. 已知的坑（v2.0 血泪教训）

**agent 必须避免这些错误：**

### 坑 1：PDF 图片对象不都是标准 stream
- 症状：`doc.update_stream(xref)` 抛 `object is no PDF dict`
- 原因：`page.get_images()` 返回的 xref 中，部分是 inline image 或 form XObject 引用
- 解决：调用前先 `if not doc.xref_is_stream(xref): continue`

### 坑 2：图片降 PPI 后 Width/Height 不同步
- 症状：PDF 打开后图片下半部分显示为红色/黑色方块
- 原因：`update_stream` 只更新数据流，PDF 对象里的 `/Width` `/Height` 还是旧值
- 解决：`update_stream` 之后必须 `doc.xref_set_key(xref, "Width", str(new_w))` 和同样的 Height

### 坑 3：SMask 处理不当会破坏渲染
- 症状：带透明的图片压缩后完全变白或显示异常
- 原因：把 RGBA 合成到白底转 JPEG 后，原来的 SMask 引用还在，PDF 阅读器仍然按透明处理
- 解决：合成到白底后必须 `doc.xref_set_key(xref, "SMask", "null")` 解除 SMask 引用

### 坑 4：中间保存和最终保存的大小差异
- 症状：`global_adjust` 每轮测量的大小是 20MB，最终输出却是 11MB
- 原因：`doc.tobytes(garbage=0)` 保留孤立对象，`garbage=4` 清理后大小骤降
- 解决：任何时候需要测量大小，都用 `doc.tobytes(garbage=4, deflate=True, clean=True)`

### 坑 5：从压过的图再压无法恢复质量
- 症状：`global_adjust` 想给 hero 图回调质量，但输出永远上不去
- 原因：`doc.extract_image(xref)` 返回的是当前 PDF 里的图片，已经被前一轮压缩过了
- 解决：`scan_pdf` 阶段把每张图的**原始字节流缓存到内存**（存到 `ImageInfo.original_data`），之后所有压缩都从原始数据开始

### 坑 6：极端压缩比下 v2.0 策略失效
- 症状：71MB 压到 10MB，图片全糊
- 原因：非图片开销就占 8MB+，图片能用的预算只有 1-2MB
- 解决：**这不是 bug 是物理限制**。当 compression_ratio <= 0.4 时切换到 v1.0 路径（整页栅格化）

### 坑 7：微型图片浪费流程时间
- 症状：一页有 100+ 张 3x2 到 30x30 像素的装饰元素
- 解决：`scan_pdf` 阶段过滤掉 `width * height < 4096` 或 `bytes < 5120` 的图片

---

## 9. 项目文件结构

```
portfolio-compressor/
├── PROJECT_BRIEF.md               # 本文件
├── PROGRESS.md                    # agent 每完成一步在这里打勾
├── README.md                      # 用户 facing 文档
├── pyproject.toml
├── .python-version                # 3.11
├── .gitignore
│
├── src/
│   └── compressor/
│       ├── __init__.py
│       ├── cli.py                 # CLI 入口
│       ├── pipeline.py            # 总编排，根据压缩比选择策略
│       ├── config.py              # 常量、阈值、权重
│       ├── schemas.py             # Pydantic 数据模型
│       ├── exceptions.py          # 自定义异常
│       │
│       ├── strategy_v1.py         # 整页栅格化策略（激进压缩）
│       ├── strategy_v2.py         # 图片级压缩策略（温和压缩）
│       │
│       ├── pdf_io.py              # PDF 扫描、图片提取、缩略图生成
│       └── classifier.py          # 分类（图片级 + 页面级两套接口）
│
├── server/
│   ├── main.py                    # FastAPI app
│   ├── routes.py                  # API endpoints
│   ├── jobs.py                    # in-memory job manager
│   └── ratelimit.py
│
├── web/                           # Next.js (Phase 2)
│
├── tests/
│   ├── conftest.py                # 合成 PDF fixtures
│   ├── test_pdf_io.py
│   ├── test_classifier.py
│   ├── test_strategy_v1.py
│   ├── test_strategy_v2.py
│   └── test_pipeline.py           # 端到端 + 策略切换测试
│
└── data/                          # gitignored
    ├── uploads/
    ├── outputs/
    └── logs/
```

---

## 10. 分阶段实施

### Phase 0：核心库（CLI 能跑通）

按顺序做，每个 Task 完成前不要开始下一个：

- [ ] Task 0.1：项目初始化，目录结构，pyproject.toml
- [ ] Task 0.2：`schemas.py` 数据模型
- [ ] Task 0.3：`config.py` 所有常量集中
- [ ] Task 0.4：`pdf_io.py` 扫描 + 提取 + 元信息读取
- [ ] Task 0.5：`classifier.py` 图片级 + 页面级分类
- [ ] Task 0.6：`strategy_v2.py` 图片级压缩（温和场景）
- [ ] Task 0.7：`strategy_v1.py` 整页栅格化（激进场景）
- [ ] Task 0.8：`pipeline.py` 根据压缩比选择策略
- [ ] Task 0.9：`cli.py` 命令行入口
- [ ] Task 0.10：pytest 覆盖两条策略路径 + 切换逻辑
- [ ] Task 0.11：用真实作品集测试（在 `tests/fixtures/portfolio_1.pdf`）

**验收标准**：
- 60-100MB 作品集压到 5/10/15/20MB 任意目标，都能落在 [target - 0.3MB, target] 区间
- 压缩后 PDF 用 Chrome/Adobe Reader 打开没有红色方块、图片截断、白屏
- 文字在温和压缩下保持矢量清晰
- 图片在激进压缩下不会糊到不能辨认

### Phase 1：FastAPI 服务层

（略，参考 v2.0 PLANNING.md 的 Phase 1）

### Phase 2：Next.js 前端

（略，参考 v2.0 PLANNING.md 的 Phase 2）

---

## 11. 数据模型概要

### ImageInfo（v2.0 路径用）

```python
class ImageInfo(BaseModel):
    xref: int
    page_num: int
    original_bytes: int
    original_data: bytes = Field(default=b"", exclude=True)  # 缓存原始数据，避免"从压过的图再压"
    original_smask_data: bytes = Field(default=b"", exclude=True)
    smask_xref: int = 0
    pixel_width: int
    pixel_height: int
    format: str
    display_rect: tuple[float, float, float, float]
    display_ratio: float
    effective_ppi: float
    classification: PageType = PageType.PROCESS
    confidence: float = 0.5
```

### PageInfo（v1.0 路径用）

```python
class PageInfo(BaseModel):
    page_num: int
    page_type: PageType
    confidence: float
    image_array: np.ndarray = Field(exclude=True)  # 整页渲染的 numpy array
```

### CompressionConfig

```python
class CompressionConfig(BaseModel):
    target_size_mb: float
    tolerance_mb: float = 0.3

    # 策略切换阈值
    strategy_switch_ratio: float = 0.4  # compression_ratio <= 0.4 时切到 v1.0
    
    # v2.0 路径参数（PPI + quality）
    max_ppi: int = 200
    hero_min_ppi: int = 150
    process_min_ppi: int = 96
    hero_max_quality: int = 92
    process_max_quality: int = 75
    hero_min_quality: int = 45
    process_min_quality: int = 25
    small_image_quality_floor: int = 20
    
    # v1.0 路径参数（整页栅格化）
    render_dpi: int = 200
    hero_base_quality: int = 90
    process_base_quality: int = 55
    hero_min_quality_v1: int = 50
    process_min_quality_v1: int = 20
    
    # 权重（两条路径共用）
    hero_label_weight: float = 1.0
    process_label_weight: float = 0.4
    large_size_weight: float = 1.0
    medium_size_weight: float = 0.6
    small_size_weight: float = 0.3
    
    # 保存选项
    garbage_level: int = 4
    deflate: bool = True
    clean: bool = True
    
    # 二分搜索
    max_iterations_per_image: int = 8
    max_global_adjust_rounds: int = 5
```

---

## 12. Agent 必须遵守的强制约束

### 一定要做

1. **每次修改前先读 PROJECT_BRIEF.md 相关章节**
2. **每完成一个 Task 在 PROGRESS.md 打勾并简短记录做了什么**
3. **每个 module 顶部写 docstring**
4. **所有函数标注 Python 3.11 style type hints**（`list[int]` 不是 `List[int]`）
5. **用 Pydantic 而不是 dataclass**
6. **异常用自定义类**（`CompressionError`, `ClassificationError`, `PDFParseError`）
7. **所有阈值/权重放 `config.py`**，不要 hardcode 在业务代码里
8. **写代码前先给我 3-5 句的实现计划，等我确认再写**
9. **不确定时问，不要自由发挥**
10. **改完立即跑相关测试，不要"改完再说"**

### 一定不要做

1. ❌ 不引入 non-goals 里的功能（账户、支付、DB 等）
2. ❌ 不装 pyproject.toml 里没写的库，需要新库先问
3. ❌ 不写 500+ 行的单文件，超过就拆
4. ❌ 不写没有测试的复杂逻辑
5. ❌ **绝对不加"兼容壳"或"兼容别名"**——旧代码删了就是删了，v2.0 因为这个吃了很多苦
6. ❌ 不用 emoji 在 commit message 或代码注释里
7. ❌ 不生成大段 TODO 注释就交差
8. ❌ 不改 PROJECT_BRIEF.md，需要改设计先和 owner 讨论

### 代码风格

- Python: black + ruff 默认
- 命名: `snake_case` 函数变量, `PascalCase` 类, `SCREAMING_SNAKE_CASE` 常量
- 注释：中英混合都可以，公共 API 的 docstring 用英文
- 不写多余注释（`counter += 1  # increment counter` 这种）

---

## 13. 测试策略

### 单元测试（每个模块必有）

- `test_pdf_io.py`：合成 PDF fixture，验证 scan_pdf、extract_image_array
- `test_classifier.py`：构造不同特征的 ImageInfo 验证分类结果
- `test_strategy_v2.py`：预算分配、单图压缩、全局校验
- `test_strategy_v1.py`：整页栅格化、页面级 quality 分配

### 端到端测试

- `test_pipeline.py`：
  - 合成一个 5MB 的 PDF，target=3MB（compression_ratio=0.6），验证走 v2.0
  - 合成一个 5MB 的 PDF，target=1MB（compression_ratio=0.2），验证走 v1.0
  - 验证输出大小落在 [target - tolerance, target] 区间
  - 验证输出 PDF 能被 fitz.open 正常打开，页数不变

### 真实数据测试

- `tests/fixtures/portfolio_1.pdf`（用户提供，71MB）
- 测试压缩到 5/10/15/20MB 四个目标，人工检查视觉质量

---

## 14. 提示词模板（agent 使用）

当 owner 在 VSCode 里唤起 agent 时，通常这样开头：

```
读 PROJECT_BRIEF.md 里 Phase [X] Task [Y] 的要求。
先给我一个 3-5 句话的实现计划，不要写代码。
我确认后你再写。
```

或者：

```
按 PROJECT_BRIEF.md Task 0.6 的要求实现 src/compressor/strategy_v2.py。
先展示函数 signature，我 review 后你再填函数体。
```

---

## 附录 A：MVP 之后的路线图（先不做）

- Phase 3：Cloudflare Tunnel + Vercel 部署
- Phase 4：引入 Gemma 视觉模型做低置信度分类
- Phase 5：用户账户 + Stripe 支付
- Phase 6：批量压缩 / API 开放

**这些不在当前 spec 范围内，agent 忽略。**

---

_End of PROJECT_BRIEF.md_