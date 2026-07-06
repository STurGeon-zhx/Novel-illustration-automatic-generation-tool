# 小说插画自动生成工具

局域网可用的一键小说插画生成工具。流程是输入小说章节，先调用 Agnes 兼容文本模型拆分 1-10 条结构化生图提示词，人工审核或修改后，再调用 Agnes 生图模型逐张生成图片。

## 功能

- 输入一章小说正文并选择图片数量。
- 自动生成结构化提示词：标题、场景摘要、视角、正向提示词、负向提示词。
- 拆分出的正向提示词统一为动漫风格。
- 提示词可在前端审核和编辑。
- 批量生成图片，失败图片可单独重试。
- SQLite 保存任务历史，图片保存到本地 `outputs/`。
- 支持局域网访问，无登录；每台电脑/浏览器使用本地设备身份隔离历史记录。

## 配置

复制 `.env.example` 为 `.env`，然后填入模型配置：

```ini
OPENAI_BASE_URL=https://apihub.agnes-ai.com/v1
OPENAI_API_KEY=replace-with-your-api-key
TEXT_MODEL=agnes-2.0-flash
IMAGE_MODEL=agnes-image-2.1-flash
IMAGE_SIZE=1024x1024
IMAGE_RETURN_BASE64=true
APP_DATA_DIR=data
DATABASE_PATH=data/app.db
OUTPUTS_DIR=outputs
MODEL_TIMEOUT_SECONDS=120
MODEL_MAX_RETRIES=2
LEGACY_OWNER_ID=
```

`LEGACY_OWNER_ID` 只用于把启用隔离前已有的旧历史记录归属到指定设备。留空时旧历史不会出现在任何设备的历史列表中。

## 后端启动

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 前端启动

```powershell
cd frontend
npm install
npm run dev
```

局域网用户访问：

```text
http://你的局域网IP:5173
```

如果先执行 `npm run build`，后端检测到 `frontend/dist` 后也可以直接托管前端。

## 测试

```powershell
python -m unittest discover -s backend/tests
```
