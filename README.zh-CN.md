# droid-byok

[English](README.md) | [简体中文](README.zh-CN.md)

`droid-byok` 是一个用于管理 Factory Droid BYOK Provider、上游模型和默认模型的
全屏终端界面（TUI）与命令行工具。它直接管理 `~/.factory/settings.json` 中的
自定义模型配置。

## 功能

- 新增、编辑、删除和激活 BYOK Provider。
- 从上游获取模型列表，并选择需要加入的模型。
- 搜索 Provider 和上游模型。
- 配置变更时保留并修复 Droid 模型引用。
- 并发检测 Provider 端点，并显示结构化健康状态。
- 写入前自动备份 `settings.json`。
- 支持宽屏和小终端的响应式 truecolor TUI。

## 系统要求

- Python 3.10 或更高版本（仅 Python 安装方式需要）
- Factory Droid
- 支持 UTF-8 的终端

## 安装

### 独立二进制安装

Linux 或 macOS 用户可以直接安装独立二进制，不需要 Python：

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | bash
```

安装指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | \
  DROID_BYOK_VERSION=v0.3.1 bash
```

安装脚本会自动识别操作系统和 CPU 架构，从 GitHub Releases 下载对应二进制，
验证 SHA-256 后安装到 `~/.local/bin`。可以通过
`DROID_BYOK_INSTALL_DIR` 指定其他安装目录。

### pipx 安装

也可以使用 `pipx` 安装 Python 包：

```bash
pipx install .
droid-byok
```

直接从 GitHub 安装：

```bash
pipx install git+https://github.com/despriber/droid-byok.git
```

开发模式运行：

```bash
python3 -m pip install -r requirements.txt
./droid-byok
```

## 使用

启动 TUI：

```bash
droid-byok
```

常用 CLI 命令：

```bash
droid-byok provider list
droid-byok provider current
droid-byok provider speedtest
droid-byok models list
droid-byok --help
```

常用 TUI 快捷键：

- `/`：筛选 Provider
- `f`：获取上游模型
- `u`：设置默认 Provider/模型
- `m`：查看 live models
- `?`：打开帮助

## 数据与安全

运行时配置保存在源码目录之外：

```text
~/.factory/settings.json
~/.factory/droid-byok/providers.json
~/.factory/droid-byok/backups/
```

这些文件可能包含 API Key，请勿提交到 Git 或加入 Release。项目的 `.gitignore`
已经排除这些文件，仓库中的 `providers.example.json` 只展示空配置结构。

可以使用以下环境变量覆盖默认路径：

- `FACTORY_HOME`
- `DROID_SETTINGS`
- `DROID_BYOK_STORE`
- `DROID_BYOK_BACKUP_DIR`

## 构建 Python 发布包

```bash
python3 -m pip install build
python3 -m build
```

wheel 和源码包会生成在 `dist/` 中。

## 发布 GitHub Release

仓库包含 GitHub Actions Release 工作流。推送 `v*` 标签时会自动构建 Python 包和
Linux/macOS 的 x86_64/arm64 独立二进制，并上传到 GitHub Releases。

```bash
git tag v0.3.1
git push origin v0.3.1
```

也可以使用 GitHub CLI 手动上传本地构建产物：

```bash
gh release create v0.3.1 dist/* \
  --title "droid-byok v0.3.1" \
  --notes "Initial public release"
```

## 许可证

MIT
