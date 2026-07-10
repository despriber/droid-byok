# droid-byok

[English](README.md) | [简体中文](README.zh-CN.md)

在终端里管理 **Factory Droid 的 BYOK**（Bring Your Own Key）。

如果你在用 [Factory Droid](https://docs.factory.ai/)，又接了自己的 API Key、OpenAI 兼容中转、Anthropic 接口，或者各种模型网关，多半迟早会开始手改 `~/.factory/settings.json`。改一次还行；Provider 一多、默认模型来回切、`customModels` 引用再坏掉几次，就挺烦的。

`droid-byok` 就是干这事的：全屏 TUI + 一套小 CLI。

- 保存多个 BYOK **Provider 配置**
- 从上游 `/models` 拉模型目录
- 写进 Droid 正在用的 `customModels`
- 切换默认模型，尽量不搅乱其他配置
- 端点不通或太慢时，直接测连通性和延迟

思路参考过 `cc-switch` 这类工具，但目标是 Droid 自己的 BYOK 结构。

## 为什么要有这个

Droid 的 BYOK 能力本身没问题，日常多 Provider 切换却还是偏“手搓 JSON”：

| 痛点 | droid-byok 怎么处理 |
| --- | --- |
| 多个 Key / Base URL | 做成可命名的 Provider 配置 |
| 模型一个个手填 | 拉取上游模型列表，勾选即可 |
| 默认模型切换麻烦 | 一个快捷键 / 一条命令 |
| 改完配置引用坏掉 | 尽量修复 session / mission 相关模型引用 |
| 不知道端点还活着没有 | 并发 speedtest / 健康探测 |
| 怕把 settings 改炸 | 写盘前自动备份 `settings.json` |

方便检索的关键词：**Factory Droid**、**Droid BYOK**、**自带 Key**、**customModels**、**settings.json**、**OpenAI 兼容接口**、**Anthropic BYOK**、**模型中转**、**LLM 网关**、**模型切换 TUI**。

## 功能

- Textual 全屏 truecolor TUI，小终端也能用
- 适合脚本和快速操作的 CLI
- Provider 增删改查、设为默认
- 把当前 live `settings.json` 导入成 Provider
- 拉取上游模型（`/models`，兼容常见 `/v1/models`）
- 搜索 / 过滤 Provider 和模型
- 设置 Droid session 默认模型；若存在 mission 相关字段会一并同步
- 尽量保留稳定的 `custom:*` 模型 ID
- 并发探测端点状态和延迟
- 原子写入 + 带时间戳备份
- API Key 支持明文，也支持 `${ENV_VAR}`

## 环境要求

- 已安装 Factory Droid，并使用 `~/.factory/settings.json`
- 支持 UTF-8 的终端
- 走 Python 安装时需要 Python 3.10+
- 独立二进制**不需要** Python

## 安装

### 一键安装（Linux / macOS 二进制）

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | bash
```

指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | \
  DROID_BYOK_VERSION=v0.3.2 bash
```

脚本会识别系统与架构，从 GitHub Releases 下载对应二进制，校验 SHA-256，默认装到 `~/.local/bin`（可用 `DROID_BYOK_INSTALL_DIR` 改目录）。

### pipx / Python 包

```bash
# 本地克隆后
pipx install .

# 直接从 GitHub
pipx install git+https://github.com/despriber/droid-byok.git
```

开发运行：

```bash
python3 -m pip install -r requirements.txt
./droid-byok
```

从 Release 装 wheel：

```bash
pipx install droid_byok-0.3.2-py3-none-any.whl
```

## 快速开始

```bash
# 默认进 TUI
droid-byok

# 或者纯命令行
droid-byok provider add \
  --id openrouter \
  --name openrouter \
  --base-url https://openrouter.ai/api/v1 \
  --api-key "$OPENROUTER_API_KEY" \
  --model anthropic/claude-sonnet-4 \
  --apply

droid-byok use openrouter
droid-byok models list
```

TUI 里比较自然的第一次流程：

1. `a` 添加 Provider（Base URL + API Key）
2. `f` 拉取上游模型并勾选
3. `Enter` / `u` 设为 Droid 默认
4. 重启或重开 Droid，模型就会出现

## CLI

```bash
droid-byok                        # TUI
droid-byok interactive
droid-byok tui

droid-byok provider list
droid-byok provider current
droid-byok provider show <id>
droid-byok provider add --id ... --base-url ... --api-key ... --model ...
droid-byok provider delete <id>
droid-byok provider default <id> [--model <name>]
droid-byok provider switch <id>   # default 的别名
droid-byok provider import-live   # 把当前 live settings 存成 Provider
droid-byok provider speedtest [id]

droid-byok use <id> [--model <name>]
droid-byok models list
droid-byok models show
droid-byok models default <id|name|displayName>
droid-byok help
droid-byok -V
```

写入 Droid 配置时支持的 provider 类型：

- `generic-chat-completion-api`（默认，OpenAI 兼容）
- `openai`
- `anthropic`

## TUI 快捷键

| 按键 | 作用 |
| --- | --- |
| `↑` `↓` / `j` `k` | 移动 |
| `Enter` / `u` | 设为默认 Provider |
| `a` | 新增 |
| `e` | 编辑 |
| `d` | 删除 |
| `i` | 导入 live settings |
| `f` | 拉取上游模型 |
| `m` | 查看 live `customModels` |
| `t` | Speedtest |
| `/` | 过滤 |
| `r` | 刷新 |
| `?` | 帮助 |
| `q` | 退出 |

## 和 Droid 的对应关系

| 路径 | 作用 |
| --- | --- |
| `~/.factory/settings.json` | Droid 正在使用的配置（`customModels`、session 默认模型、mission 模型等） |
| `~/.factory/droid-byok/providers.json` | 本地 Provider 配置库 |
| `~/.factory/droid-byok/backups/` | 写盘前的 `settings.json` 备份 |

可用环境变量覆盖：

- `FACTORY_HOME`
- `DROID_SETTINGS`
- `DROID_BYOK_STORE`
- `DROID_BYOK_BACKUP_DIR`

`droid-byok` 不替代 Droid，只管理 Droid 已经支持的 BYOK Provider / 模型配置。

## 安全说明

Provider 配置和 settings 里可能有 API Key。

- 不要提交 `~/.factory/**`
- 不要把真实的 `providers.json` / `settings.json` 贴到 issue 或 Release
- 能用 `${ENV_VAR}` 就尽量用
- 仓库里只有空的 `providers.example.json` 示例结构

写入是原子的（先写临时文件再替换），相关文件会尽量用 `0600` 权限。

## 构建与发布

```bash
python3 -m pip install build
python3 -m build   # dist/ 下生成 wheel 和 sdist
```

推送 `v*` 标签会触发 GitHub Actions，自动构建 Python 包和 Linux/macOS 的 x86_64/arm64 二进制，并上传到 Releases：

```bash
git tag v0.3.2
git push origin v0.3.2
```

## 相关链接

- 仓库：https://github.com/despriber/droid-byok
- Factory 文档：https://docs.factory.ai/
- Factory BYOK 概览：https://docs.factory.ai/cli/byok/overview

## 许可证

MIT
