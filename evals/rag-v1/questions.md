# RAG 评测题目与验收要点（40 题）

来源于 cases.json v1.0.0。评分方法见 [README](README.md)，机器可读原文摘录见 [cases.json](cases.json)。这不是已经跑出的模型成绩。

测试时只把“问题”发给 RAG，不发送验收要点或本文件。

## FT01 · 故障定位

问题：FT测试中USB错误是为什么？

类型：answerable；来源：用户原问题。

验收要点：

- 找不到 product=CherryUSB ADB 的设备或 speed 不等于 5000，USB 检查失败
- 枚举和速率通过后，还要用 ADB 发送 date 并检查 timestamps:；该环节失败为 ADB 错误
- 这些是文档的失败分支，不能据此确定本次设备的物理故障

不应出现：仅复述连接异常而没有判断条件；断言一定是线坏或供电不足。

格式：分点，区分 USB 与 ADB。

依据：1820_test.text.md / USB_TEST - USB自动测试项。

## FT02 · 故障定位

问题：USB错误是为什么?

类型：partial；来源：用户原问题。

验收要点：

- 明确按知识库中的 FT USB_TEST 场景解释，或先询问场景
- 给出设备枚举、5000 速率和 ADB 检查方向
- 说明确定本次原因需要实际测试日志

不应出现：把 FT 文档当成所有 USB 故障的唯一原因。

格式：简短说明适用范围。

依据：1820_test.text.md / USB_TEST - USB自动测试项。

## FT03 · 精确标识符

问题：USB_TEST 查找哪个 USB product，要求 speed 是多少？

类型：answerable；来源：文档衍生。

验收要点：

- product 为 CherryUSB ADB
- speed 为 5000

不应出现：把 5000 写成 480。

格式：保留标识符和数字。

依据：1820_test.text.md / USB_TEST - USB自动测试项。

## FT04 · 分支判断

问题：USB 已找到且 speed=5000，但 date 输出不含 timestamps:，应归类为什么错误？

类型：answerable；来源：文档衍生。

验收要点：

- ADB 命令通信测试失败，返回 ADB
- 不应说是未找到 USB 设备

不应出现：归类为设备枚举失败。

格式：直接回答。

依据：1820_test.text.md / USB_TEST - USB自动测试项。

## FT05 · 日志理解

问题：文档示例的 USB0 重试了多少次？最后有哪些失败标记？

类型：answerable；来源：文档衍生。

验收要点：

- 共尝试 3 次，不是初次加 3 次
- USB0 test failed after 3 attempts；USB Connection Test Failed

不应出现：所有版本固定重试三次。

格式：限定为文档示例。

依据：1820_test.text.md / 错误日志快速定位。

## FT06 · 日志定位

问题：FT 的测试日志在哪里，怎么定位 USB_TEST 的过程？

类型：answerable；来源：文档衍生。

验收要点：

- 上位机工具 LOG 文件夹，SN-日志命名的 txt
- 搜索 Errors: 定位失败项
- 查看 Executing_Test 到 Done_Test 之间的过程

不应出现：把板端 /tmp 当成文档指定的上位机日志目录。

格式：分点步骤。

依据：1820_test.kg.md / 日志分析。

## FT07 · 命令精确性

问题：怎么进入 RK182x 的 PCIe 虚拟控制台，怎么退出？

类型：answerable；来源：文档衍生。

验收要点：

- 在 RK3588 端执行 rknn-console rk1820
- Ctrl+X 退出

不应出现：改写成 rknn console；把 Ctrl+C 当成文档退出键。

格式：命令用行内代码或代码块。

依据：1820_test.text.md / 虚拟串口控制台。

## FT08 · 命令对比

问题：文档里上电下载固件、上电拉住复位、下电分别用什么命令？

类型：answerable；来源：文档衍生。

验收要点：

- 上电下载固件：rk1820_boot.sh
- 上电拉住复位：rk1820_boot.sh reset
- 下电：echo_rk1820_stop_test

不应出现：遗漏 reset 参数；建议无条件执行这些有状态操作。

格式：三项映射，作为文档说明。

依据：1820_test.text.md / 调试方法；1820_test.text.md / 下电RK182x模组。

## FT09 · 流程对比

问题：FT1、FIT1、IQC 在 SN 和产品号处理上有什么区别？

类型：answerable；来源：文档衍生。

验收要点：

- FT1 设置 SN，并有 SN_MATCH_SOC
- FIT1 有 BURN_CHECK_PN、SN_MATCH_FAN_DET 和 SET_PN
- IQC 有 PN_GET，读取产品号

不应出现：说三个阶段都会写产品号。

格式：三项对比。

依据：1820_test.kg.md / FT1功能测试步骤；1820_test.kg.md / FIT1功能测试步骤；1820_test.kg.md / IQC测试步骤。

## FT10 · 精确数值

问题：MEMORY 测试里 RK1820 和 RK1828 的 DDR 容量各是多少？

类型：answerable；来源：文档衍生。

验收要点：

- RK1820：2560MB
- RK1828：5120MB

不应出现：颠倒容量。

格式：简短对应关系。

依据：1820_test.text.md / 错误详情 MEMORY。

## FT11 · 故障区分

问题：FIRMWARE_UPGRADE 的 Loader 和 Upgrade 错误有什么区别？

类型：answerable；来源：文档衍生。

验收要点：

- Loader：未成功进入 Loader 模式
- Upgrade：进入升级环节后固件升级失败

不应出现：都解释成固件文件损坏。

格式：分点对比。

依据：1820_test.text.md / FIRMWARE_UPGRADE - 固件升级测试项。

## FT12 · 流程理解

问题：BURN_CHECK 从哪个 vendor data 项读取结果，怎么判断通过？

类型：answerable；来源：文档衍生。

验收要点：

- pcie_upgrade_tool rvd 6
- 读取提取成功且以 _PASS 结尾才通过

不应出现：从 SN 的 item 1 判断老化通过。

格式：保留命令和后缀。

依据：1820_test.text.md / BURN_CHECK - 老化检查测试项。

## FT13 · 精确标识符

问题：产品号 PN 和 SN 分别从哪个 vendor data 项读取？

类型：answerable；来源：文档衍生。

验收要点：

- PN：pcie_upgrade_tool rvd 5
- SN：pcie_upgrade_tool rvd 1

不应出现：把 PN、SN、老化结果的 item 混淆。

格式：两条只读命令。

依据：1820_test.text.md / GET_PN - IQC测试读取产品号。

## FT14 · 条件约束

问题：SET_PN 是否任何时候都能执行写入？文档要求什么前提？

类型：answerable；来源：文档衍生。

验收要点：

- 前面测试全部通过且 SN 匹配风扇
- 根据内存容量和风扇信息选产品号
- 需要按流程进入 MaskRom，再加载 bootloader 进入 Loader 后写入

不应出现：建议直接无条件执行 wvd 5。

格式：前提和流程分点。

依据：1820_test.text.md / SET_PN - 老化检查后写入产品号。

## FT15 · 数值与步骤

问题：文档中的 FAN 测试如何设置占空比，转速合格范围是多少？

类型：answerable；来源：文档衍生。

验收要点：

- 100% 占空比时 RPM 为 17000±20%
- 0% 占空比时 RPM 为 0

不应出现：把百分比当温度范围。

格式：两步。

依据：1820_test.text.md / 错误详情 FAN。

## FT16 · 适用范围

问题：USB_TEST 已在 SODIMM 验证，是否就能保证 M.2 测试没风险？

类型：answerable；来源：文档衍生。

验收要点：

- 不能保证
- 文档指出 M.2 硬件线路未改存在测试风险；USB_TEST 在 SODIMM 上验证

不应出现：把 SODIMM 验证等同于所有 M.2 版本验证。

格式：明确结论及依据。

依据：1820_test.kg.md / 测试风险项。

## DEP01 · 完整步骤

问题：介绍一下ROCKRAGCLAW怎么复现

类型：answerable；来源：用户原问题。

验收要点：

- 准备 RK3588、Debian、交叉编译工具链和 RockX SDK
- 基于目标板 device.inf 获取 key.lic
- 设置编译器和板 IP，执行 deploy_rkrag.sh
- 模型单独放入 /userdata/rkrag_cli/rag_model/
- 启动 run.sh 或 run_server.sh 并验证；QQ 使用还需 OpenClaw 集成

不应出现：只讲环境或只讲部署模型就称完整复现；混用当前 LightRAG 的 /userdata/rklight-rag 路径。

格式：有序步骤，可简短但不能硬裁成两步。

依据：工程部署指南.kg.md / 环境准备；工程部署指南.text.md / SDK 授权；工程部署指南.kg.md / 快速部署步骤；工程部署指南.text.md / 快速部署步骤。

## DEP02 · 环境要求

问题：ROCKRAGCLAW 指南要求什么操作系统、工具链和板端依赖？

类型：answerable；来源：文档衍生。

验收要点：

- Debian
- gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu
- curl、python3；RockX SDK

不应出现：把指南要求说成所有平台唯一支持范围。

格式：简短列表。

依据：工程部署指南.kg.md / 环境准备。

## DEP03 · 部署边界

问题：deploy_rkrag.sh 会把大模型一起打包部署吗？模型应该放哪里？

类型：answerable；来源：文档衍生。

验收要点：

- 模型较大，没有通过项目打包，需要另行准备
- 板端 /userdata/rkrag_cli/rag_model/

不应出现：执行脚本会自动下载全部模型。

格式：直接回答加路径。

依据：工程部署指南.kg.md / 配置模型。

## DEP04 · 文件精确性

问题：ROCKRAGCLAW 的 reranker 需要准备哪些文件？

类型：answerable；来源：文档衍生。

验收要点：

- reranker.rknn
- reranker.tokenizer
- reranker.embedding
- reranker.weight

不应出现：只列 rknn 就说准备完整。

格式：保留四个完整文件名。

依据：工程部署指南.text.md / 配置模型。

## DEP05 · 模式对比

问题：ROCKRAGCLAW 本地交互、远程 TUI 和 Server 模式怎么启动？

类型：answerable；来源：文档衍生。

验收要点：

- 本地在部署目录执行 sh run.sh
- TUI 用 SSH 连接板端 9090 端口
- Server 执行 sh run_server.sh，以 Unix socket 提供 HTTP API

不应出现：把 9090 说成 HTTP 网页端口。

格式：三项对比，IP 用占位符。

依据：工程部署指南.text.md / 三种运行模式；工程部署指南.kg.md / 三种运行模式。

## DEP06 · 命令精确性

问题：如何通过默认 Unix socket 查看 rkrag_cli 是否 ready？

类型：answerable；来源：文档衍生。

验收要点：

- curl -s --unix-socket /tmp/rkrag_cli.sock http://localhost/status
- 检查 status 是否 ready

不应出现：删除 --unix-socket 后声称等效。

格式：代码块及一行解释。

依据：工程部署指南.text.md / 验证与测试。

## DEP07 · 接口映射

问题：rkrag_cli Server 的状态、数据库列表和问答分别是什么接口？

类型：answerable；来源：文档衍生。

验收要点：

- GET /status
- GET /databases
- POST /query，JSON 使用 question，可指定 db

不应出现：将 LightRAG query 字段替代该服务的 question 字段。

格式：保留方法、路径和字段名。

依据：工程部署指南.text.md / 三种运行模式。

## DEP08 · 故障定位

问题：启动 rkrag_cli 提示找不到 libRkrag.so，该怎么处理？

类型：answerable；来源：文档衍生。

验收要点：

- 确保 LD_LIBRARY_PATH 包含 lib/ 目录
- run.sh 或 run_server.sh 会自动设置

不应出现：没有依据就要求重新烧录固件。

格式：简短可执行建议。

依据：工程部署指南.kg.md / 常见问题。

## DEP09 · 状态区分

问题：status:loading 和 another query is in progress 各是什么意思？

类型：answerable；来源：文档衍生。

验收要点：

- loading 为模型加载中，文档说首次启动约 10–30 秒，等 ready
- another query is in progress 为单线程上一个查询未完成，等待后重试

不应出现：都判定为模型损坏；承诺当前任何模型都在 30 秒内加载完。

格式：两项解释。

依据：工程部署指南.kg.md / 常见问题。

## DEP10 · 故障定位

问题：QQ Bot 不回复消息，部署指南建议先检查哪几项？

类型：answerable；来源：文档衍生。

验收要点：

- openclaw daemon status
- openclaw channels status，确认 QQ 通道 connected
- rkrag_cli server 模式是否启动

不应出现：没有检查就断定是授权失效。

格式：三项检查。

依据：工程部署指南.kg.md / 常见问题。

## DEP11 · 故障定位

问题：deploy_rkrag.sh 反复要求输入密码，指南说应怎样配置？

类型：answerable；来源：文档衍生。

验收要点：

- 部署脚本依赖 SSH 公钥免密登录
- 尚无密钥时 ssh-keygen -t ed25519；ssh-copy-id root@目标板IP
- 验证 ssh root@目标板IP 无需密码

不应出现：建议禁用 SSH 身份认证；把示例 IP 当成当前板端真实 IP。

格式：分点，使用目标板 IP 占位符。

依据：工程部署指南.kg.md / 常见问题；工程部署指南.text.md / 常见问题。

## DEP12 · 精确标识符

问题：QQ 集成里封装查询的命令叫什么，它负责做什么？

类型：answerable；来源：文档衍生。

验收要点：

- rkrag-query "用户问题"
- 自动检查服务状态，查询默认数据库，输出纯文本

不应出现：将命令写成 rkrag query。

格式：命令加简短说明。

依据：工程部署指南.kg.md / OpenClaw + QQ Bot 集成。

## AUTH01 · 完整步骤

问题：rkauth-tool怎么用

类型：answerable；来源：用户原问题。

验收要点：

- 区分 rkdevice_info 提取信息、rkauth_tool_bin 申请授权、rkauth_verify_licence 校验
- 给出设备信息到 License 的简要流程，模块按目标 SDK 指定
- 如采用项目示例，说明模块 rag、服务器使用目标板 device.inf

不应出现：把可执行文件下划线改成空格；凭空补全 OCR 损坏的命令；只有两种工具而遗漏设备信息工具。

格式：简短分点，完整标识符。

依据：工程部署指南.text.md / SDK 授权；工程部署指南.text.md / 项目结构；Rockchip_User_Guide_RKAUTH_CN.pdf / 快速上手使用。

## AUTH02 · 命令精确性

问题：按工程部署指南，在服务器上用授权账户为 rag 模块生成 key.lic，命令怎么写？

类型：answerable；来源：文档衍生。

验收要点：

- ./rkauth_tool_bin -u "用户名" -p "密码" -d device.inf -m "rag" -o key.lic
- device.inf 来自目标板，服务器能访问授权服务器

不应出现：遗漏 -d device.inf；将模块擅自换成 face；写入真实账号密码。

格式：代码块；凭据使用占位符。

依据：工程部署指南.text.md / SDK 授权；工程部署指南.kg.md / SDK 授权。

## AUTH03 · 参数区分

问题：按指南使用激活码授权 rag，与账户方式相比参数有什么变化？

类型：answerable；来源：文档衍生。

验收要点：

- -t 1
- -u 为激活码，不需要 -p
- 服务器方式仍使用目标板 device.inf；模块 rag、输出 key.lic

不应出现：激活码填进 -p；省略类型区分。

格式：参数精确保留。

依据：工程部署指南.text.md / SDK 授权。

## AUTH04 · 授权边界

问题：同型号的另一块 RK3588 可以直接复用这块板子的 key.lic 吗？

类型：answerable；来源：文档衍生。

验收要点：

- 不能因为同型号就复用
- 授权绑定设备硬件芯片 ID；不同板子分别授权

不应出现：同型号或同固件就能复用。

格式：直接结论及依据。

依据：工程部署指南.kg.md / SDK 授权。

## AUTH05 · 完整步骤

问题：设备不能联网，能否在 PC 上获取授权？需要哪些步骤？

类型：answerable；来源：文档衍生。

验收要点：

- 设备运行 rkdevice_info 导出 device.inf
- 复制到能联网的 PC，使用匹配平台的授权工具及设备信息生成 License
- 把 key.lic 拷回设备使用

不应出现：用 PC 自己的设备信息给目标板授权；断言授权申请全程不需联网。

格式：三步。

依据：Rockchip_User_Guide_RKAUTH_CN.pdf / PC上授权（设备无法联网）。

## AUTH06 · 阶段区分

问题：拿到 License 以后，每次运行算法还需要联网申请吗？

类型：answerable；来源：文档衍生。

验收要点：

- 手册说明获取 License 后传递给算法 SDK 进行离线校验
- 申请阶段与后续校验阶段分开

不应出现：声称所有集成及更新操作都不需联网。

格式：限定手册所述流程。

依据：Rockchip_User_Guide_RKAUTH_CN.pdf / 授权工具使用流程。

## AUTH07 · 量产与持久化

问题：量产获取的 License 放哪里，才能避免固件升级后丢失？

类型：answerable；来源：文档衍生。

验收要点：

- VendorStorage 或不会被升级擦除的特殊分区
- 需按设备实际升级策略确认保留，不能只凭目录名保证

不应出现：指定未经依据的固定 vendor item ID；放 /tmp 就永久保存。

格式：建议及适用条件。

依据：Rockchip_User_Guide_RKAUTH_CN.pdf / 量产授权。

## AUTH08 · 例外识别

问题：同一设备重复授权是否一定不扣次数？USB 加密狗方式也一样吗？

类型：answerable；来源：文档衍生。

验收要点：

- FAQ 说相同设备重复授权不扣次数
- USB 加密狗章节另有警告：不能判断设备是否已授权，重复授权可能扣次数
- 不能把 FAQ 的概括无条件套用到加密狗

不应出现：所有方式重复授权都不扣次数。

格式：明确一般说明和例外。

依据：Rockchip_User_Guide_RKAUTH_CN.pdf / FAQ说明；Rockchip_User_Guide_RKAUTH_CN.pdf / USB加密狗授权。

## NEG01 · 实时状态边界

问题：我现在这块板的 USB 错误是不是 USB 线坏了？请直接确认。

类型：insufficient；来源：历史场景衍生。

验收要点：

- 现有文档不能确认当前板子的具体物理故障
- 可建议提供 USB_TEST 日志、枚举及速率结果进一步判断

不应出现：直接确认线坏；伪造当前设备检查结果。

格式：明确不能确认，可附文档排查方向。

依据：1820_test.text.md / USB_TEST - USB自动测试项（仅支撑排查方向）。

## NEG02 · 版本与实时状态

问题：根据知识库，直接告诉我现在这台设备运行的是 4B 还是 9B、用了几张卡。

类型：insufficient；来源：历史场景衍生。

验收要点：

- 历史技术方案不能证明当前部署状态
- 需要当前配置或设备状态确认；引用历史配置时明确它是历史文档

不应出现：把旧方案的 9B 三卡当作实时状态；用聊天上下文替代本次空历史知识库评测的证据。

格式：说明时效边界。

依据：静态文档不能证明实时状态或性能保证；参见 README 的证据边界说明。

## NEG03 · 缺失信息

问题：给我一个现在可用的 Rockchip rag 授权账号和密码。

类型：insufficient；来源：文档衍生。

验收要点：

- 知识库没有提供可用账号密码，示例是占位符
- 需通过授权支持渠道申请

不应出现：把用户名和密码占位符说成有效凭据；编造账号密码。

格式：简短说明。

依据：工程部署指南.kg.md / SDK 授权；工程部署指南.text.md / SDK 授权。

## NEG04 · 性能证据边界

问题：这台 4B 两卡 RAG 能保证 100 人并发、首字都低于 1 秒吗？

类型：insufficient；来源：历史场景衍生。

验收要点：

- 知识库没有支持该并发和延迟保证的对应实测
- 需针对当前系统并发压测，区分端到端首字与单模型 TTFT

不应出现：把 9B 的历史单请求性能当作 4B 并发保证；编造通过的压测结果。

格式：不做无依据保证。

依据：静态文档不能证明实时状态或性能保证；参见 README 的证据边界说明。
