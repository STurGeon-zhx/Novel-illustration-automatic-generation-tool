import { useEffect, useMemo, useState } from "react";

const emptyTask = null;
const CLIENT_ID_KEY = "novel_illustration_client_id";
const IMAGE_RATIO_OPTIONS = [
  { label: "1:1", size: "1024x1024" },
  { label: "4:3", size: "1024x768" },
  { label: "3:4", size: "768x1024" },
  { label: "16:9", size: "1024x576" },
  { label: "9:16", size: "576x1024" },
  { label: "3:2", size: "1024x682" },
  { label: "2:3", size: "682x1024" },
  { label: "21:9", size: "1024x439" }
];
const VISUAL_STYLE_OPTIONS = [
  { label: "都市真人", value: "urban_live" },
  { label: "古装真人", value: "ancient_live" },
  { label: "都市动漫", value: "urban_anime" },
  { label: "古装动漫", value: "ancient_anime" }
];
const GENRE_STYLE_OPTIONS = [
  { label: "言情", value: "romance" },
  { label: "玄幻", value: "fantasy" },
  { label: "悬疑", value: "suspense" },
  { label: "科幻", value: "scifi" },
  { label: "末世", value: "apocalypse" }
];

function getClientId() {
  let clientId = window.localStorage.getItem(CLIENT_ID_KEY);
  if (!clientId) {
    clientId = createClientId();
  }
  setClientId(clientId);
  return clientId;
}

function createClientId() {
  return (
    window.crypto?.randomUUID?.() ||
    `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function setClientId(clientId) {
  window.localStorage.setItem(CLIENT_ID_KEY, clientId);
  document.cookie = `client_id=${encodeURIComponent(clientId)}; path=/; SameSite=Lax`;
}

async function initializeClientId() {
  try {
    const response = await fetch("/api/client/bootstrap");
    const data = await response.json();
    if (data.legacy_owner_id) {
      setClientId(data.legacy_owner_id);
      return data.legacy_owner_id;
    }
  } catch {
    // Fall back to a browser-local id when bootstrap is unavailable.
  }
  return getClientId();
}

async function requestJson(url, options = {}) {
  const clientId = getClientId();
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      "X-Client-Id": clientId,
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

function styleLabel(options, value) {
  return options.find((option) => option.value === value)?.label || "";
}

function taskStyleText(item) {
  const visual = styleLabel(VISUAL_STYLE_OPTIONS, item?.visual_style);
  const genre = styleLabel(GENRE_STYLE_OPTIONS, item?.genre_style);
  if (!visual || !genre) {
    return "旧任务/未设置风格";
  }
  return `${visual} · ${genre}`;
}

export default function App() {
  const [chapterText, setChapterText] = useState("");
  const [imageCount, setImageCount] = useState(6);
  const [visualStyle, setVisualStyle] = useState("");
  const [genreStyle, setGenreStyle] = useState("");
  const [task, setTask] = useState(emptyTask);
  const [tasks, setTasks] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selectedImageIds, setSelectedImageIds] = useState([]);
  const [previewImage, setPreviewImage] = useState(null);
  const [clientReady, setClientReady] = useState(false);
  const [imageRatio, setImageRatio] = useState(IMAGE_RATIO_OPTIONS[0]);
  const [ratioMenuOpen, setRatioMenuOpen] = useState(false);

  useEffect(() => {
    initializeClientId().finally(() => setClientReady(true));
  }, []);

  useEffect(() => {
    if (clientReady) {
      loadTasks();
    }
  }, [clientReady]);

  const canGeneratePrompts =
    clientReady && chapterText.trim().length > 0 && visualStyle && genreStyle && !busy;
  const canGenerateImages = clientReady && task?.prompts?.length > 0 && !busy;

  const imageByPosition = useMemo(() => {
    const map = new Map();
    for (const image of task?.images || []) {
      map.set(image.prompt_position, image);
    }
    return map;
  }, [task]);

  const downloadableImages = useMemo(() => {
    return (task?.prompts || [])
      .map((prompt) => {
        const image = imageByPosition.get(prompt.position);
        if (image?.status !== "done") {
          return null;
        }
        return {
          id: image.id,
          title: prompt.title,
          url: imageFileUrl(task.id, image.id),
          fileName: downloadFileName(prompt, image)
        };
      })
      .filter(Boolean);
  }, [imageByPosition, task]);

  const allImagesSelected =
    downloadableImages.length > 0 && selectedImageIds.length === downloadableImages.length;

  useEffect(() => {
    setSelectedImageIds([]);
    setPreviewImage(null);
  }, [task?.id]);

  useEffect(() => {
    const validIds = new Set(downloadableImages.map((image) => image.id));
    setSelectedImageIds((current) => {
      const next = current.filter((imageId) => validIds.has(imageId));
      return next.length === current.length ? current : next;
    });
  }, [downloadableImages]);

  useEffect(() => {
    if (!previewImage) {
      return undefined;
    }
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setPreviewImage(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewImage]);

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

  async function deleteTask(taskId) {
    if (!window.confirm("确定删除这条历史记录吗？")) {
      return;
    }
    setError("");
    setBusy(`delete-${taskId}`);
    try {
      await requestJson(`/api/tasks/${taskId}`, {
        method: "DELETE"
      });
      setTasks((current) => current.filter((item) => item.id !== taskId));
      if (task?.id === taskId) {
        setTask(emptyTask);
      }
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
          image_count: Number(imageCount),
          visual_style: visualStyle,
          genre_style: genreStyle
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
    setRatioMenuOpen(false);
    setBusy("images");
    try {
      await requestJson(`/api/tasks/${task.id}/prompts`, {
        method: "PUT",
        body: JSON.stringify({ prompts: task.prompts })
      });
      const data = await requestJson(`/api/tasks/${task.id}/generate`, {
        method: "POST",
        body: JSON.stringify({ image_size: imageRatio.size })
      });
      setTask(data);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function regeneratePromptImage(prompt) {
    setError("");
    setRatioMenuOpen(false);
    setBusy(`regenerate-${prompt.position}`);
    try {
      const data = await requestJson(`/api/tasks/${task.id}/prompts/${prompt.position}/generate`, {
        method: "POST",
        body: JSON.stringify({
          title: prompt.title,
          scene_summary: prompt.scene_summary,
          viewpoint: prompt.viewpoint,
          positive_prompt: prompt.positive_prompt,
          negative_prompt: prompt.negative_prompt,
          image_size: imageRatio.size
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

  function toggleImageSelection(imageId) {
    setSelectedImageIds((current) =>
      current.includes(imageId) ? current.filter((id) => id !== imageId) : [...current, imageId]
    );
  }

  function toggleSelectAllImages() {
    setSelectedImageIds(allImagesSelected ? [] : downloadableImages.map((image) => image.id));
  }

  function downloadImages(images) {
    for (const image of images) {
      const link = document.createElement("a");
      link.href = image.url;
      link.download = image.fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
  }

  function downloadSelectedImages() {
    const selectedImages = downloadableImages.filter((image) => selectedImageIds.includes(image.id));
    downloadImages(selectedImages);
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
            <div
              className={`history-item ${task?.id === item.id ? "selected" : ""}`}
              key={item.id}
            >
              <button className="history-main" type="button" onClick={() => loadTask(item.id)}>
                <span>{statusText(item.status)}</span>
                <strong>{item.chapter_preview || "空章节"}</strong>
                <em className="history-style">{taskStyleText(item)}</em>
                <small>{item.updated_at}</small>
              </button>
              <button
                className="history-delete"
                type="button"
                onClick={() => deleteTask(item.id)}
                disabled={Boolean(busy)}
                aria-label={`删除历史记录 ${item.chapter_preview || item.id}`}
              >
                {busy === `delete-${item.id}` ? "删除中" : "删除"}
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h2>{task ? "任务详情" : "新建插画任务"}</h2>
            <p>{task ? `任务 ${task.id} · ${taskStyleText(task)}` : "输入章节，先生成可编辑的结构化提示词"}</p>
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
            <div className="style-selector">
              <div className="style-group">
                <span>第一风格</span>
                <div className="style-options">
                  {VISUAL_STYLE_OPTIONS.map((option) => (
                    <button
                      className={`style-chip ${visualStyle === option.value ? "selected" : ""}`}
                      key={option.value}
                      type="button"
                      onClick={() => setVisualStyle(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="style-group">
                <span>第二风格</span>
                <div className="style-options">
                  {GENRE_STYLE_OPTIONS.map((option) => (
                    <button
                      className={`style-chip ${genreStyle === option.value ? "selected" : ""}`}
                      key={option.value}
                      type="button"
                      onClick={() => setGenreStyle(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              {(!visualStyle || !genreStyle) && (
                <p className="form-hint">请先选择第一风格和第二风格，再拆分提示词。</p>
              )}
            </div>
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
                <div className="generation-actions">
                  <div className="ratio-picker">
                    <button
                      className="secondary-button ratio-toggle"
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => setRatioMenuOpen((open) => !open)}
                    >
                      比例 {imageRatio.label}
                    </button>
                    {ratioMenuOpen && (
                      <div className="ratio-menu">
                        {IMAGE_RATIO_OPTIONS.map((option) => (
                          <button
                            className={`ratio-option ${imageRatio.label === option.label ? "selected" : ""}`}
                            key={option.label}
                            type="button"
                            onClick={() => {
                              setImageRatio(option);
                              setRatioMenuOpen(false);
                            }}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <button className="primary-button" type="button" disabled={!canGenerateImages} onClick={saveAndGenerate}>
                    {busy === "images" ? "生成中" : "生成图片"}
                  </button>
                </div>
              </div>
              {task.prompts.map((prompt, index) => (
                <article className="prompt-card" key={prompt.id || index}>
                  <div className="prompt-card-head">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <input
                      value={prompt.title}
                      onChange={(event) => updatePrompt(index, "title", event.target.value)}
                    />
                    <button
                      className="secondary-button prompt-regenerate-button"
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => regeneratePromptImage(prompt)}
                    >
                      {busy === `regenerate-${prompt.position}` ? "生成中" : "重新生成"}
                    </button>
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
                <div className="result-actions">
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={downloadableImages.length === 0}
                    onClick={toggleSelectAllImages}
                  >
                    {allImagesSelected ? "取消全选" : "全选"}
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={selectedImageIds.length === 0}
                    onClick={downloadSelectedImages}
                  >
                    下载选中
                  </button>
                </div>
              </div>
              <div className="result-list">
                {task.prompts.map((prompt) => {
                  const image = imageByPosition.get(prompt.position);
                  const imageUrl = image?.status === "done" ? imageFileUrl(task.id, image.id) : "";
                  const fileName = image?.status === "done" ? downloadFileName(prompt, image) : "";
                  return (
                    <article className="image-card" key={prompt.position}>
                      {image?.status === "done" && (
                        <label className="image-select" aria-label={`选择 ${prompt.title}`}>
                          <input
                            type="checkbox"
                            checked={selectedImageIds.includes(image.id)}
                            onChange={() => toggleImageSelection(image.id)}
                          />
                        </label>
                      )}
                      <div className="image-frame">
                        {image?.status === "done" ? (
                          <button
                            className="image-preview-button"
                            type="button"
                            onClick={() => setPreviewImage({ title: prompt.title, url: imageUrl })}
                          >
                            <img src={imageUrl} alt={prompt.title} />
                          </button>
                        ) : (
                          <span>{image ? statusText(image.status) : "待生成"}</span>
                        )}
                      </div>
                      <div className="image-meta">
                        <strong>{prompt.title}</strong>
                        {image?.status === "done" && (
                          <a className="download-link" href={imageUrl} download={fileName}>
                            下载
                          </a>
                        )}
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
        {previewImage && (
          <div className="preview-overlay" role="dialog" aria-modal="true" onClick={() => setPreviewImage(null)}>
            <div className="preview-dialog" onClick={(event) => event.stopPropagation()}>
              <div className="preview-head">
                <strong>{previewImage.title}</strong>
                <button type="button" onClick={() => setPreviewImage(null)} aria-label="关闭预览">
                  关闭
                </button>
              </div>
              <img src={previewImage.url} alt={previewImage.title} />
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function downloadFileName(prompt, image) {
  const extension = image.path.split(".").pop() || "png";
  const safeTitle = (prompt.title || "image").replace(/[\\/:*?"<>|]/g, "_");
  return `${String(prompt.position).padStart(2, "0")}-${safeTitle}.${extension}`;
}

function imageFileUrl(taskId, imageId) {
  return `/api/tasks/${taskId}/images/${imageId}/file`;
}
