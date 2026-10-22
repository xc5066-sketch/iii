# Instagram 媒体选择下载（手机网页部署版）

## 功能
- 输入公开 Instagram 主页链接/用户名，尝试读取媒体条目。
- 手机端网格预览，每页 24 项。
- 勾选单项或选择当前页，支持清空选择。
- 仅下载所选条目并打包为 ZIP。
- 不添加水印，不自动去除源文件已有水印。
- 不收集 Instagram 密码或 Cookie。

## 限制
Instagram 会限制自动访问、要求登录或改变页面结构。yt-dlp 能否读取某个主页取决于平台响应；不保证所有账号、历史帖子、轮播图或视频都能读取。免费 Render 服务可能休眠、重启或限制运行时间。只下载你有权保存的内容，并遵守平台规则、版权和当地法律。

## 手机部署/更新（GitHub + Render）
1. 下载 ZIP 并解压。
2. 在手机浏览器打开 GitHub，进入之前部署网站的仓库。
3. 用 ZIP 中的文件替换旧文件：`app.py`、`requirements.txt`、`render.yaml`、`Procfile`、`.gitignore`、`README.md`。提交更改。
4. 如果 Render 已连接该仓库，通常会自动重新部署；否则进入 Render 服务页，点击 **Manual Deploy → Deploy latest commit**。
5. 部署完成后打开原来的 `.onrender.com` 网站并刷新。
6. 测试：输入公开主页 → 读取主页 → 勾选几项 → 下载所选 ZIP。

Render Build Command：`pip install -r requirements.txt`
Render Start Command：`gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT`
Health check path：`/health`

## 本地测试
Python 3.10+，运行 `pip install -r requirements.txt`，然后 `python app.py`，打开 `http://127.0.0.1:10000`。
