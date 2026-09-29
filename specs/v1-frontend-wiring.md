# Spec v1 — 前端接入 API（Phase-2）

复制 `_template.html` → `backend/app/static/index.html`，**只做数据层外科手术**：CSS、HTML 结构、渲染函数、过滤/搜索/导出逻辑、表单即时校验、交互动画一律不动。

## 改动清单

1. 数据源反转：`ALL_CASES`/`SUBMISSIONS` 初始为空数组（`SUBMISSIONS` 改 `let`）；删除客户端 normalize/seed 调用；启动改为 `init()`：`GET /api/bootstrap` → `applySnapshot` → `render()` → `openFromHash()`。
2. 新增 `API` 小对象与 `applySnapshot(j)`：整体替换两数组、合并 `reminderSettings`、填充 `AUTO_LOG`（服务端为唯一日志源）。
3. 写操作逐个改为 `await API.*` 后 `applySnapshot` + 模板原有的后续动作（banner 文案、flash 文案、`goToDetail`、退出编辑态等全部保留）：
   - 提交案例（保留全部前端校验；422 → 模板 showError）
   - 确认登记 / 退回登记
   - 删除案例（两处确认入口；服务端删除后仍调用模板 `deleteCase` 完成本地状态复位）
   - 详情保存（前端三条规则保留 + 服务端 422 映射到 `state.editError`，复用模板错误条）
   - 手动发提醒（邮箱校验保留）、提醒设置保存
   - 遗留 Excel 上传模拟（动画不变，成功步改为服务端生成 18 条）
4. 移除客户端每日检查调度（`dailyCheckIfDue` 调用与 `setInterval`），改为**每小时**静默 `bootstrap` 刷新；仅在非编辑态（非 detail 编辑、无展开提醒面板、非 submit 表单页）时重渲染，避免打断输入。
5. localStorage 读写保留但仅作启动前兜底，`applySnapshot` 一律覆盖（避免双源打架）。
6. `window.claude` 下载分支等模板遗留死代码原样保留（部署环境惰性，不影响 UI）。

## 一致性验收

与 `_template.html` 并排：所有视觉元素、文案、徽章色、空态、动画一致；唯一可感知差异 = 数据持久化与多端共享。

## 母版与实现的关系（v2 起的既定事实）

`backend/app/static/index.html` 是**规范实体与唯一运行文件**：v2 各 Phase 的加固（XSS 转义、错误提示、滚动/缩放适配、防双击、favicon 等）只落在这里。`_template.html` 仍带这些问题（无转义、2026 硬编码等），**仅作布局与文案参考，不再向它同步修复，也不要以它为起点复制新页面**。"与模板并排一致"的验收口径 = 视觉与文案一致，不含母版自身缺陷。
