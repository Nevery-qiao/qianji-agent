---
name: qianji-bookkeeping
description: Use when an Agent should query or change the user's Qianji books, accounts, bills, refunds, debts or recurring/installment tasks through the installed qianji-agent MCP. Does not acquire bills or operate the Qianji UI.
---

# 钱迹后台记账

## 首次接入先识别环境

先核实 Agent 的 MCP 命令实际在钱迹所在 Mac 运行，还是云端/另一台机器；再查平台真实支持 stdio 命令或远程 MCP URL。品牌名称、诊断进程是 Mac、能远程执行 Mac shell，都不能代替这项核对。安装本项目后可用 qianji-agent-connect 离线判断；缺信息先补齐，不把 ready_for_validation 当接通。路线见[通用接入指南](https://github.com/Nevery-qiao/qianji-agent/blob/main/docs/AGENT-CONNECTION.md)。

同机且支持 stdio 才配置 Mac 绝对路径。云端且支持 URL 时连接 Mac 上的鉴权 HTTPS 只读入口；云端仅支持 stdio 时明确缺口，不复制登录材料或新建 journal。远程 access_mode=remote_readonly、operations=[] 是当前权限事实，只能调用列出的五工具。不能因后文介绍完整业务而尝试财务 CLI/SDK、preview、execute、旧 status、ack 或 scheduler。实际平台握手、工具、完整恢复分页和 fresh 账户复核通过，才称远程只读接通；正式写入和生产交班另按真实授权及验收。

调用已安装的 `qianji-agent` MCP。首次使用前，用户需要正常登录自己的钱迹官方App。连接失败先区分具体原因：只有实际确认登录已失效才请本人在官方App重登；app_access_denied是当前进程读取受限，不能据此当登录过期，不反复重登或改账号。按正常权限/宿主连接方式处理，不复制凭据绕过。不要要求绑定邮箱、改变账号或修改App。

先用 `qianji_connection` 检查连接，`qianji_capabilities` 查看当前开放动作；能力清单与安装包验收矩阵中的限制优先于猜测。没有支持的业务返回缺口，不能把报销、退款或债务伪装成普通收支，也不能改用界面操作。

开始工作、每批结束及接班时，调用`qianji_recovery_list`查看全部分页；历史消息没有原请求号也必须从持久清单发现。遇到开放待办或tracking.action不是none，先读[挂起跟进与宿主调度](references/recovery.md)。旧版没有这些入口时明确未接通通用恢复，不声称无人值守就绪。runtime_version证明实际运行版本，配置路径不算加载证明。实际加载0.2.0且存在qianji_account_review时，开始/批末/接班调用该工具复核账户；只有本次current=true且contract=continuation-v1的结果可作当前观察，其他工具附带cached摘要即使有过去状态也不能当新核验。scope中逐账户看matched/halted/unavailable，aggregate ready=false可能来自其他账户，不自行扩大成全部账户停止。旧版本没有该入口时不声称新接续/晚到监测已接通。

待办的waiting只能按原号核实，到期自动检查用qianji_operation_status(automatic=true)；needs_attention不得因定时唤醒重置次数或绕过原暂停。所有新版execute结果（含直接成功/失败）都保留awaiting_ack，防止回执送达前断线遗漏；它代表结果已查明但调用方尚未收尾：先接续原台账/交付，再以最新version和不含私密内容的处置引用调用qianji_recovery_ack。verified用recorded，failed用handled_without_recording，后一种不代表已入账；未知不能确认关闭。ack前须真实持久移交原台账/处置；日报尚未交付时在原STATE/ledger保留请求号、事实和待交付状态，未持久移交不ack，closed不代表本人已收到。能立即完成的台账与ack先做，再按剩余清单处理调度，避免每笔无必要创建任务；open=0不等于未发送账单/来源/分类或账户异常全部完成，原业务台账和日常任务继续保留；同时查看account_halt_count及当前account_review。新账能否独立继续由工具依赖保护和原业务有效范围共同判断，详见恢复参考的“普通新账与账户停止”。不能手改plan、换journal、清未知或自行强制放行。

## 选择对象与形成指令

用 `qianji_query` 查找账本、账户、分类、标签和原账目。按真实编号选择；同名时比较归属、币种和类型，有歧义再向用户澄清。不要以“第一个账户”或默认账本代替用户意图。标签查询返回分组和嵌套标签；标签编号是不透明字符串。

基础币当前必须为CNY。外币收支使用currency/amount指定交易原币，account_amount指定账户币金额，base_amount指定CNY金额；同币金额必须相等。跨币转账的amount为目标币净额，currency为目标币种，account_amount为转出本金，base_amount为CNY等值；跨币手续费fee为来源账户币金额，fee_base_amount必须显式给出费用的CNY金额，base_amount保持本金等值；余额从来源扣本金加费用，不猜汇率。外币退款的currency/amount是原单交易币及本次退回原币金额，account_amount是退款到账金额，base_amount是本次退款CNY金额；按原币累计限额，可退至不同账户。不要猜汇率。转账/还款的amount是转入净额，fee另扣转出侧；CNY支出amount是实付金额，discount单独记优惠，不能再减一次。

金额必须是精确字符串（如 `"12.50"`），对象编号保持字符串，时间使用带偏移的完整时间（如 `"2026-10-18T12:30:00+08:00"`）。收入/支出分类类型必须匹配；转账与信用卡还款明确两侧账户。是否需要用户确认取决于实际用户授权，不要求每笔都重复确认。

每条独立业务指令生成一个唯一 `request_id`，重查或重试同一指令始终保留它。同日同额的不同交易使用不同编号，不擅自去重。修改/删除先读取目标，将最新 `version` 作为 `expected_version`；发生冲突时重新核对，不能照旧覆盖。

`qianji_preview` 可检查指令和余额影响，但它不会落账，也不锁住服务器数据。实际执行使用 `qianji_execute`。

## 根据回执行动

- `verified`：原生记录和该操作要求的字段/余额已经回读核验。向用户报告对应结果，保留对象编号。
- `pending_verification`：可能已经记上。只调用 `qianji_operation_status`；客户端超时后即使暂时request_not_found，也需等原调用结束或停止原服务，不能据此换号重发。不要改用新请求编号重发，也不要先写一条反向记录。
- `not_executed`：说明缺少字段、引用、版本冲突或连接问题，修正原因后再执行。未执行的原请求可修正；已记录为failed的请求会保留失败结果，修正后的新指令使用新编号。`previous_result_unknown`、account_halted或continuation.decision_code中的停止原因不能当缺字段修正后绕过；查当前account_review和原恢复项，未知只在原预算/授权内核实。
- `failed`：后台拒绝且已核实无效果；说明具体能力缺口，不做语义替换。
- `unsupported`：当前适配器没有开放该操作。不要探测任意后台路由或修改原生账号设置。

0.1.8发送留证修复版的待核实回执还可给出dispatch_state、dispatch_error_code和verification_code：它们只说明原发送留证与当前核验障碍，不是成功或允许重发的证明。not_recorded表示旧请求未保存该证据，unavailable表示证据暂不可读，二者不能互相替代；旧版没有字段时不推断其值。原生原号查询只有在真实记录完整核验通过，或原发送已明确拒绝且完整快照证明无效果时，才会正常更新结果。后台原文只留私人日志，不粘贴到聊天。财务未知时不另开日志或绕过保护；只有实际新合同和原业务范围都允许，才可正常execute独立新账。新账仍须字段及当时自然余额同时核验，不把“挂起旧账”当放弃核验。historical_balance_context_unattributed表示后续新账使旧余额不够归因，旧请求仍pending，不能猜成功/失败或重开自动次数。

图片先调用attachment_upload(image_path为绝对路径)，只把核验回执image_key放入账目image_keys。只接收有效、单帧PNG/JPEG，文件不超过8MB且不超过2400万像素；损坏、动画或超限图片会在上传前拒绝。storage_hash_verified=true表示上传存储回执的哈希匹配；file_content_verified=true才表示下载字节与原文件SHA256一致。image_pixels_verified=true表示已通过正常TLS校验，从官方账单图片域名取回native_huge显示版本，按EXIF方向归一化后尺寸和RGBA像素完全相同；服务可能重新编码，所以file_content_verified=false与image_pixels_verified=true可以同时成立，不能说原文件字节已验证。download_variant=native_huge不是原文件下载证明。只有存储哈希通过且两种内容核验都未通过时，才仅报告上传存储核验，不猜是证书、网络还是像素不匹配，也不降低TLS。旧版本未给出新字段时不推断像素已通过。删除账单不保证删除云端文件。唯一允许显式重试的未知写入是相同请求/相同内容键的图片上传，财务未知请求仍禁止重发。

refund_update不是普通账目局部修改：必须传object_id及最新expected_version，并完整给出account_id、amount和time。用户只改金额时，先查原退款，沿用其到账账户和交易时间，不自行换账户或改为当前时间；外币再补明确原币/账户币/CNY金额。写前not_executed缺字段可沿原请求补齐；已写入或待核实仍只查原请求。

账户status=active/hidden/finished/all用于统一查找隐藏及结清对象；自定义操作记录目录必须为所有Agent共用的同一绝对路径。普通账目可更换book_id/account_id/to_account_id，换账本时同时指定该本匹配的category_id。子分类换父级使用category_move；category_update用于改名，category_promote升为根分类，category_demote降为指定parent_id的子分类，不允许第三层。account_update保留余额与类型，只改名称、备注、计总资产标记及信用额度/日期。分期fee是全部期数的总手续费，fee_method为average/first/last，remainder为first/last；不是每期手续费。提前还款的关联记录，在分期任务已删除后，必须显式指定付款及关联支出的两份最新version，使用prepay_records_delete成对维护；不能称为撤销分期。

任务保存成功与未来自动出账分开汇报。`task_execution_observed` 只代表此次回读确实看到了关联账单，不证明未来跨日/跨月必然执行。

无MCP的Agent可用命令行：`qianji-agent query books`、`qianji-agent preview`、`qianji-agent execute <request_id>`、`qianji-agent status <request_id>`。查询筛选或指令JSON从标准输入传入；与MCP共用默认操作记录目录，不能给每个Agent另配一套记录库。

账单获取、OCR和自然语言提取由调用方完成。登录信息、原始后台错误与工具记录库不进入聊天或公共仓库。

所有分期提前还款必须显式给出本次提前还款的fee（无费用也写0.00）。工具按原分期总本金、分钱分配及已执行期数算剩余计划本金；历史账单增改删不会更改计划或执行期数，不把费用再抵本金；不自动猜测、追加或豁免剩余费用。

借还款历史维护使用debt_bill_update：object_id是原账单，related_id是借贷账户，两者最新version分别放expected_version/related_version；只修改amount/time/remark，不能悄悄改借贷方向或归属。本金、已还本金和现金余额分别回读，利息不计入本金；已结清债务只允许时间/备注等不改金额的维护，金额变更明确拒绝。不可用普通bill_update绕过。

共享信用额度：account_update的shared_limit_account_id为主信用账户ID，shared_limit_version带主账户最新version；-1解除共享，不同时填写limit。只连接同币种独立主卡，不创建自引用或链式共享。主卡有成员时不能删除/清空额度，先解除共享。子卡credit.limit可能是历史缓存，读取公开credit.shareid后查询主卡额度；不能把缓存或配置额度当作可用额度。

周期任务的repeat_update还可更换repeat_unit及相应repeat_value/repeat_values、book_id/account_id/to_account_id/category_id；官方说明改周期可能重置次数，本次原生试验未出现重置，不能承诺一定重置或一定不重置；旧账单与原关联编号必须不变。重配若同时出新账，必须回读新账关系、金额及新旧资金账户余额才报成功。已生成的周期账单用scheduled_bill_update/copy/delete，object_id/expected_version为账单，related_id/related_version为repeat任务；副本会脱离任务，不能当新增执行次数。这组动作只用于repeat；分期生成账单使用下述独立动作。

跨币手续费与本金必须能由钱迹同一套原生换算比率表达，工具会核对二者按分舍入后的金额；fee_conversion_inconsistent表示无法同时保存这些明确金额，不擅自替换汇率。

正在执行的CNY消费分期生成账单，用installment_bill_update/copy/delete；两份版本分别对应账单和installment任务。amount是该期本金加手续费的账面合计，更新保留原费用拆分，不能改到低于已含费用；fee/discount/外币转换不由这组动作处理。复制保留合计金额，但副本成为普通支出，原生会移除分期费用拆分；要向用户解释，不能称仍关联分期或次数增加。修改/删除账单后原计划及已执行期数不变；提前还款依原计划剩余本金，不从修改后的历史账单倒推。已提前还款任务及退款等混合关联不支持此维护，不能绕过通用账目保护。
