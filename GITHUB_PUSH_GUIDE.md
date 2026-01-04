# 推送项目到 GitHub 的步骤

## 1️⃣ 检查 git 状态

```bash
cd g:\LWH\model\huanghe-demo-back
git status
```

如果 `config.ini` 已经被追踪，会在输出中显示。

## 2️⃣ 如果 config.ini 已被追踪，需要删除它

```bash
# 从 git 追踪中删除 config.ini（但保留本地文件）
git rm --cached config.ini

# 从 git 追踪中删除所有敏感配置文件
git rm --cached config*.ini *.config.json 2>/dev/null; true
```

## 3️⃣ 提交更改

```bash
git add .gitignore
git commit -m "chore: add config files to .gitignore to protect sensitive data"
```

## 4️⃣ 创建 GitHub 仓库（如果还没有）

访问 https://github.com/new 创建新仓库

## 5️⃣ 添加 GitHub 远程地址

```bash
# 替换 YOUR_USERNAME 和 YOUR_REPO 为你的用户名和仓库名
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

或者如果已经有远程地址：

```bash
git push origin main
```

## 6️⃣ 为新用户创建示例配置文件

创建 `config.ini.example` 文件，告诉其他开发者需要哪些配置：

```ini
[DEFAULT]
username = your_username
portalServer = 172.21.252.204
portalPort = 8061
managerServer = 172.21.252.204
managerPort = 8061
dataServer = 172.21.252.204
dataPort = 8061
mappingServer = 172.21.252.204
mappingPort = 8061
```

然后添加到 git：

```bash
git add config.ini.example
git commit -m "docs: add config.ini.example for reference"
git push
```

## 7️⃣ 完整的 git 命令序列

```bash
# 进入项目目录
cd g:\LWH\model\huanghe-demo-back

# 检查当前状态
git status

# 从追踪中删除 config.ini
git rm --cached config.ini

# 提交 .gitignore 更新
git add .gitignore
git commit -m "chore: add config.ini to .gitignore"

# 验证 config.ini 不在暂存区
git status

# 推送到 GitHub
git push origin main
```

## ⚠️ 如果 config.ini 已经被推送到 GitHub

如果 `config.ini` 已经在远程仓库中，运行上面的命令虽然会从本地 git 中移除它，但它仍然会存在于 git 历史中。你可以：

### 选项 A：使用 BFG（推荐）
```bash
# 安装 BFG (如果还没安装)
# 访问 https://rtyley.github.io/bfg-repo-cleaner/

# 清除所有 config.ini 文件
bfg --delete-files config.ini

# 清理垃圾
git reflog expire --expire=now --all && git gc --prune=now --aggressive

# 强制推送
git push --force
```

### 选项 B：全新开始
```bash
# 删除本地 .git 目录
rm -r .git

# 重新初始化
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## 📋 最佳实践清单

- ✅ `.gitignore` 已更新，包含 `config.ini`
- ✅ 创建 `config.ini.example` 文件作为参考
- ✅ 添加 README.md 说明如何配置
- ✅ 添加贡献指南 (CONTRIBUTING.md)
- ✅ 不推送任何敏感信息（密码、API密钥、服务器地址等）

## 🔐 敏感文件检查

在推送前，检查是否包含其他敏感文件：

```bash
# 查看即将推送的文件
git diff --cached --name-only

# 搜索可能的敏感信息
git log --all -S "password" --oneline
git log --all -S "secret" --oneline
git log --all -S "api_key" --oneline
```
