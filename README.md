# 小说插画自动生成工具

局域网可用的一键小说插画生成工具。流程是输入小说章节，先调用 OpenAI 兼容文本模型拆分 1-10 条结构化生图提示词，人工审核或修改后，再调用 OpenAI 兼容生图模型逐张生成图片。

## 功能

- 输入一章小说正文并选择图片数量。
- 自动生成结构化提示词：标题、场景摘要、视角、正向提示词、负向提示词。
- 提示词可在前端审核和编辑。
- 批量生成图片，失败图片可单独重试。
- SQLite 保存任务历史，图片保存到本地 `outputs/`。
- 支持局域网访问，无登录，历史记录共享。

## 配置

复制 `.env.example` 为 `.env`，然后填入模型配置：

```ini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=replace-with-your-api-key
TEXT_MODEL=gpt-4.1-mini
IMAGE_MODEL=gpt-image-1
IMAGE_SIZE=1024x1024
```

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
