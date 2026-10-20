# 挂起事项与宿主跟进

适用于所有新执行结果的交付确认、任何原工具动作出现未知、重启接班、定时核实，以及任务取消/恢复。账单获取仍在调用方；本文不授权新的财务业务或解除用户暂停。

## 每轮按这个顺序处理

1. 连接/能力检查后调用`qianji_recovery_list`，沿`next_offset`读取全部开放项。`total=0`只表示操作恢复清单清空；实际0.2.0再读qianji_account_review及account_halt_count，账户停止仍存在就不能结束跟进；`due=0`、没有waiting或只剩needs_attention/awaiting_ack都不是清空。
2. 新版每条execute即使直接verified/failed也先保留awaiting_ack，防止成功回执送达前断线遗失。先完成能立即完成的台账/处置并确认收尾，再重读剩余清单、处理`tracking`调度意图；清单已空且未建任务就不用创建。仍有无法收尾项时必须保证跟进。宿主支持正规任务工具时，按下文创建/复用/取消并回读；没有调度能力或回读失败时明确未接通，不假称会自动跟进。
3. waiting到`next_check_at`才调用原`qianji_operation_status(request_id,automatic=true)`。不得发execute重试未知。`recovery_not_due`等待；`recovery_requires_attention`保留并升级，不换参数规避自动次数上限。needs_attention仅在有新证据或本人/既有授权明确要求时人工核实，原故障预算和暂停继续生效。
4. awaiting_ack核对原verified/failed回执，先在调用方正常API接续原ledger/日报/处置。钱迹已成功但台账中断，只补回执，不重记。然后用恢复项最新version调用`qianji_recovery_ack`：recorded对应verified；handled_without_recording对应failed且已明确保留/告知未入账结果。引用只给本地处置记录的安全标识或摘要，不传邮件、密码、后台原文。
5. 最后重新列清单、复核账户并处理调度意图，直接汇报新增结果和确需本人处理事项。连续唤醒无变化且无可执行工作时保持安静，不每次重复提醒；超期升级只在首次/实质变化时报告。不得用确认清单来伪造外部台账已保存。若批次日报/用户交付晚于单笔ack，必须先在原调用方STATE/ledger持久保存已核实事实、原请求号及待交付状态，由原每日/管理任务补交；尚未持久移交时保留awaiting_ack。工具closed不代表用户已收到。

## 一个账号一份跟进意图

`qianji_recovery_scheduler()`返回scope_id、generation、desired_active、mode、job_id、action。scope_id是这份账号日志的持久随机标识，不是账号/登录信息；宿主任务的名称或提示保留它，匹配时同时检查目标会话，避免接管别的队列任务。

- action=ensure：先检查同用途、同账号安装、同目标会话的既有任务，存在则复用。没有任务才通过宿主正规工具建立一个专用跟进任务，内容是重复上述只读核实/收尾流程。不要每笔新建；创建结果不明先查原记录，不能盲建第二个。随后正规view回读任务ID、目标、启用状态和排期。
- action=inspect：对已登记job做正规view，更新实际状态；不能因为数据库留有job_id就说仍在运行。
- 回读后调用`qianji_recovery_scheduler(action='record',observation={expected_generation,mode,job_id,observed_state,observation_reference})`。observed_state为active/paused/absent，引用给安全观察标识。这是宿主报告，MCP不能独立证明宿主内部；登记成功也不代表已经实际唤醒过，首次运行要另验。
- dedicated是只负责本恢复队列的任务；shared是已获授权、还负责其他日常工作的任务。不得将一个专用任务随意标成shared逃避清理；也不能取消shared每日记账/管理任务。
- shared排期不满足新waiting及时核实需求时，唯一调度负责人先通过正规工具建立/回读同scope、同目标的专用任务，再record新dedicated观察，额外传replaces_shared_job_id=当前shared任务ID和最新expected_generation。成功会提升generation并保留原日常任务；旧代际回调不能改回绑定。不得把原任务假报absent，也不得把专用任务换标shared逃避清理。CAS失败要重读：仅复用当前有效绑定，妥善取消本次刚建且未被绑定的专用任务并回读，不能遗留孤儿任务。dedicated改绑需先真实取消旧专用任务并登记，不直接替换active旧专用任务。
- 操作open与account_halt_count都归零、且实际调度意图允许后，dedicated的action=cancel：只取消记录的该专用job，再正规回读确认不存在或暂停，登记absent/paused。取消失败保持待处理，不报告已停。shared仅在操作/账户事项都处理完后停止本队列恢复处理，不取消仍承担日常业务的主任务。
- 取消回调遇到schedule_changed：旧代际失效；立即重读清单和调度意图。若新增待办让desired_active=true且action=ensure，修复/恢复唯一专用任务并再次回读登记；不能用“之前已取消”结束。版本冲突同样重读，不照旧确认。
- 再出现第一项待办会再次输出ensure，按同一流程恢复。启动/每批结束以及原日常任务都检查“有待办无有效跟进”并补偿，覆盖创建/取消中断。电脑/宿主停止时不能保证准时唤醒，恢复后补查到期项。

## 宿主接入

Codex使用当前提供的官方任务创建/查看/更新/删除工具，不直接编辑任务文件或调度数据库；按工具实际返回的ID和目标操作。其他Agent使用其正常任务系统，同样要求唯一身份、实际回读、取消回读及启动补偿。

专用任务提示应明确：使用本Skill、原共享journal；复核账户且只核实到期原请求；不execute未知、不新扫来源、不解除暂停/重开旧预算；先补调用方处置再确认；处理全部调度意图；无变化不通知，实际解决、首次升级、调度失败或需要本人时才报告。不要把原账务周期/分期任务当作宿主跟进任务。

## 清单与原业务台账

工具清单只覆盖已通过本工具执行的结果交付，不代替原业务台账。清单open=0不表示来源已收齐、未发送账单已入账、待分类或待授权事项已解决。这些事项仍留在原STATE/ledger，由原日常任务接续，不另造第二份业务账本。

## 普通新账与账户停止（实际0.2.0 / continuation-v1）

恢复清单适用所有工具动作；下面只开放证据完整的普通新增合同，不说明所有复杂业务都能跨未知继续。实际版本、接口及当前账户复核缺任一项，就不宣称已可接续。

- 已结束本地发送的历史unknown仍保留，既有plan/原锚/原号/预算不改。正常新bill_create仅普通CNY收入/支出、单账户、无费用/折扣/图片/标签/任务关系；独立信用与普通账户分别按工具适配，信用共享主/子卡未适配拒绝。工具逐项检查全部旧操作，不仅总数。旧计划无scope注解但可从原plan完整恢复时可判断；缺范围明确停，不用商户/日期/换号假造独立。
- 原ledger确认未发送且用户已授权的真正新交易，保留其canonical及稳定request，用正常preview/execute；preview只看参数不解除保护。字段和当时自然余额都核实才verified，先接原ledger/daily-cycle、持久待交付事实后ack。工具首次采用独立观察点不表示历史已对齐，不改旧核实锚。
- 新unknown或余额冲突会持久停止受影响账户的收入和支出，重启/换对话/新号/改方向都不解除。qianji_account_review每轮开始、批末、交班及原每日/管理任务复核；工具每次新写前也复核。当前结果current=true且账户matched仅是观察证据，仍需原业务有效范围与execute实际依赖保护；不把cached/current=false或unavailable当当前就绪。
- A账户halt不自行停B；B须有完整独立依赖、当前matched及有效业务范围。无法确定影响范围的owner停止约束整个账号。多原因halt只解除有可靠原结果的本请求原因，不因另一个请求成功清其余原因；工具没有force清除入口。
- 旧效果在新账verified后晚到、外部App改变余额/旧账/结构时，后续复核可持久保存account_drift_unexplained并停止该账户。外部合法记账也可能触发保守暂停；不自动重设观察点、改余额或重发新账。休眠/离线不能即时发现，恢复后的首轮及每次写前先核对。差异先在工具留证，再由原唯一执行者写原STATE/例外、原管理者写其管理事实，不建平行业务台账。无可用核对/解释证据就保留停止状态，不能靠“有空再处理”遗失。
- historical_balance_context_unattributed只说明旧余额受后续事实影响，仍pending；不据此auto failed/verified。旧needs_attention不自动复开次数，账户review不重查旧号、不消耗旧核实预算。

## 调用方暂停与日常任务

工具允许不代表工作级故障暂停自动解除。有此暂停的调用方，由原唯一执行者按既有用户授权和实际技术验收，在原状态中登记可审计的有限范围修订及相同work的新有效run，保留旧异常/旧暂停核心字段与原预算。不能另建work或清active来绕过；用户暂停、其他故障、工具halt优先。原p3/日常任务、操作规程必须真实消费修订，不只写无人读取的字段。已有持续日常许可生效后，每新run按实际门槛计算范围，不每天重新等一次总控审批；不得扩大原用户权限。

接续已整理未发送清单时不重复拉来源；这不把“source0”变成日常永久禁取信。原日常来源获取按自己的有效授权继续，工具不负责来源获取。单笔ack后日报未交付事实仍留原STATE/ledger，原任务补交。

操作open=0但account_halt_count>0仍需同一跟进；只处理到期原号和当前账户证据，无变化保持安静。两者都清空后专用任务按正规取消/回读闭环，shared原日常/管理任务保留。安装包/规则更新不等于实际宿主加载、有效范围接入或真实账务验收。

CLI同核心：`recovery-list`、`status <request_id> --automatic`、`recovery-ack <request_id>`（stdin确认JSON）、`recovery-scheduler`/`recovery-scheduler --record`（stdin观察JSON）。调用方明确只准原生MCP时不得改走CLI。
