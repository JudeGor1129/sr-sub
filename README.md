# sr-sub

把小火箭节点做成**固定地址、自动更新**的订阅：GitHub Actions 每小时跑一次脚本，抓源、去重、测活，把结果写到 `docs/sub.txt`，由 GitHub Pages 对外提供。

## 部署（三步）

**1. 建仓库**

在 GitHub 上新建一个 **Public** 仓库，名字随意，比如 `sr-sub`。别选 Private——Pages 免费版不支持私有仓库对外发布。

**2. 上传文件**

把本目录下的所有内容传上去，注意 `.github/` 是个隐藏目录，别漏了。用命令行最省事：

```bash
git init
git add -A
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/sr-sub.git
git push -u origin main
```

**3. 开启 Pages**

仓库 → Settings → Pages → Source 选 **Deploy from a branch** → Branch 选 `main`、目录选 `/docs` → Save。

等一两分钟，订阅地址就是：

```
https://<你的用户名>.github.io/sr-sub/sub.txt
```

如果不方便访问 `github.io`，用 jsDelivr 镜像（有缓存，更新会延迟约 12 小时）：

```
https://cdn.jsdelivr.net/gh/<你的用户名>/sr-sub@main/docs/sub.txt
```

## 小火箭里怎么用

首页右上角 **+** → 类型选 **Subscribe（订阅）** → URL 填上面那个地址 → 保存。之后下拉刷新就会重新拉取。

## 加自己的源

编辑 `sources.txt`，每行一个订阅地址或仓库内文件路径，`#` 开头是注释：

```
nodes_base.txt
https://某个订阅地址
```

改完 push，Actions 会自动重跑。

## 可调参数

在 `.github/workflows/update.yml` 的 `env` 里改：

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHECK_TIMEOUT` | 3 | 测活超时秒数 |
| `CHECK_WORKERS` | 64 | 测活并发数 |
| `MAX_NODES` | 600 | 订阅最多保留节点数 |

## 本地跑一次

```bash
python3 scripts/update.py              # 完整流程（含测活）
SKIP_CHECK=1 python3 scripts/update.py # 只合并去重，不测活
```

产物在 `docs/`：`sub.txt` 是 base64 订阅内容，`nodes.txt` 是明文列表。

## 说明

测活只做 TCP 端口连通性判断，能连上不代表服务一定可用（TLS 握手、账号有效期都可能让节点失效）。免费节点的生命周期通常只有几天，建议在 `sources.txt` 里配置多个源，让订阅能持续补充新节点。
