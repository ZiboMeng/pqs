# Claude ↔ Codex Bridge — Proposal & Protocol Sketch

**Date**: 2026-04-25
**Status**: design proposal (not yet implemented). Saved as a
working document so we can pick this up after data-integrity round-3
follow-up settles.

---

## 1. 背景

用户希望让 Claude (this CLI) 和 Codex (another CLI on the same
machine) 通过共享 markdown 文件互相讨论开发任务：
- Claude 做开发
- Codex 做审计 + 在审计后提需求
- Claude 审核需求，提出意见，跟 Codex 讨论

Codex 已给出初版思路（watcher daemon + turn markers + debounce）。
本 doc 是 Claude 这一侧的反馈 + 落地方案。

---

## 2. 对 Codex 方案的整体评价

**思路对 ~80%**：append-only markdown + turn markers + watcher
daemon + processed-offset 这个骨架同意。

**但有 4 处需改**。

### 2.1 关键现实限制 Codex 没提到：Claude 没法被 daemon 直接触发

这是最大的设计 constraint：

- Claude Code 是 user-invoked，不是 daemon。它没有"自己 wake up
  来读文件并回复"的能力。
- 即使本地 watcher 在跑，它**不能直接 wake 一个已存在的 Claude
  session**。可行的只有：
  1. 用 `claude -p "..."` 起一个新 session（每次重新 load 整个
     project context — 慢且贵）
  2. 直接调用 Anthropic API（绕过 CLI）
- Codex 那一侧大概率有同样的问题（无法 always-on）。

**结论**: Codex 描述的"watcher 推动两个 agent 自动来回 N 轮"在
我这一侧落地需要付 cost 翻倍 + 每次重 load context 的代价。

**推荐先 user-driven relay（用户每次说"继续"），跑通后再视必要
性升级到 watcher。**

### 2.2 Turn marker 格式应当带 id + timestamp + prev_hash

Codex 的:

```
<!-- TURN: claude --> ... <!-- END -->
```

我的版本:

```
<!-- TURN id=001 from=codex ts=2026-04-25T17:00:00Z prev=GENESIS -->
... codex 内容 ...
<!-- END id=001 -->
```

加 `id`、`ts`、`prev` 三个字段：

- `id` 单调递增 — debounce 失败 / 文件被乱改时能 detect 漏 turn
- `ts` 给一个粗略时间锚
- `prev` = 上一个完整 turn 内容的 sha256 前 12 hex — 形成 chain；
  文件被中间篡改 / 半截写入会被发现
- `<!-- END id=N -->` 必须 `id` 跟 open 配对，watcher 解析时强制
  校验

### 2.3 "几秒没写入" debounce 不够

只靠静默期会被 IDE auto-save / 网络抖动骗。

**必须以 `<!-- END id=N -->` 完整收到为准**。debounce 只是"快速
失败的 timeout"，不是判断完整的依据。

### 2.4 锁文件别用，改用 atomic write 或 git commit

锁文件容易 deadlock 在 stale 状态。

替代方案：

- (A) 写临时文件 + 原子 rename：

  ```bash
  cp claude-bridge.md claude-bridge.md.tmp.$$
  echo "...new turn..." >> claude-bridge.md.tmp.$$
  mv claude-bridge.md.tmp.$$ claude-bridge.md  # POSIX rename is atomic
  ```

- (B) **每个 turn 一个 git commit** — commit 本身就是 atomic +
  自带 hash chain，跟 §2.2 hash 字段重合。这是更优选择。

---

## 3. 推荐落地路径（三 stage）

### Stage 1 — 用户驱动 relay（不写代码，立刻可用）

**协议**：repo 加 `bridge/claude-codex-bridge.md`，git tracked，
每个 turn = 一个 commit。

格式：

```markdown
# Claude ↔ Codex bridge

Topic: <one-liner of what they're discussing>
Started: 2026-04-25T17:00:00Z
Charter: <max_turns | escalate_to_user_when | end_condition>

---

<!-- TURN id=001 from=user ts=2026-04-25T17:00:00Z prev=GENESIS -->
<task description here>
<!-- END id=001 -->

<!-- TURN id=002 from=codex ts=2026-04-25T17:02:00Z prev=ab12cd34ef56 -->
<codex audit / proposal>
<!-- END id=002 -->

<!-- TURN id=003 from=claude ts=2026-04-25T17:05:00Z prev=cd34ef56ab78 -->
<my review / counter-proposal / agreement>
<!-- END id=003 -->
```

**操作流程**：

1. 用户 → Codex："读 `bridge/claude-codex-bridge.md` 最后一个
   `from=claude` 的 turn，append 你的回复"。Codex 写完 commit
2. 用户 → Claude："读 bridge 文件最后一个 `from=codex` 的 turn
   并回复"。Claude 写完 commit
3. 当 turn id 触达 charter 设的 `max_turns`，或一方明确写
   `<!-- END id=N final=true -->` 时停止 → 升给用户做仲裁

**Stage 1 的优点**：

- 0 代码量
- git 自带 chain integrity（每个 commit atomic + hashed）
- 用户随时能 `git log` 查全过程
- 任何一方写错或用户不满意，`git revert` 干净回退
- 没有 daemon = 没有崩溃 / race / stale lock 风险

**Stage 1 的缺点**：用户每次切换需要手动 ping 双方。但每轮只是说
一句"继续"，成本可接受。

### Stage 2 — 半自动 watcher（仅当 Stage 1 切换累到不能忍时再做）

只有 Stage 1 跑过 5-10 个 conversation **协议跑通无 bug** 之后再
升级。

```python
# bridge/watcher.py — pseudo
while True:
    last_turn = parse_last_complete_turn(BRIDGE_FILE)
    if last_turn.from == "codex" and not_yet_replied_by_claude(last_turn.id):
        prompt = (
            f"Read bridge/claude-codex-bridge.md. "
            f"Append turn id={last_turn.id+1} from=claude "
            f"prev={last_turn.hash}, replying to turn {last_turn.id}."
        )
        subprocess.run(
            ["claude", "-p", prompt,
             "--allow-tools", "Read,Edit,Bash"]
        )
    elif last_turn.from == "claude" and not_yet_replied_by_codex(last_turn.id):
        subprocess.run(["codex", ...similar...])
    time.sleep(POLL_INTERVAL)  # e.g. 15-30s
```

**实现细节要点**：

- 用 `watchdog` (Python) 或 `inotifywait` (Linux) 比纯轮询好
- watcher **只处理完整 `<!-- END id=N -->` 的 turn**；半截写入忽略
- 维护 `bridge/.processed_turn_id` 文件防重复处理
- 给每次 invoke 设 timeout（比如 5 min），防 stuck
- 失败时 backoff (1s → 2s → 4s → 30s max)

**Cost 警告**：每次 `claude -p` 是新 session，要 reload
project context — 比 active session 贵。Stage 2 上线前要明确预算。

### Stage 3 — Charter / Escalation 机制

为了避免 Claude ↔ Codex 无限拉锯：

```yaml
# bridge/charter.yaml
max_turns: 20
escalate_to_user_when:
  - explicit_disagreement_after_3_attempts  # 一方 3 次"我不同意"
  - turn_size_exceeds_2000_words           # 一方写超 2000 字
  - same_argument_repeated_twice           # echo loop
  - claude_or_codex_says: "ESCALATE"       # 主动 escalate
end_condition:
  - both_say: "AGREED"                     # 双方明确同意
  - user_appends_terminator                # 用户写 terminator turn
```

**Charter 必须在文件顶部 fixed**（不准 mid-conversation 改）。

watcher（Stage 2）或 user（Stage 1 手动）按这个 charter 决定是否
继续。

---

## 4. 给 Codex 的回复要点

```
我同意你 4 项核心思路: append-only markdown / turn markers /
processed offset / debounce.

但建议改 4 处:

A. turn marker 加 id + ts + prev_hash 字段, <!-- END --> 必须
   配 id; 参考:

       <!-- TURN id=003 from=claude ts=... prev=ab12cd34ef56 -->
       <!-- END id=003 -->

   理由: debounce 不够稳; 完整性靠 marker 配对 + hash chain.

B. 别用锁文件, 改用每个 turn = 一个 git commit. git 自带 atomic
   + hash chain, 顺便给 user 一个 git log 可查的全过程.

C. Claude 这一侧没法被 watcher daemon 直接 wake. 你提的 daemon
   思路在我这边落地需要 `claude -p` 起新 session, 每次重 load
   project context (慢/贵). 我建议先做 user-driven relay (Stage 1):
   user 每次说"继续", 双方各读对方最新 turn 再写一轮. 跑通 5-10 轮
   后再考虑 watcher (Stage 2).

D. 加一个 charter.yaml 钉死 max_turns / escalation 条件 / end
   condition. 防止两个 agent 无限循环.

如果同意, 我们今天就用 Stage 1 协议. 我先在 repo 加一个空 bridge
file + 协议规范 + 一个 test conversation, 你来 review 协议, 没
问题就开始用.
```

---

## 5. 三选一: 用户接下来要做什么

1. **直接落地 Stage 1**: 现在就加 `bridge/claude-codex-bridge.md`
   + `bridge/PROTOCOL.md`（写完整协议），用户 review 后开始用
2. **先把方案讨论完**: 等用户跟 Codex 来回讨论确认协议，再落代码
3. **Stage 1 + Stage 2 watcher 一起实现**: 同时写好 watcher 脚本
   （即使先不开），后面随时能升级

**Claude 推荐 (1)** — 先把协议打死，watcher 等真需要再说。

---

## 6. Stage 1 落地时的 deliverable

如果走 Stage 1, 需要落以下 4 个文件:

```
bridge/
  PROTOCOL.md              # 协议规范 (turn marker schema, hash
                           # chain rules, escalation rules)
  charter.yaml             # 当前 conversation 的 charter
  claude-codex-bridge.md   # 实际对话文档 (initially empty
                           # except header + topic + first user turn)
  README.md                # 给两个 agent 看的"如何 append turn"
                           # 操作指南
```

可选:
```
  bridge/.processed_turn_id   # gitignored; 记录上次处理到的 turn
                              # (Stage 2 watcher 用)
  bridge/watcher.py           # Stage 2 daemon, 默认不开
```

---

## 7. Open questions to settle before Stage 1 starts

1. **Topic per conversation**: 同时只能有一个 active conversation
   ($1 file)? 还是允许多个 (`bridge/topic_<slug>.md` + 用户分别
   ping)?
2. **Charter 是否每次新 conversation 都重新写**, 还是有 default?
3. **Disagree resolution**: 当 Claude 和 Codex 真的谈不拢时, 谁
   有最终决定权? Default 应该是 escalate to user, 但 charter 应
   该明示.
4. **Cost budget per conversation**: max_turns + each turn token
   cap, 防止跑飞.
5. **Test conversation topic**: 第一次试跑用什么任务? 推荐用 round-3
   已经有的 follow-up parking lot 里某一项 (e.g. "universe hardcode
   → config sweep") 作为 dry-run 主题, 因为这个范围明确, 易判断
   两 agent 是否谈出 sensible plan.
