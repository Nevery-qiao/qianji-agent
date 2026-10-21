# 先判断你的 Agent 怎样连接钱迹

这份指南依据运行架构选方法，GrokBot 是远程 Agent 的一个实例。品牌相同的桌面版、云端版也可能采用不同架构。不要只问“支持某某 Agent 吗”。

## 第一步：核实三件事

1. **MCP 命令实际在哪运行？** 在钱迹所在 Mac，还是平台云电脑/另一台电脑？能通过 shell 访问 Mac，不等于平台能把 MCP stdio 进程放在 Mac。
2. **平台支持哪种 MCP？** 本机 `command/args`（stdio），还是远程 `url/headers`（HTTP），或两者都有？查看平台实际配置字段，不猜测。
3. **钱迹 Mac 是否可用？** 官方 App 已登录、版本匹配、工具能读到现有登录状态；远程使用时 Mac 也要在线。登录材料始终留 Mac。

安装源码后，可让 Agent 运行离线接入判断。此命令不读取登录信息、不连接钱迹、不建立记录库：

```sh
qianji-agent-connect
qianji-agent-connect --agent-location same-mac --mcp stdio --mac-available yes
qianji-agent-connect --agent-location cloud --mcp http --mac-available yes --goal read
```

缺少信息时返回待核实问题；`ready_for_validation` 仅表示可选路线，不表示已经接通。诊断进程的操作系统不能证明 Agent MCP 命令运行位置。

## 第二步：选择路线

| 已核实的情况 | 方法 | 必须确认的边界 |
|---|---|---|
| Agent 与钱迹在同一 Mac，支持 stdio | 在该 Mac 安装，配置绝对路径 `qianji-agent-mcp`，安装 Skill | 本机可见性不等于调用已获授权；核对实际连接和恢复清单 |
| Agent 在云端/其他机器，支持远程 MCP URL | Mac 运行 `qianji-agent-remote`，通过鉴权 HTTPS 连接 | 本阶段仅五个只读工具；同一原 journal，不复制认证到云端 |
| Agent 在云端，只支持云端 command/stdio | 当前不能直接接 Mac | 不要填写 Mac 绝对路径，也不要在云端新建空记录库冒充原环境 |
| Agent 不能用 MCP，但能在同一 Mac 执行命令 | 可按实际授权使用原 CLI 的有限入口 | CLI 不等于完整 MCP 合同，不能绕过调用方原工作流程 |
| 没有已登录且在线的 Mac | 当前无法接入 | Windows/Linux/云端独立登录尚未实现 |

## 同机 stdio

```json
{"mcpServers":{"qianji-agent":{"command":"/absolute/path/to/venv/bin/qianji-agent-mcp","args":[]}}}
```

所有调用者共用默认 `~/Library/Application Support/qianji-agent`，不同 Agent 不另配记录库。平台若在云电脑执行 command，以上配置不适用。

## 远程只读 HTTPS

在钱迹 Mac 上安装本次源码，生成高强度随机 Bearer token，保存到本人所有、0600、无符号链接的私有文件；不放仓库、不发聊天、不通过命令参数传密钥值。使用前必须已有原 journal；远程入口缺少或替换原文件会拒绝，不初始化空库。

```sh
qianji-agent-remote --token-file /absolute/private/token --public-url https://YOUR-DEPLOYED-HOST --port 8769
```

`YOUR-DEPLOYED-HOST` 是占位符，不是可提交配置。先部署真实 HTTPS 通道，按其真实域名启动服务。入口仅监听 `127.0.0.1`，保留精确 Host/Origin 校验；不允许 wildcard，不关闭 TLS 验证，不开放无鉴权公网 HTTP。HTTPS 代理必须保留 Authorization，并用已批准的 Host 转发到该端口；客户端无 Origin 可用，存在 Origin 则必须精确匹配配置的 HTTPS origin。

平台配置（密钥通过平台安全输入/私有配置交付，不能直接照抄占位符）：

```json
{"name":"qianji-agent-readonly","url":"https://YOUR-DEPLOYED-HOST/mcp","headers":{"Authorization":"Bearer SECRET_FROM_PRIVATE_FILE"}}
```

服务端只登记 `qianji_connection`、`qianji_capabilities`、`qianji_query`、`qianji_recovery_list`、`qianji_account_review`。写入、preview、旧请求 status、ack、scheduler 工具即使伪造 `tools/call` 也拒绝；后端另有白名单。capabilities 返回 remote_readonly 和空 operations，不能把本机51项动作当远程已开放。account_review 与原恢复读取会按原核心维护正常核验/恢复元数据；不发送金融请求，不登记或修改宿主定时绑定。

### HTTPS 通道的选择与维护

- 试验可使用 Cloudflare Quick Tunnel：无需新账户，URL 随进程结束失效、重启改变，不支持 SSE。此入口使用 stateless Streamable HTTP JSON 响应；仍须实际验证目标客户端兼容性。Quick Tunnel 没有可用性保证，不能称长期生产部署。
- 稳定服务应由部署者选定已有域名与受管 HTTPS 隧道/代理，建立启动、健康检查、密钥轮换和停止流程。涉及新账户、费用、长期公网服务须由其所有者决定；本项目不自动购买或启用。
- 服务正常退出会断开；停止 HTTPS 隧道同时撤下外部地址。移除 token 文件会使后续请求立即401；原 token 文件轮换后旧 token 立即失效，须同步平台。撤销平台连接再停止服务/隧道，保留原 journal，不删账务事实。
- token 允许持有者读取财务资料。若平台连接按账号共享，同账号其他 Bot 可能也能调用，不能宣称单 Bot 隔离；需要更细隔离的平台应使用其真实权限功能。
- Mac 休眠、断网、官方登录失效或 App 更新不匹配都会导致不可用；只有确证登录失效才请用户重登。不能复制官方凭证到云端、降低证书校验或切换空记录库来“修复”。

Cloudflare 官方说明：https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

## GrokBot 实例

本次现场 AddMcpServer 有 name/url/headers/auth 或 command/args/env，没有 machineId 或单 Bot 范围。command 在云电脑执行，所以 Mac 路径不能直接注册。已连接 Mac 的 shell 是另一项能力。适用路线是上方远程只读 HTTPS；账号级共享边界应明确告知用户。不同版本仍以实际字段为准。

## 第三步：验证后才能称接通

1. 未认证、错误/撤销 token、错误 Host/Origin 必须拒绝。
2. 实际客户端握手成功、工具列表精确五项；直接伪造被禁调用也不能触达核心。
3. 实际 connection/query 成功，恢复清单沿 next_offset 全部分页，fresh account_review 的 current=true/continuation-v1 与原 scope 对上。旧 unknown 保留，不重查旧 status 或关闭它。
4. 记录客户端名称、运行位置、原 scope、实际时间、测试范围及未验证项；不要记录密码、token或账务原文到公共日志。
5. 本机测试、URL 已创建、平台注册成功和实际平台调用成功是四件事，分别验明。只读成功不授权正式记账或生产交班。
