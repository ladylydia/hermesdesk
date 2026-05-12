

现在这套实现里，真实用户权限仍然只有两种：`standard` 和 `power user`，`default / advanced / power` 是我在目录展示层引入的“有效角色（effective role）”。

## 1) 三类有效角色怎么界定

- `power`
  
  - 条件：`HERMESDESK_POWER_USER=1`
  - 对应你现在的 `power user`

- `default`
  
  - 条件：不是 power user，且 `show_recipe_market` 关闭
  - 对应 `standard user` 的普通状态

- `advanced`
  
  - 条件：不是 power user，但 `show_recipe_market` 打开（从设置或 `hermesdesk_show_recipe_market.txt` 读）
  - 本质：还是 `standard user`，只是目录展示更“开放”，不是新的系统权限

---

## 2) 和工具（toolsets）的具体关联

有，写死在策略里：

- 对所有角色可见/低风险：  
  `web, file, vision, image_gen, tts, skills, todo, browser`
- 仅 `power`：  
  `terminal, code_execution, moa`
- 其他未知 toolset：  
  默认从 `advanced` 起可见（中风险）

另外目录里会给 `locked` 标记。  
注意：这是目录展示和引导层；真正工具是否可用仍由原有 `ToolPolicy` + `HERMESDESK_POWER_USER` 决定。

---

## 3) 和 Skill 的具体关联、标签机制

有支持，而且是通过 `SKILL.md` frontmatter 的 `metadata.hermesdesk`：

可用字段（当前已接入）：

- `metadata.hermesdesk.visibility.roles`
- `metadata.hermesdesk.visibility.min_role`
- `metadata.hermesdesk.source`
- `metadata.hermesdesk.trust`
- `metadata.hermesdesk.recommended`

### fallback 规则（没打标签时）

- 如果 `source/trust` 判定为社区/不受信（如 `github/url/hub/community/untrusted/unknown`）=> 仅 `power` 可见
- 否则 => 默认三角色都可见

---

## 4) 有没有“自动创建标签关联 skill”？

没有自动创建。

- 现在是“读取型”设计：从 skill frontmatter 读标签，不写回 skill 文件。
- 也没有独立数据库做 skill-tag 映射。
- 如果你要“创建标签”，目前要通过：
  - 手动改 `SKILL.md`，或
  - 让 agent 用 `skill_manage` 去改（这正符合你的 agent-assisted 流程）
