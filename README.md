# gas_ec_studio

`gas_ec_studio` 是一个全新的独立桌面软件骨架，用于气体分析仪接入、协议调试、实时采集、高频归档，以及为后续涡动协方差处理链路预留接口。

## 当前阶段能力

- PySide6 高端科学仪器工作台 UI
- 设备中心 / 实时采集 / 项目与站点 / 报告中心四大页面
- 操作员视图 / 工程师视图双视图切换
- Mode1 / Mode2 / ACK / 多帧粘连 / 截断 / 损坏帧解析
- 事务管理、原始协议 JSONL、高频 CSV、SQLite 元数据
- `SIM` 模拟设备，可在无真机环境直接演示

## 运行

```powershell
python -m pip install -e .[dev]
python -m app.main
```

## 测试

```powershell
pytest
```

## EddyPro Parity Gates

This repository keeps two EddyPro parity claims separate:

- `can_release_full_eddypro_parity`: strict official parity. It stays blocked until complete EddyPro/SmartFlux breadth, official EddyPro executable-run raw-to-final evidence, and accepted evidence-pack provenance pass together.
- `can_release_source_derived_functional_parity`: source-derived functional parity. It can pass when public real raw or hardware evidence is unavailable, using EddyPro-source-derived conformance fixtures, the accepted public official anchor, and delivery-chain tests.

Use:

```powershell
python scripts/run_eddypro_release_gate.py --workspace-root . --output artifacts/eddypro_release_gate/eddypro_release_gate.json --skip-acceptance
```

The second gate is a truthful engineering closure, not a substitute for official field numeric parity or hardware/vendor certification. Current public data discovery status is tracked in `docs/benchmark/public_ec_data_discovery.md`.
