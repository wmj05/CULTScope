# CULTScope 3.2A 人工审核工作表

- 生成日期：2026-11-17
- 范围：CS-0001《橡皮头》、CS-0002《粉红色的火烈鸟》、CS-0003《洛基恐怖秀》
- 当前状态：三部均为 `pending`，`reviewer`、`reviewed_at`、`confidence` 全部留空
- 重要说明：本表由 AI 整理，`verification_status=verified` 仅表示“已抓取来源正文并核对相关句子”，不代表人工审核通过
- 数据边界：候选标签只记录在本表，尚未写入 `movie_cult_tags.csv`；证据已写入 `movie_criterion_evidence.csv`

## 一、来源与可访问性

| 来源 | 机构/性质 | 层级 | 访问与核对方式 |
|---|---|---|---|
| S-005 国会图书馆 NFR 公告（2006） | 机构 | T1 | WebFetch 抓取正文核对；脚本请求受 TLS 限制 |
| S-006 BFI Sight and Sound（Rosenbaum） | 机构刊物 | T2 | 脚本请求 200，正文核对 |
| S-007 TCM《Eraserhead》条目 | 媒体 | T2 | 脚本请求 200，正文核对 |
| S-008 国会图书馆博客（Sterritt 随笔） | 机构 | T1 | WebFetch 抓取正文核对；脚本请求受 TLS 限制 |
| S-009 Criterion《Pink Flamingos》随笔 | 机构 | T2 | WebFetch 抓取正文核对；脚本请求遇证书告警 |
| S-010 Criterion《Eraserhead》访谈 | 机构 | T2 | WebFetch 抓取正文核对；脚本请求遇证书告警 |
| S-011 Baltimore Magazine 50 周年报道 | 媒体 | T3 | WebFetch 抓取正文核对；脚本请求 403 |

T3 来源只作补充线索，不计入“approved 所需 T1/T2 证据”。

## 二、CS-0001《橡皮头》

候选标准：C1 午夜场与仪式化放映、C2 商业失败后的二次流行、C5 非主流制作与实验美学、C7 评论争议与重新评价、C8 可追溯的文化影响。

| 标准 | 来源 | 证据摘要 | 定位 | 状态 |
|---|---|---|---|---|
| C1 | S-008 | 1970 年代末旧金山午夜场热门，洛杉矶放映持续到 1981 年 | 检索句 `By the end of the ‘70s it had scored a midnight hit...` | verified |
| C2 | S-008 | 首映夜约 25 人、评论反应平淡，之后靠口碑扩大受众 | 检索句 `an opening-night crowd of twenty-five people...` | verified |
| C5 | S-007 | 五年制作、AFI 旧马厩布景、六人剧组 | 检索句 `it took Lynch and his crew of six five years...` | verified |
| C5 | S-010 | 林奇确认五年完成、多在夜间拍摄 | 检索句 `Eraserhead took five years to complete` | verified |
| C7 | S-007 | 2004 年入选国家电影登记处；2010 年 OFCS 评为第二佳处女作 | 检索句 `In 2004, the film was added to the National Film Registry` | verified |
| C8 | S-007 | 影响《七宗罪》《巴顿·芬克》《铁男》等 | 检索句 `The film had a major cultural impact...` | verified |

候选文化标签（待人工确认，未入库）：

| 标签 | 依据 | 待确认事项 |
|---|---|---|
| aesthetic_surrealism | S-008 论及其超现实主义脉络 | “超现实”是否应作为独立标签而非美学描述 |
| aesthetic_low_fi | S-007 制作条件 | 低成本是否足以构成“粗粝低成本”标签 |
| aesthetic_experimental_narrative | S-008 论及非线性/声画实验 | 与“实验叙事”定义是否吻合 |
| theme_identity_anxiety | S-007 提到林奇对父职的恐惧 | 需引原文具体句，当前为转述 |
| influence_subcultural_symbol | S-007 提到 T 恤与海报持续销售 | 是否达到“亚文化符号化”的纳入条件 |

待解决：C2 缺少首轮票房/发行数据；“评价上升”缺少不同时期评论对照。

## 三、CS-0002《粉红色的火烈鸟》

候选标准：C1 午夜场与仪式化放映、C3 亚文化与边缘群体认同、C4 审查与内容争议、C5 非主流制作与实验美学、C7 评论争议与重新评价。

| 标准 | 来源 | 证据摘要 | 定位 | 状态 |
|---|---|---|---|---|
| C1 | S-009 | 1970 年代长期午夜场放映，1975 年 DEVO 在 Kent State 放映场演出 | 检索句 `Still going strong after years on the midnight circuit` | verified |
| C3 | S-009 | 称人物为 `honest-to-God marginals`，置于 queer underground 脉络 | 检索句 `they are honest-to-God marginals` | verified |
| C5 | S-009 | 被称为 `gloriously subunderground filmmaking`，Dreamland 作坊制作 | 检索句 `this is gloriously subunderground filmmaking` | verified |
| C4 | S-011 | 真实法庭审查诉讼；1990 年 Orange County 大陪审团起诉音像店 | 检索句 `As late as 1990, an Orange County... grand jury indicted` | verified（仅 T3） |
| C7 | S-011 | 1974 年《Variety》恶评，后在文章发表前入选国家电影登记处 | 检索句 `one of the most vile, stupid, and repulsive films ever made` | verified（仅 T3） |

候选文化标签（待人工确认，未入库）：

| 标签 | 依据 | 待确认事项 |
|---|---|---|
| production_independent | S-009 Dreamland 作坊与极低预算 | 与“独立制作”定义的边界 |
| production_censorship_controversy | S-011 审查诉讼 | 需 T1/T2 审查档案支撑 |
| reception_midnight_movie | S-009 午夜场放映 | 需具体影院/节目单资料 |
| theme_sexual_transgression | S-009 对禁忌与性越界的描述 | 需引原文具体句 |
| aesthetic_camp | S-009 `camp spectacle` 表述 | 与坎普定义是否一致 |

待解决：C4、C7 目前只有 T3 媒体来源，按项目规则不能计入 approved 所需证据；需补 T1/T2 的审查档案、学术文献或资料馆记录。

## 四、CS-0003《洛基恐怖秀》

候选标准：C1 午夜场与仪式化放映、C2 商业失败后的二次流行、C3 亚文化与边缘群体认同、C6 粉丝仪式化参与。

| 标准 | 来源 | 证据摘要 | 定位 | 状态 |
|---|---|---|---|---|
| C1 | S-005 | 国会图书馆称其为 `the ultimate "midnight movie"` | NFR 条目段 | verified |
| C1 | S-006 | 1976 年 4 月 Waverly 午夜场重开，每周两场，扩散至约 180 家影院 | 正文第 5 段及仪式段 | verified |
| C2 | S-006 | 英美首轮商业失败，随后改午夜场形成 cult | 检索句 `the film was a commercial failure...` | verified |
| C3 | S-006 | 记录纽约、圣地亚哥午夜场的同性恋观众与 gay bars 接受 | `According to Ed Bordenka...` 段 | verified |
| C6 | S-005 | 称其“revolutionized... audience participation” | NFR 条目段 | verified |
| C6 | S-006 | 喊台词、抛米、水枪、雨伞、片前 Time Warp 与扮演 | 仪式相关段落 | verified |

候选文化标签（待人工确认，未入库）：

| 标签 | 依据 | 待确认事项 |
|---|---|---|
| reception_midnight_movie | S-005、S-006 | 无 |
| reception_fan_ritual | S-006 仪式描述 | 是否与“粉丝仪式”定义完全一致 |
| reception_cult_revival | S-006 失败后重映 | 是否属于“口碑逆袭”而非单纯发行策略 |
| theme_sexual_transgression | S-006 性解放与易装表述 | 需引原文具体句 |
| aesthetic_camp | S-006 `campy indifference` | 与坎普定义是否一致 |

待解决：C3 主要依据 1980 年观察，建议补充更近的社群研究；标签证据需逐条引用原文。

## 五、人工审核清单

1. 逐条打开来源链接，确认 `locator` 中的检索句确实存在且支持 `evidence_summary`；如不支持，将该行改为 `disputed` 或删除。
2. 为 CS-0002 的 C4、C7 补充 T1/T2 来源；在此之前不得将该片标记为 approved。
3. 确认候选标准是否成立（每片至少两条 verified + T1/T2 才满足项目审核规则）。
4. 从候选标签中决定是否入库；入库时填写 `origin=manual`、`evidence`、`source_ids`、`annotator`、`reviewed=true`。
5. 人工审核完成后，才可填写 `reviewer`、`reviewed_at`、`confidence`，并追加 `review_log.csv` 记录（含哈希链）。
6. 本轮不生成任何 approved 记录，审核日志保持为空。
