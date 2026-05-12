# 路线 C（Desk 调内嵌 Python）— 个人微信验证说明

Kabuqina **已产品化路线 C**：微信扫码走 **`weixin_qr_worker.py`** + `WeixinQrRouteCBlock`；同类「bundle 内 Python + Tauri IPC」模式亦用于 **QQ**（`qqbot_qr_worker.py`）、**飞书/Lark**（`feishu_qr_worker.py`）。Telegram 为 **token 表单**，不走扫码 worker。总览见 [gateway-desk-weixin-strategy.md](gateway-desk-weixin-strategy.md)。

本文档仍专注于 **个微 / iLink**，完成两件事的 **结论与可复现步骤**：

1. **打包 / 运行可行性**：用仓库内脚本 + 与安装包一致的解释器验证「能否 import + 打到 iLink」。
2. **iLink `get_bot_qrcode` 返回的数据形态**：以 Hermes 上游实现为准，避免凭猜测做前端。（QQ/飞书的开放平台字段见上游与本仓库 Settings 文案。）

若两项均通过，个微绑定可走路线 C；若解释器侧 import/网络/体积异常，再评估 **路线 B**（在 `web_server` 增加薄 HTTP）。Desk 当前默认 **不采用路线 B**。

---

## 1. iLink `get_bot_qrcode` 返回什么？（结论）

Hermes 在 `gateway/platforms/weixin.py` 里把响应当 **JSON 对象** 解析（`GET` → `json.loads(raw)`），登录流程只使用两个字段：

| JSON 字段 | Hermes 中的含义 | 前端含义 |
|-------------|-----------------|----------|
| **`qrcode`** | 字符串；代码注释称为 **hex token** | **轮询** `get_qrcode_status` 时作为查询参数 `?qrcode=` 的**不透明令牌**（不是给用户扫的「主码」） |
| **`qrcode_img_content`** | 字符串；注释写明为 **full scannable liteapp URL** | 非空时：这是 **HTTP(S) 文本 URL**，应用来生成可扫二维码（`qrcode` 库 `add_data(qr_scan_data)` 的输入）；**不是** Base64 图片字段名意义上的「图片 blob」 |

编码逻辑（同一文件内）：

- 若 `qrcode_img_content` 非空 → 扫码内容用 **URL 字符串**。
- 若为空 → 退化为用 **`qrcode` 字符串本身** 生成 QR（上游注释：微信侧更需要完整 URL，故优先 URL）。

因此 **默认路径下前端复杂度**：在 WebView 里用 **`<img>` 不需要**（除非你们自己把 URL 转成图片）；更直接的是：

- 展示 **可点击的 `https://…` 链接**；或  
- 用 **前端 QR 库** 对 `qrcode_img_content`（或回退的 `qrcode`）做 **encode**，或  
- 用 **Tauri 返回 URL**，由现有壳用 `qrcode` / `tauri-plugin-qrcode` 等生成位图（与 CLI ASCII QR 等价）。

**若线上偶发返回 `data:` 前缀**：按字符串处理即可（`weixin_ilink_qr_probe.py` 会标注 `data:` 类型）。

---

## 2. 路线 C —「最小」打包可行性怎么验？

### 2.1 与正式桌面包一致的关键

桌面壳实际拉起的是 **`python/dist/runtime`** 里打好的 CPython + `hermesdesk.pth`（把 `../hermes` 与 `../site-packages` 放进 `sys.path`），入口为 **`desktop_entrypoint.py`**。  
路线 C 要成立，需满足：

1. **解释器**：`python\dist\runtime\python\python.exe`（或等价路径）能 `import gateway.platforms.weixin`（依赖已在 prune 的 `site-packages` 里，例如 `aiohttp`、`cryptography`、`yaml` 等 — 开发机裸 `python` 只挂 `hermes/` 常会缺 `yaml`，**应以 bundle 为准**）。
2. **网络**：内嵌进程须能访问 `https://ilinkai.weixin.qq.com`（Kabuqina 的 `network_allowlist` overlay 需包含该主机；当前若未放行，要在 overlay 或配置里显式加入后再测）。
3. **体积**：路线 C **不要求**在壳里新增 `qrcode` 轮子即可展示 **URL**；若要在 **Rust 侧**生成 PNG/SVG，再评估依赖增量。完整 `qr_login()` 在 CLI 里会 `import qrcode` 打 ASCII — 可选依赖。

### 2.2 仓库内一步探测脚本（不轮询、不登录）

脚本路径：**`python/tools/weixin_ilink_qr_probe.py`**

只做一次 `GET …/ilink/bot/get_bot_qrcode?bot_type=…`，打印字段类型说明；可加 `--json` 看原始 JSON。

**开发机（子模块在路径上，且已安装 Hermes 网关依赖时）：**

```powershell
Set-Location D:\project\Kabuqina
$env:PYTHONPATH = "$PWD\hermes"
python python\tools\weixin_ilink_qr_probe.py
```

**打好的 runtime（先执行 `.\python\build_bundle.ps1`）：**

```powershell
$rt = "D:\project\Kabuqina\python\dist\runtime"
& "$rt\python\python.exe" "$PWD\python\tools\weixin_ilink_qr_probe.py"
```

若 bundle 内 `sys.path` 与入口不一致，可显式指定含 `gateway` 的 Hermes 根目录：

```powershell
$env:HERMESDESK_WEIXIN_PROBE_ROOT = "$rt\hermes"
& "$rt\python\python.exe" .\python\tools\weixin_ilink_qr_probe.py
```

**产物体积**：在增加任何 Tauri 命令或 Python 桥接代码前后，对 `tauri\target\release\bundle\msi\` 或安装目录做 **一次 diff**（关注 `python/dist/runtime` 是否已含 `gateway` 与 `aiohttp` — 通常已由现有 Hermes 剪枝带入，**不应**为微信探测单独倍增）。

### 2.3 与「最小 Tauri 原型」的关系

严格意义上的 **第二进程 + 空壳 Tauri** 可以不做：Kabuqina **已是** Tauri + 内嵌 Python。工程上最小验证集为：

| 步骤 | 目的 |
|------|------|
| A. 用 **bundle 的 `python.exe`** 跑通 `weixin_ilink_qr_probe.py` | 证明剪枝后的 site-packages + hermes 树能连 iLink |
| B. 在同一 runtime 里 **异步跑** `qr_login(hermes_home)`（可人工扫码完成或超时退出） | 证明长连接 + 证书 + 重定向与 Desk 数据目录下的 `HERMES_HOME` 一致 |
| C. 再在 Tauri 里加 **`invoke` 桥**（stdout/JSON 或临时文件）由 `web/` 调 | 产品化；**不必**为验证单独新建仓库 |

若 A 失败：先修 **PYTHONPATH / overlay 网络白名单 / TLS**，再谈路线 B。  
若 B 失败：对照 `weixin.py` 日志与 `HERMES_HOME` 路径。  
若 A+B 成功、仅 C 嫌烦：才考虑路线 B 把「取码 + 轮询」做成 HTTP。

---

## 3. 路线 B 何时再评估？

- bundle **无法**稳定 `import gateway.platforms.weixin` 或无法访问 iLink（策略/证书/体积）。  
- 产品坚持 **浏览器内** 单一协议（仅 JSON + WebSocket），不接受子进程/IPC。

---

## 4. 参考代码位置（Hermes 子模块）

- `hermes/gateway/platforms/weixin.py` — `EP_GET_BOT_QR`、`qr_login()`、`_api_get()`  
- `hermes/hermes_cli/gateway.py` — `_setup_weixin()`（CLI 调用 `asyncio.run(qr_login(...))`）

---

## 5. 文档维护

验证结果（日期、bundle 版本、探测输出样例是否含 `qrcode_img_content` URL）建议记在 issue 或本文件末尾附录，便于日后对齐腾讯侧接口变更。

**相关**：总路线说明见 [gateway-desk-weixin-strategy.md](gateway-desk-weixin-strategy.md)；架构见 [architecture.md](architecture.md)；网关排障见 [troubleshooting.md](troubleshooting.md) §§12–16。

---

## 6. Keys 已保存 vs 网关进程、vs 路线 C「已配置」

三者不要混为一谈：

| 层面 | 含义 |
|------|------|
| **Hermes 仪表盘 / Keys（/env）** | 展示写入 **`hermes-home/.env`** 的变量；条目多不代表 **`python -m gateway.run`**（Desk 网关子进程）一定在跑。 |
| **消息网关进程** | 独立子进程，读同一 `.env`；首轮连 iLink 失败时，**旧版**嵌入式 `gateway/run.py` 可能立刻 **exit 1**（见 [troubleshooting.md §12](troubleshooting.md)，及 §§14–16 其它网关类故障）。更新 **`hermes/` 子模块后必须** `.\python\build_bundle.ps1` **刷新 `python/dist/runtime`**。 |
| **壳设置「个人微信已配置」** | **`cmd_weixin_env_status`**：仅当 **`WEIXIN_ACCOUNT_ID` 与 `WEIXIN_TOKEN` 均非空**时为已配置；**不要求**网关曾连通。仅缺一会在设置页显示 **凭据不完整**（琥珀提示）。 |

**相关**：Desk 侧消息网关总述见 [gateway-desk-weixin-strategy.md §8](gateway-desk-weixin-strategy.md)。
