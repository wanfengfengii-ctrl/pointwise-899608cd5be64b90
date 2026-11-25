# 澄湾参考数据交换归档

澄湾联合材料试验中心用固定修订核清试次实际领用的参考。岚河材料检测站收取指定试次的交换件，关源后凭实收号和暂停采信通知复核。接续试验人员凭报告号领取参考原件出处，或根据无参考结论安排补测。

## 运行

在项目根目录使用 Python 3.11，依赖均为标准库。

```text
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 是物化时提供的完整回归入口。演示显式准备独立的临时站库与隔离库，写入 `samples/shift.json`，关闭站库，重开隔离库后签报，再从报告存档读回原结论。`samples/alternate.json` 给出同一外发试次原领用相同、撤批后的领用不同的对照源记录。

## 一天的交接

1. 白班登记参考入列和试次取用批次。工作修订从首个合法批次开始，后续可继续加入批次。
2. 编制员冻结指定工作修订。冻结号指向当时已提交的批次和有序事件。
3. 编制员核在线账。样例中同值的 R1、R2 分先后入列，内部试次先取 R1，外发试次 V 取 R2。
4. 编制员选择 V 发行固定件。补发时凭发行号取首次字节。
5. 合作方实收并保存首执。相同字节复投返回第一次的实收号和首执。
6. 夜班关闭源库，重开隔离库，以原实收号分别提交零撤批、撤 BH、撤 B1 和撤 BV 的请求。
7. 隔离端按每次请求重新计算，依次签出 V 引用 R2、V 引用 R1、V 无参考及空行集。
8. 接续试验人员凭原报告号复领首份结论及首执，原结论仍引用 R2。

## Python 接口

先分别创建 `RecordingStore(path)`、`DispatchArchive(path, issuer)`、`ReceiptStore(path)` 和 `ReportStore(path)`，调用各自的 `initialize()`，用完调用 `close()`。站端两个库实例可指向同一个站库文件，隔离端两个库实例可指向同一个隔离库文件。调用方管理各实例的连接生命周期。重复初始化保留已有记录。发行归档的发行单位在首次初始化时绑定。

| 模块与入口 | 输入和结果 |
| --- | --- |
| `record.batches.record_batch(store, working_revision, batch, events)` | 整批登记，返回工作修订号。事件类型为 `record.events.ReferenceArrival` 和 `TrialUse`。参考出处为 `record.origins.ReferenceOrigin(batch, document, line)`。 |
| `record.revisions.freeze(store, working_revision)` | 返回新的不可变冻结号。`read_frozen_revision(store, revision)` 读回其工作修订、批次和有序事件。 |
| `assign.ledger.online_ledger(store, revision)` | 返回原序排列的试次账行。账行的 `reference` 为实际参考事件或 `None`。 |
| `issue.dispatch.issue_package(store, archive, revision, trials)` | 冻结修订内所选试次的集合可为空，返回归档后的 V1 字节。`issue.package.decode_envelope(wire)` 可读取发行号。 |
| `issue.dispatch.reissue_package(archive, dispatch_id)` | 返回首次归档的字节。 |
| `receive.register.accept_package(store, wire)` | 返回实收号 `receipt_id` 和原首执 `acknowledgment`。同号判定以发行单位及其发行号为准。 |
| `receive.lookup.get_received(store, receipt_id)` | 返回准确原件 `wire`、发行单位、发行号、冻结号、校验值及首执。 |
| `review.request.audit_package(receipts, reports, request)` | `AuditRequest(receipt_id, request_id, excluded_batches=())` 指定本次来件及撤批。返回正式报告及首执。 |
| `review.history.get_report(store, report_id)` | 直接领回报告号、请求号、实收号、撤批集合、原有序报告行及原首执。 |

编号、原件文档名、相容键和单位采用非空可打印文本，首尾无空白。出处行号是正整数，出处批次与入列批次一致。参考测值用有限十进制文本记录并保留原精度与单位。试次可省略测值和单位，也可成对提供。原序是整数，与物理提交顺序无关。一个工作修订内每个序位只能出现一次，参考实例号、试次号各自在其类型内唯一。非法事件、冲突序位或重复批次使整批失败。未知修订、来件或报告编号抛出 `KeyError`，非法范围、坏件、同号异件和未知撤批抛出 `ValueError`。SQLite 签存异常沿调用返回，报告和首执一同回滚。相同报告请求号与相同实收、撤批复投可领原报告，同号异参拒绝。

## 计算与固定件

在一次计算中，按原序处理事件，每次取用消费当时已入列、相容且未被消费的最早参考。站内按原相容键的相等关系判定相容，无需换算或浮点比较。同值异出处的参考分别入列。无参考时保留试次行，参考为 `None`。以后入列的参考从其原序开始可用。

V1 外层为 UTF-8 JSON，字段为 `version`、`issuer`、`dispatch_id`、`revision`、`body`、`checksum`。校验值是其余五个字段按键排序、紧凑 ASCII JSON 序列化后的 SHA-256 十六进制值，用于完整性核验。发行端将参考实例、可披露出处、批次、原序、所选试次及派生资格定版。内站试次的原名、原相容键和原测值只保留在站库。隔离端核验正文结构和可核对的引用关系，实收后保留精确字节。每次撤批计算从指定实收件独立起步，已撤批的入列和取用同时退出，只有留存的已选试次进入报告。报告中有参考时携带实例号、原序、批号及文档行号。

历史 V1 原配对件支持实收、按原号原样领取及零撤批签报。需要重新计算时使用带重放依据的发行件。历史合法报告始终直接从签存记录读取。
