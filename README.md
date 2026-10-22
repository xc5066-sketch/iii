# Instagram 公开主页媒体批量下载（手机网页部署版）

这是一个面向手机浏览器的轻量 Flask 网页。输入公开 Instagram 主页用户名/链接，后端调用 yt-dlp 尝试获取可访问的帖子媒体，并将文件打包成 ZIP。程序不会给文件添加水印，也不会自动去除源文件已有水印。

## 重要限制
- Instagram 会调整访问策略、要求登录或限制自动访问。不能保证每个主页都可访问，也不能保证完整获取全部历史帖子、轮播图和视频。
- 本项目只支持公开主页；没有 Cookie/密码输入功能，不要把账号密码提交给任何第三方网站。
- Render 免费服务可能休眠、重启、限时或限制可用磁盘/带宽。任务可能因主页过大、平台限制或服务重启而失败。
- 仅下载你有权保存的内容，并遵守 Instagram 条款、版权和当地法律。
- 本项目是代码包，不是已经上线的网站。部署完成后才会有你的专属网址。

## 用手机部署（尽量免费）
需要 GitHub 账号和 Render 账号。流程只需在手机浏览器完成；第一次配置需要手动上传项目文件。

1. 在手机浏览器打开 GitHub 并登录，创建一个新的 **Public** repository，例如 `instagram-public-media-tool`。
2. 解压本 ZIP。进入仓库，点 **Add file → Upload files**，把解压后的项目文件上传到仓库根目录。必须包含 `app.py`、`requirements.txt`、`render.yaml`、`Procfile`、`.gitignore`、`README.md`。不要只上传外层 ZIP 文件。
3. 打开 Render 并注册/登录： https://render.com/
4. 在 Render Dashboard 选择 **New → Web Service**，连接 GitHub，并选择刚才的仓库。
5. 如果 Render 自动读取 `render.yaml`，确认服务计划为 Free；否则手动设置：Runtime `Python`、Build Command `pip install -r requirements.txt`、Start Command `gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`，选择 Free 实例。
6. 点 **Deploy Web Service**，等待构建日志显示部署成功。打开 Render 分配的 `https://你的服务名.onrender.com` 网址。
7. 在网页输入公开主页链接并开始下载。完成后点击 ZIP 下载链接。手机浏览器可能会把文件保存到“下载”目录。

## 更新
更新 GitHub 仓库中的文件并提交后，Render 通常会自动重新部署。

## 本地开发（可选）
Python 3.10+；运行 `pip install -r requirements.txt`，再运行 `python app.py`，打开 `http://127.0.0.1:10000`。
