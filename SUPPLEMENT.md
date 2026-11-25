# 补到样交接

岚河在接收固定试次数据后，可能在一个已登记的班次交接点补录同类实物。站库关闭后，质控员用该实收件与自己的核准到样清单签报。报告用于按实际参考出处复测。

## 发行和实收

在 `issue.dispatch` 提供 `issue_supplement(store, archive, revision, trials, compatibility, gates) -> bytes`。`revision` 指现有冻结号。`trials` 沿用原选择的集合语义，所选试次均须属于 `compatibility` 指定的相容类。其他类的入列和领用与本件无关。选空集可发行。`gates` 为按冻结原序截点非递减排列的 `(点号, 截点)` 对，点号唯一，截点为整数且布尔值无效。补到样在该截点及此前的站内事件之后入队。同截点多点采用声明顺序。档案号、点号及其他标识沿用 README 的文本规则。

发行时补到样尚未知。每两个公开边界之间只交整段领用依据，允许列出同类参考的有序身份和出处，内部试次的名称、批次、原序、逐条消费记录和相容原键留站。所选试次和交接点是公开边界。第一处公开边界之前也按整段口径处理。所选试次的原序与身份可公开，内部测值及其他类的参考出处留站。段证据的表示由实现决定，须对任意合法到样保持原领用口径。

V2 沿用 README 的外层字段、校验值口径和发行来源绑定，`version` 为整数 `2`。`issue.package.decode_envelope` 可读两版外层。原 `reissue_package` 按发行号补发原字节。原 `accept_package` 入口按版本核验外层、正文的结构、公开边界及证据引用，坏件不入账。同一发行来源同字节复投返回原实收号和首执，同号异件拒收。

## 隔离签报

隔离端以 audit_supplement(receipts, reports, receipt_id, request_id, arrivals) 仅凭指定 V2 实收签报。函数位于 `review.request`。`arrivals` 为有序的 `(点号, 补到样号, 文档号, 行号)` 列表或元组。各项均为本站已核准的同类实物。行号为正整数且布尔值无效。点号必须在所选实收件声明，补到样号全单唯一，站内号与补到样号由不同来源区分。在每一点内按来样清单原序入队，各点按发行时声明的顺序执行。清单的有效顺序即按点重排后保留点内相对顺序。

一次复核从空队开始，按冻结原序接续站内领用和本站到样。每个试次领取当时最早的同类未用参考，已用参考不得在后段重现，空缺记 null。后到实物不追改已完成的试次。报告仅列所选试次并按原序排列。V1 件走原签报入口，V2 件走补到入口。坏件、非法输入和请求号异参复用按现有方式抛出 `ValueError`，未知编号按现有方式抛出 `KeyError`。

返回对象通过 `report_id`、`request_id`、`receipt_id`、`arrivals`、`rows` 和 `acknowledgment` 读取。`arrivals` 为有效顺序的四元组之元组，`rows` 沿用原有序行的 `position`、`trial` 和 `reference`。站内参考沿用 V1 的参考字段并附 `source: station`。补到参考含 `source: arrival`、`reference`（补到样号）、`gate`（点号）以及含 `document` 和 `line` 的 `origin`。缺参考时 `reference` 为 `None`。报告、有效到样和首执同次签存，提交失败无新增成果。相同请求号与同一实收及同一有效到样清单复投领原报，异参拒绝。关闭站库后可签，重开隔离库可按报告号领取。通过原 `review.history.get_report` 领取两版报告，V1 撤批及已签历史保持原口径。

## 样例和交付核验

`samples/supplement.json` 的 `common_batches` 可按 README 的事件格式分别登记为 A、B 两个工作修订。甲另录 `a_only`。各自冻结后，用文件中的 `trials`、`compatibility` 和 `gates` 发行。样例故意把 W 写在选择列表首位，报告仍按 V、W 排列。`cases` 给出第一个和第二个交接点的实际输入及两份来件的预期参考号，`null` 表示没有参考。甲在首点依次补 X、Y、Z 时，V 领 Z，其出处为 `partner-register` 第 3 行，W 领站内 R1。把 X 改在 V 后的交接点录入时，两件都是 V 领 R2、W 领 X。

`python3 -B supplement_check.py control` 用完整样例原事件核对参照，并走一次 V1 实收和签报。交付时将现有 `.pointwise-runtime.json` 的 `verify` 和 `demo` 接到补到业务，保留其版本、类型、准备列表及 argv 写法。可使用 `python3 -B supplement_check.py verify` 运行原回归及补到核验，失败须退出非零。`python3 -B supplement_check.py demo` 在关源后签报，重开后显示原报告的实际出处与首执。
