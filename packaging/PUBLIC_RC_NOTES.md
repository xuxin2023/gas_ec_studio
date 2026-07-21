## 公网预览版说明

这是 Windows 10/11 64 位候选版本，供功能体验、现场流程和导出结果验收使用。

### 下载

- 推荐下载 ZIP，解压后运行其中的 EXE。
- 也可以直接下载单文件 EXE。
- `SHA256SUMS.txt` 用于核对下载文件完整性。

### 安全提示

当前候选版本未进行商业代码签名，Windows 可能显示“未知发布者”或 SmartScreen 提示。请仅从本 GitHub Release 页面下载，并在运行前核对 SHA-256。正式稳定版仍要求有效代码签名和可信时间戳。

PowerShell 校验示例：

```powershell
Get-FileHash .\GasECStudio-*-win64.zip -Algorithm SHA256
```
