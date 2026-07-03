# PROGRESS

## Phase 0: 核心库

- [x] Task 0.1 项目初始化：pyproject.toml、目录结构、.gitignore、venv（Python 3.14，系统仅此版本，满足 >=3.11）
- [x] Task 0.2 `schemas.py`：PageType/Strategy 枚举、ImageInfo、PageInfo、CompressionConfig、CompressionResult
- [x] Task 0.3 `config.py`：扫描过滤、分类阈值、面积分档、服务层常量全部集中
- [x] Task 0.4 `pdf_io.py`：scan_pdf（跳过非 stream xref、微型图、PIL 无法解码的格式；缓存原始字节与 SMask）、flatten_to_rgb、render_page、pdf_bytes
  - 重要发现：`doc.tobytes(garbage=4)` 会改写内存文档并重编 xref，导致后续 update_stream 报 bad xref。
    pdf_bytes 改为在快照副本上做垃圾回收测量（坑 4 的正确姿势）。
- [x] Task 0.5 `classifier.py`：图片级（colorfulness + 白底比 + 边缘密度 + 显示占比）、页面级（ink ratio + colorfulness）
- [x] Task 0.6 `strategy_v2.py`：预算分配（label 权重 x 面积档 x 原始大小）、PPI 阶梯 + quality 二分、
  update_stream 后同步 Width/Height/Filter/ColorSpace 并解除 SMask（坑 1/2/3/5 全部处理）、全局调整循环
- [x] Task 0.7 `strategy_v1.py`：整页渲染缓存为 q95 JPEG、页面级 quality、全局 multiplier 二分、超标时自动降 DPI
- [x] Task 0.8 `pipeline.py`：按 compression_ratio 自动切换；v2 达不到目标时自动回退 v1；已小于目标时 passthrough
- [x] Task 0.9 `cli.py` + `__main__.py`：`python -m compressor input.pdf --target 15 --output out.pdf`
- [x] Task 0.10 pytest：34 个测试全部通过（pdf_io / classifier / strategy_v1 / strategy_v2 / pipeline / server）
- [ ] Task 0.11 真实作品集测试：**等待 owner 提供 `tests/fixtures/portfolio_1.pdf`（71MB）**
  - 已用合成 35MB 作品集冒烟：→20MB 走 v2（1.9s），→5MB 走 v1（输出 4.99MB，2.9s）

## Phase 1: FastAPI 服务层

- [x] `server/main.py`：FastAPI app + CORS（localhost:3000）+ /api/health
- [x] `server/routes.py`：POST /api/jobs（上传 + 目标档位校验 + PDF 魔数校验）、GET /api/jobs/{id}、GET /api/jobs/{id}/download
- [x] `server/jobs.py`：内存 job 表 + ThreadPoolExecutor(2)，1 小时过期清理，完成后删除上传原件
- [x] `server/ratelimit.py`：滑动窗口 per-IP 限流（10 次/小时）

## Phase 2: Next.js 前端

- [x] `web/`：create-next-app（Next 16 + React 19 + Tailwind v4 + TS）
- [x] `app/page.tsx`：单页流程（拖拽/选择 PDF → 选 5/10/15/20MB → 上传 → 轮询 → 下载），
  显示压缩结果（大小、页数、耗时、所用策略），错误与限流提示
- [x] `npm run build` 通过；dev server 冒烟通过
- 说明：UI 用 Tailwind 手写（shadcn 风格）；MVP 单页无需引入 shadcn CLI 组件依赖，
  如 owner 坚持 shadcn/ui 可后补

## 端到端验证记录（2026-07-03）

- 合成 35MB 作品集（12 页，含 SMask 透明图与微型装饰图）：
  - CLI `--target 20` → vector_preserving，8.33MB，1.9s（图片到质量上限，低于窗口属预期）
  - CLI `--target 5` → page_rasterization，4.99MB，2.9s（落在 [4.7, 5.0] 窗口内）
  - API 上传 → 轮询 → 下载 全流程通过（35MB → 9.2MB @ target 10MB）
- pytest：34 passed
- black 已格式化；ruff 因沙箱 Application Control 策略无法执行原生二进制，未跑（代码按 ruff 默认风格书写）

## 遗留事项

- Task 0.11：等待 owner 提供真实 71MB 作品集 `tests/fixtures/portfolio_1.pdf` 后做四档人工画质检查
- strategy_switch_ratio=0.4 需在真实数据上调优（PLANNING.md 决策 1）
