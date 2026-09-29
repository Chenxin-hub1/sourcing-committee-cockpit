# T04 — 提交与登记确认/退回

**Status:** closed
**Type:** task
**Spec:** specs/v1-backend.md

POST /api/submissions（必填+门禁校验、SUB-#### 分配、编号归一化、重复待审拦截）；confirm（建 PENDING 案例行、周内行号+1、状态与 approvedSwatId）；reject（必填原因）。
