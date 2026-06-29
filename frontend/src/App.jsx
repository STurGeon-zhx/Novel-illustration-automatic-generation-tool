import { useEffect, useMemo, useState } from "react";

const emptyTask = null;

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

function statusText(status) {
  return {
    created: "已创建",
    prompts_ready: "待生图",
    generating: "生成中",
    done: "已完成",
    failed: "失败",
    partial_failed: "部分失败",
    running: "生成中"
  }[status] || status;
}

export default function App() {
  const [chapterText, setChapterText] = useState("");
  const [imageCount, setImageCount] = useState(6);
  const [task, setTask] = useState(emptyTask);
  const [tasks, setTasks] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadTasks();
  }, []);

  const canGeneratePrompts = chapterText.trim().length > 0 && !busy;
  const canGenerateImages = task?.prompts?.length > 0 && !busy;

  const imageByPosition = useMemo(() => {
    const map = new Map();
    for (const image of task?.images || []) {
      map.set(image.prompt_position, image);
    }
    return map;
  }, [task]);

  async function loadTasks() {
    const data = await requestJson("/api/tasks");
    setTasks(data.tasks);
  }

  async function loadTask(taskId) {
    setError("");
    setBusy("loading");
    try {
      const data = await requestJson(`/api/tasks/${taskId}`);
      setTask(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function createTask() {
    setError("");
    setBusy("prompts");
    try {
      const data = await requestJson("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          chapter_text: chapterText,
          image_count: Number(imageCount)
        })
      });
      setTask(data);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function updatePrompt(index, field, value) {
    setTask((current) => ({
      ...current,
      prompts: current.prompts.map((prompt, itemIndex) =>
        itemIndex === index ? { ...prompt, [field]: value } : prompt
      )
    }));
  }

  async function saveAndGenerate() {
    setError("");
    setBusy("images");
    try {
      await requestJson(`/api/tasks/${task.id}/prompts`, {
        method: "PUT",
        body: JSON.stringify({ prompts: task.prompts })
      });
      const data = await requestJson(`/api/tasks/${task.id}/generate`, {
        method: "POST"
      });
      setTask(data);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function retryImage(imageId) {
    setError("");
    setBusy(`retry-${imageId}`);
    try {
      const data = await requestJson(`/api/tasks/${task.id}/images/${imageId}/retry`, {
        method: "POST"
      });
      setTask(data);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">绘</span>
          <div>
            <h1>小说插画生成工具</h1>
            <p>局域网工作台</p>
          </div>
        </div>
        <button className="nav-button active" type="button" onClick={() => setTask(emptyTask)}>
          新建任务
        </button>
        <div className="history-title">历史记录</div>
        <div className="history-list">
          {tasks.map((item) => (
            <button
              className={`history-item ${task?.id === item.id ? "selected" : ""}`}
              key={item.id}
              type="button"
              onClick={() => loadTask(item.id)}
            >
              <span>{statusText(item.status)}</span>
              <strong>{item.chapter_preview || "空章节"}</strong>
              <small>{item.updated_at}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{task ? "任务详情" : "新建插画任务"}</h2>
            <p>{task ? `任务 ${task.id}` : "输入章节，先生成可编辑的结构化提示词"}</p>
          </div>
          {task && <span className={`status ${task.status}`}>{statusText(task.status)}</span>}
        </header>

        {error && <div className="error-banner">{error}</div>}

        {!task && (
          <section className="input-panel">
            <label>
              <span>小说章节</span>
              <textarea
                value={chapterText}
                onChange={(event) => setChapterText(event.target.value)}
                placeholder="粘贴一章小说正文"
              />
            </label>
            <div className="input-actions">
              <label className="count-control">
                <span>图片数量</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={imageCount}
                  onChange={(event) => setImageCount(event.target.value)}
                />
              </label>
              <button className="primary-button" type="button" disabled={!canGeneratePrompts} onClick={createTask}>
                {busy === "prompts" ? "拆分中" : "拆分提示词"}
              </button>
            </div>
          </section>
        )}

        {task && (
          <section className="task-grid">
            <div className="prompt-column">
              <div className="section-heading">
                <h3>提示词审核</h3>
                <button className="primary-button" type="button" disabled={!canGenerateImages} onClick={saveAndGenerate}>
                  {busy === "images" ? "生成中" : "生成图片"}
                </button>
              </div>
              {task.prompts.map((prompt, index) => (
                <article className="prompt-card" key={prompt.id || index}>
                  <div className="prompt-card-head">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <input
                      value={prompt.title}
                      onChange={(event) => updatePrompt(index, "title", event.target.value)}
                    />
                  </div>
                  <label>
                    <span>场景摘要</span>
                    <textarea
                      value={prompt.scene_summary}
                      onChange={(event) => updatePrompt(index, "scene_summary", event.target.value)}
                    />
                  </label>
                  <label>
                    <span>视角</span>
                    <input
                      value={prompt.viewpoint}
                      onChange={(event) => updatePrompt(index, "viewpoint", event.target.value)}
                    />
                  </label>
                  <label>
                    <span>正向提示词</span>
                    <textarea
                      value={prompt.positive_prompt}
                      onChange={(event) => updatePrompt(index, "positive_prompt", event.target.value)}
                    />
                  </label>
                  <label>
                    <span>负向提示词</span>
                    <textarea
                      value={prompt.negative_prompt}
                      onChange={(event) => updatePrompt(index, "negative_prompt", event.target.value)}
                    />
                  </label>
                </article>
              ))}
            </div>

            <div className="result-column">
              <div className="section-heading">
                <h3>图片结果</h3>
              </div>
              <div className="result-list">
                {task.prompts.map((prompt) => {
                  const image = imageByPosition.get(prompt.position);
                  return (
                    <article className="image-card" key={prompt.position}>
                      <div className="image-frame">
                        {image?.status === "done" ? (
                          <img src={`/outputs/${image.path}`} alt={prompt.title} />
                        ) : (
                          <span>{image ? statusText(image.status) : "待生成"}</span>
                        )}
                      </div>
                      <div className="image-meta">
                        <strong>{prompt.title}</strong>
                        {image?.error_message && <p>{image.error_message}</p>}
                        {image?.status === "failed" && (
                          <button type="button" onClick={() => retryImage(image.id)} disabled={Boolean(busy)}>
                            {busy === `retry-${image.id}` ? "重试中" : "重试"}
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}
