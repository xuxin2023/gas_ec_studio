# 架构概览

## 分层

- `app/`: PySide6 工作台 UI，强调操作员与工程师双视图。
- `core/protocol/`: 独立协议内核，处理命令构造、分帧、ACK、Mode1/Mode2、系数与事务。
- `core/adapters/`: 串口与模拟设备适配层。
- `core/acquisition/`: 异步采集与缓存。
- `core/storage/`: JSONL / CSV / SQLite 落盘。
- `core/ec_rp` / `core/ec_fcc`: 后续算法接口骨架。
- `models/`: 统一领域模型。

## UI 原则

- 左导航、中央工作区、右侧上下文检查器、底部可折叠日志。
- 操作员只看到高频业务信息与常用操作。
- 协议细节、ACK、原始帧和事务追踪收纳到工程师视图与右侧检查器。

## 数据流

1. 设备连接配置进入 `DeviceConnectionConfig`
2. 采集层通过适配器读取协议流
3. `FrameSplitter` 与 Mode1/Mode2 解析器输出标准化帧
4. JSONL/CSV/SQLite 同步归档
5. UI 订阅最新帧、事务和日志
