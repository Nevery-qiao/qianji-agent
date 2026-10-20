# 钱迹 Agent 工具

本机后台 MCP 与配套 Skill，供 Agent 查询、记账和管理钱迹对象。账单来源、OCR 和自然语言提取由调用方处理。

## 这个项目做什么

让 Agent 在后台使用钱迹：查询账本和账户、录入账目、处理退款和借还款、管理周期与分期任务。用户先登录官方 App，Agent 再通过 MCP 和配套 Skill 调用；不需要点界面，也不修改钱迹 App。

账单来自哪里由调用方决定，可以是用户直接提供、邮件、文件或其他工具。本项目负责把已经明确的账务指令送入钱迹，并核验结果。

**0.2.0 已完成当前 Mac 上的实际接入验收。** 包含10个MCP入口、51个业务动作，以及持久防重复记录、结果未知的挂起跟进、调用方收尾确认、逐账户复核。实际验证覆盖原记账和管理Agent接入、普通消费保存与自然余额核对、真实定时唤醒和隔离异常跟进任务清理。当前发布说明见[0.2.0验收与使用范围](docs/RELEASE-0.2.0.md)。

这些结果不表示51个动作的所有组合都已通过实账验证。[48组能力矩阵](docs/本机能力验收-v0.1.csv)保留逐项状态。当前适配官方macOS钱迹4.5.9/build1580；其他Mac、其他用户、Windows/Linux和云端仍需各自验证。

## 使用示例

- “查一下我的账本、账户和本月餐饮支出。”
- “把这笔明确的午餐消费记到指定账本和账户。”
- “查回原账单，按实际到账处理退款。”
- “看看是否还有结果未知或台账未接完的操作，按原请求继续核验。”

Agent先查到真实对象编号，按已有授权执行。工具核对账目字段和自然余额；结果不明时保留原请求，不能换编号重新记一遍。

## 从GitHub源码安装

在本目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/qianji-agent connection
```

再将下文MCP配置的启动路径改成本目录下 `.venv/bin/qianji-agent-mcp` 的绝对路径，并安装配套Skill。下文“安装”给出独立ZIP安装包的步骤。

## 连接方式

1. 用户先在自己的 Mac 登录官方钱迹 App。
2. 安装本工具，Agent 通过 stdio MCP 调用。
3. 工具只读现有 App 登录设置，用固定 HTTPS 后台接口操作。不会修改、注入或重签 App，不直接改官方本地财务数据库，不改变账号绑定；正式账本通过正常后台接口保存。登录信息仅在运行内存中，不出现在工具回执。

精确校验 App 的业务文件哈希；官方 App 更新后若不再匹配，工具返回 `adapter_update_required`，需更新适配器。App 自身仍可正常更新。当前包不需要 Hopper、REA、Node 或调研目录；这些只用于开发时确认协议。

当前只交付同机 Mac 连接。Windows/Linux/云端独立登录、远程服务、其他用户的会话迁移尚未交付。不要把这份包当成可在云端自动获取另一台 Mac 登录态的服务。

## 安装

Python3.12或更新版本。解压交付包后，在含有 `packages/` 的交付目录安装：

```sh
python3.12 -m venv ~/.local/share/qianji-agent/releases/0.2.0/venv
~/.local/share/qianji-agent/releases/0.2.0/venv/bin/python -m pip install -r requirements.lock.txt
~/.local/share/qianji-agent/releases/0.2.0/venv/bin/python -m pip install --no-deps packages/qianji_agent-0.2.0-py3-none-any.whl
~/.local/share/qianji-agent/releases/0.2.0/venv/bin/qianji-agent connection
```

从源码安装时，先解压 `packages/qianji-agent-0.2.0-source.zip`，进入含有 `pyproject.toml` 的源码目录，再使用新环境的 `python -m pip install --no-deps .`。交付目录本身不能用 `.` 安装。

将 `skills/qianji-bookkeeping` 复制到所用 Agent 的技能目录。Codex 可用 `~/.codex/skills/qianji-bookkeeping`。在 Codex 的 `~/.codex/config.toml` 添加，或使用 `codex mcp add`；路径请换成自己的绝对路径：

```toml
[mcp_servers.qianji-agent]
command = "/absolute/path/to/venv/bin/qianji-agent-mcp"
startup_timeout_sec = 20
tool_timeout_sec = 180
```

MCP 不需要 OAuth 或额外钱迹密码。重启客户端后加载工具目录。配置格式参考 [Codex 官方 MCP 文档](https://developers.openai.com/codex/mcp)。第三方 Agent 的完整兼容性需要各自验收。

所有本机 Agent 与命令行必须共用同一个默认操作记录目录：`~/Library/Application Support/qianji-agent`。不要给不同 Agent 单独分配记录库。工具用当前账号摘要绑定该目录；更换账号会拒绝接续旧账号记录。

## 十个 MCP 工具

| 工具 | 用途 |
|---|---|
| `qianji_connection` | 核对官方登录态能否读取，返回连接状态和账本数量 |
| `qianji_capabilities` | 连接兼容性、开放动作、48组状态与限制 |
| `qianji_query` | 查询账本、账户、模板、分类、标签、账目、周期/分期、币种 |
| `qianji_preview` | 验证指令、引用、版本和预期余额，不发送写请求 |
| `qianji_execute` | 使用稳定请求号执行单条已授权业务并回读核验 |
| `qianji_account_review` | 无金融写入，读取本轮逐账户观察、历史范围和持久停止；不重查旧号或重置次数 |
| `qianji_operation_status` | 只读核对待核实操作，不重发写请求 |
| `qianji_recovery_list` | 分页发现持久待核实/待收尾事项和调度意图 |
| `qianji_recovery_ack` | 结果查明且调用方完成后续处置后，按最新版本确认收尾 |
| `qianji_recovery_scheduler` | 读取宿主任务意图，或登记正规创建/取消后的观察 |

编号、金额必须为字符串；时间必须带时区偏移且精确到秒。修改和删除先查询目标，带上返回的 `version` 作为 `expected_version`。标签编号是不透明字符串。查询日期 `since` 包含起点，`until` 不包含终点。分页是完整源读取后的本地切片；账目源按钱迹原生游标继续读取；游标循环、重复记录或超过100页会停止并报不完整，不能宣称已经读全。当前真实数据规模未触发服务端多页。账户可用status=active/hidden/finished/all查询，其他对象不接受status。

例：调用 `qianji_execute`，真实编号由前置查询选择：

```json
{
  "request_id": "receipt-source-unique-001",
  "command": {
    "action": "bill_create", "kind": "expense",
    "book_id": "123", "account_id": "456", "category_id": "789",
    "amount": "12.50", "time": "2026-10-18T12:30:00+08:00",
    "remark": "午餐"
  }
}
```

不要使用示例编号执行。是否需要再次询问用户，由 Agent 根据已有授权判断；预览不是强制人工审批。

## 已开放业务与重要金额含义

- 普通收支、转账、信用卡还款、报销垫付；历史补记、受限修改/复制/删除。
- 原生退款创建/修改/删除，累计与原单双向关系核验；CNY基础币下支持显式换算的外币退款。
- 借入/借出、追加本金、偿还/收回、独立利息、零本金结清；使用debt_bill_update维护原生本金/还款/利息记录，双版本检测；已结清金额更改仍拒绝。
- 周期任务支持收支/转账/还款/垫付与六种周期。分期创建支持总手续费fee，以fee_method=average/first/last指定分摊、首期或末期收取；remainder=first/last指定分钱余数归属。提前还款可另付手续费。已添加分期计划的本金/期数修改按官方说明不支持。保存、原生支持的配置、启停/删除、提前还款；保存任务不等于未来执行已证明。
- 账本创建/改名/隐藏恢复/空本删除，现金/信用/充值卡/投资等原生模板、账户信用设置与计总资产标记、两层分类与移动/升降级、标签/标签组管理。不是所有 App 设置均可编辑。
- 标签、统计/预算标记、图片、有限外币换算、转账手续费、CNY支出优惠。

转账/还款的 `amount` 是转入净额，`fee` 另扣转出账户。例如 `amount=10.00, fee=1.00`，转出11.00、转入10.00。

普通CNY支出的 `amount` 是实际支付，`discount` 是额外记载的优惠。例如实付8.00、优惠2.00填写 `amount=8.00, discount=2.00`，余额扣8.00。不要再减一次优惠。

基础币保持CNY。收支可使用外币账户：currency/amount为交易原币与金额，account_amount为账户币金额，base_amount为CNY金额；同币的金额必须相等。跨币转账/还款的amount是目标账户转入净额，currency为目标币种，account_amount为转出本金，base_amount为CNY等值。跨币手续费fee是来源账户币金额，另须明确fee_base_amount（费用的CNY金额），base_amount只含本金。原生币种字段将来源本金与费用合计，工具按一次合计扣款。外币退款currency/amount是原单交易币及本次原币退款，account_amount是到账金额，base_amount是本次退款CNY金额；支持退至另一账户，累计上限始终按原币比较。工具不猜汇率，不改变基础币。

普通账目可用bill_update修改book_id/account_id/to_account_id；更换账本须给出该本匹配的category_id，关联业务仍用各自专用动作。分类升降级使用category_promote/category_demote，降级必须指定同本同类根分类parent_id，不能产生第三层。account_update可修改name/remark/include_in_total；信用账户还可改limit/statement_day/payment_day，日期1到31；payment_day为固定每月日，payment_after_statement_days为账单日后天数，二者互斥；statement_inclusive为含账单日，clear_credit_limit=true清除额度且不得同时填limit。

`prepay_records_delete` 用于已删除分期任务后的两条关联记录维护，要求付款记录 `object_id/expected_version` 及其关联支出 `related_id/related_version`。它成对删除、回读两条原生删除事件和两侧余额；它不撤销/恢复分期计划。

## 图片

先执行 `attachment_upload`，传本机绝对路径 `image_path`，目前只接收8MB以内PNG/JPEG。把核验回执的 `image_key` 放入账目 `image_keys`。不会接受猜测的任意键。

0.1.7使用官方App的图片显示域名与`!huge`变体，通过严格HTTPS回读，不降低TLS、不跟随重定向、不发送登录头。上传前完整解码单帧PNG/JPEG，损坏文件及超过2400万像素的图片拒绝发送。`storage_hash_verified`只证明上传回执哈希；`file_content_verified`只证明下载文件与原文件SHA256完全一致；`image_pixels_verified`证明按EXIF方向展开后的尺寸与RGBA像素完全一致。显示服务可能重新编码，因此像素一致时原文件字节仍可不同，不能混为一谈。`download_variant=native_huge`指官方显示变体，受保护原始文件的直接下载仍未交付。严格内容核验失败时可能只返回存储证明，两种内容标志均false，不据此猜测失败原因。删除账单不保证删除云端图片文件。上传使用短期存储令牌，不向存储服务发送钱迹登录头。协议参考 [七牛表单上传](https://developer.qiniu.com/kodo/1272/form-upload)。

## 回执、防重与恢复

| 状态 | Agent 应做什么 |
|---|---|
| `verified` | 原生对象及所需字段/关系/余额已核验，可报告结果 |
| `pending_verification` | 可能已记上；只查询原请求状态，禁止换号重发或补反向记录 |
| `not_executed` | 未发送本次写请求；处理字段、版本、连接或前序未知状态 |
| `failed` | 后台明确拒绝且稳定读取证实无效果；原请求号保留失败结果 |
| `unsupported` | 当前适配器没有这项能力；不能用另一业务冒充 |

同一业务一直使用同一 `request_id`，相同请求返回持久回执；异内容复用返回冲突。两笔真实交易必须用不同编号。同账号所有本机入口由文件锁串行，未知财务结果对其依赖范围继续保护；首发仅在完整依赖可证、账户独立和原业务授权有效时，允许单账户普通CNY新增与合格历史未知分开继续；旧范围不明或未适配复杂关联继续停止，新未知及账户漂移形成持久账户停止。工具允许不自动解除原业务暂停。图片使用账号/内容确定键，同一未知上传请求可以显式重试相同内容；状态查询不发送金融写请求。

开始/接班/每批结束检查完整恢复清单及本轮账户复核；每笔写前同样复核，缓存不能放行；所有新版结果的awaiting_ack都需调用方接续原台账/处置再确认；能立即完成时先ack，再按剩余清单维护调度。open=0不表示原台账未发送/待分类等事项全部结束。专用跟进任务仅在operation open和account_halt_count均清空后取消，新增待办再建立；shared日常任务保留。详见配套Skill及通用恢复说明，未接通宿主任务系统时不承诺无人值守。

这不是服务器事务或全局“恰好一次”保证：官方 App 或其他未共享记录库的客户端仍可能同时修改。版本指纹在发送前检测变化，不能消除读取与服务器写入之间的竞争。不要把多条业务指令当作原子批处理。若客户端在准备或排队阶段超时，status可能暂时request_not_found；这不证明仍在运行的原调用不会稍后提交，保留请求号，等原调用结束或关闭原服务后再判断，不能换号重发。

`task_execution_observed` 只表示此次回读观察到关联账单。未来跨日/跨月、补执行、自然登录失效和跨机尚未验收。原生报销结算接口要求公测升级，当前不改账号、不将结算假装成普通收入。

工具记录库包含处理过的业务计划与编号，属于私人财务资料；目录0700、数据库0600，不能上传公共仓库。默认状态与安装运行环境分开。备份：

```sh
qianji-agent backup /private/backup/operations.sqlite3
```

恢复时先关闭所有使用此记录库的 MCP/CLI，把备份放回私有状态目录的 `operations.sqlite3`，保留账号绑定。不要只备份代码、不备份防重复记录。已在本机验证0.1.0安装版与新源码共用同一绝对记录库及备份恢复，原请求不再落账。自定义--state-dir必须为绝对路径；不同记录库没有跨库防重保证。

## 命令行与开发验证

无MCP客户端可用相同核心：`qianji-agent query books`、`preview`、`execute <request_id>`、`status <request_id>`。业务JSON从标准输入传入。查询非交互输入可传 `{}`。

```sh
python -m unittest discover -s tests -q
```

测试只使用合成后端。开发目录中的原生验收脚本（不放入公开源文件包）是显式原生写入试验，会在已登录账号创建专用对象，**不会由测试套件自动运行**。不要在他人账号无授权执行。私人试验文件 `evidence/` 不属于安装包或发布源文件。

所有分期提前还款必须显式给出本次提前还款的fee（无费用也写0.00）。工具按原分期总本金、分钱分配及已执行期数计算剩余计划本金；修改/删除历史账单不会更改原计划或执行期数，不把历史费用再抵本金；不自动猜测、追加或豁免剩余费用。

债务历史修改用debt_bill_update，object_id/expected_version指向账单，related_id/related_version指向借贷账户；可改amount/time/remark，不改方向、账户或账本。工具检查剩余本金、loan.money和loan.totalpay；利息不改变本金。已结清记录只开放不改金额的时间/备注维护，无法借修改制造负本金或超额偿还。

0.1.3补齐：纠正还款日原生编码（固定日为纯数字、账单后天数以d结尾），未设置额度默认原生-1；共享额度/解除、父账户版本与关系保护，credit.shareid公开为字符串。子卡credit.limit可能缓存旧额度，使用共享关系查询主卡配置额度，不能视为可用额度。repeat_update支持修改周期、账户、账本和分类，并回读确保旧账单不变、原关联编号不变；若重配同时生成新账则核对新账关系和金额，核对新旧资金账户余额；scheduled_bill_update/copy/delete用于保留repeat任务时维护已生成账单，带账单与任务两份version，副本脱离任务。分期任务本身的本金/期数修改按官方文档不支持；已结清借贷改金额会出现结清/剩余本金矛盾，继续拒绝。分钟试验观测到首笔会在未来时刻前预生成，不能作为未来调度已验证。

0.1.4：installment_bill_update/copy/delete维护正在执行的消费分期生成支出，object_id/expected_version为账单、related_id/related_version为分期任务。支持CNY账目金额（含该期手续费的合计）、时间、备注、分类/账本/资金账户、标签/图片和统计预算标记；更新保留原手续费拆分，金额不得低于这部分费用，不提供借该操作修改分期手续费或计划本金/期数的入口。复制按原生规则保留合计金额，脱离任务并去掉分期费用拆分，成为普通支出；不增加分期执行次数。删除保留计划及已执行期数。上述操作都回读父任务不变。提前还款按未改动的计划计算剩余本金，不能根据改过或删除的历史账单倒推；本次提前还款费用仍须明确给出。

## 开源许可

Copyright (c) 2026 Nevery-qiao。以 [MIT 许可证](LICENSE) 发布，允许使用、修改和分发，保留版权与许可声明。
