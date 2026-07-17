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

## Windows RC 构建

RC 使用单文件 Windows EXE，并附带 ZIP、SHA-256 清单和离线启动报告：

```powershell
python scripts/build_windows_rc.py
```

独立 DPI 验证：

```powershell
python scripts/validate_rc_dpi.py
```

签名环境审计与失败关闭预检：

```powershell
python scripts/bootstrap_windows_signing_tools.py
python scripts/build_windows_rc.py --signing-audit
python scripts/build_windows_rc.py --require-signature --signing-preflight-only `
  --certificate-thumbprint <SHA1> `
  --timestamp-url <RFC3161_URL>
```

引导脚本会将经过固定 SHA-256 校验的 Microsoft Windows SDK Build Tools 解包到忽略提交的 `.build` 工具缓存。使用可信证书签名 RC 时，优先从 Windows 证书存储区按 thumbprint 选择硬件或系统保护的私钥。也可用 `--pfx`，密码必须通过 `GAS_EC_SIGN_PFX_PASSWORD` 环境变量提供。正式版晋级必须同时满足签名状态 `Valid`、可信时间戳、打包烟测通过和清单提交号一致。

内部一致性数据仅用于开发回归和历史格式兼容，不在用户界面或人可读交付报告中展示。
