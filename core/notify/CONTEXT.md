<!-- PQS module CONTEXT.md — 由 CLAUDE.md 2026-05-19 reorg 拆出。
CLAUDE.md = context 入口,仅留项目级(不变量/纪律/架构/概括)。
本文件 = 本模块的历史/契约细节(content-preserving 搬迁,无删改)。
回指: ../../CLAUDE.md ; 索引见 CLAUDE.md 末「Module CONTEXT.md 索引」。 -->

# core/notify/CONTEXT.md — module history / contract detail


## [Notify Module]

### Notify Module

Channel-agnostic notifier (`core.notify`). Backends: `wecom_bot`
(WeChat Work webhook, recommended), `server_chan`, `stdout`, `null`.

```python
from core.notify import get_notifier
n = get_notifier()  # reads config/notify.yaml
n.info("title", "body"); n.error("kill switch", "...")
```

All sends return `SendResult` (never raises on transport failure).
Rate limit + min_level gating built-in. Credentials via env var
expansion (`${PQS_WECOM_WEBHOOK_URL}`).
