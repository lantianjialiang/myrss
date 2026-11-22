const formToken = document.querySelector("#reader-form-token");
const markAll = document.querySelector("[data-mark-all]");
const unreadCounts = new Map(
  Array.from(document.querySelectorAll("[data-unread-count]"), (count) => [count.dataset.unreadCount, count]),
);
const entries = Array.from(document.querySelectorAll("details[data-open-url]"));
let focused = -1;

function markRead(entry) {
  if (!entry.classList.contains("unread")) return;
  entry.classList.remove("unread");
  for (const key of ["all", entry.dataset.feedId]) {
    const count = unreadCounts.get(key);
    if (count) count.textContent = Math.max(0, Number(count.textContent) - 1);
  }
  const scopeCount = markAll && unreadCounts.get(markAll.dataset.markAll);
  if (scopeCount && Number(scopeCount.textContent) === 0) markAll.disabled = true;
}

async function openEntry(entry) {
  const content = entry.querySelector(".entry-content");
  if (entry.dataset.loading === "1") return;
  entry.dataset.loading = "1";
  if (!content.dataset.loaded) content.textContent = "正在载入正文…";
  try {
    const response = await fetch(entry.dataset.openUrl, {
      method: "POST",
      body: new URLSearchParams({ form_token: formToken.value }),
    });
    if (!response.ok) throw new Error(String(response.status));
    content.innerHTML = await response.text();
    content.dataset.loaded = "true";
    markRead(entry);
  } catch {
    if (!content.dataset.loaded) content.textContent = "正文加载失败。请刷新页面后重试。";
  } finally {
    delete entry.dataset.loading;
  }
}

entries.forEach((entry, index) => {
  entry.addEventListener("toggle", () => {
    if (entry.open && !entry.dataset.loaded) openEntry(entry);
  });
  entry.addEventListener("click", () => { focused = index; });
});

document.addEventListener("keydown", (event) => {
  if (!entries.length) return;
  const tag = document.activeElement && document.activeElement.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
  if (event.key === "j" || event.key === "k") {
    event.preventDefault();
    const step = event.key === "j" ? 1 : -1;
    focused = Math.max(0, Math.min(entries.length - 1, focused + step));
    const entry = entries[focused];
    entry.scrollIntoView({ block: "center", behavior: "smooth" });
    if (!entry.open) entry.open = true;
  } else if (event.key === "m" && focused >= 0) {
    event.preventDefault();
    const entry = entries[focused];
    if (!entry.dataset.loaded) {
      openEntry(entry).then(() => { entry.open = false; });
    } else {
      markRead(entry);
      entry.open = false;
    }
  }
});

document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  });
});

const selectAll = document.querySelector("#select-all");
if (selectAll) {
  selectAll.addEventListener("change", () => {
    document.querySelectorAll('input[name="feed_ids"]').forEach((box) => { box.checked = selectAll.checked; });
  });
}

// 左侧分类展开/合拢，状态保存到本地，下次打开仍保持。
const groupStateKey = "myrss.groups.collapsed";
let collapsedGroups;
try { collapsedGroups = new Set(JSON.parse(localStorage.getItem(groupStateKey) || "[]")); }
catch { collapsedGroups = new Set(); }

function applyGroup(button, collapsed) {
  const key = button.dataset.groupToggle;
  const items = document.querySelector(`[data-group-items="${key}"]`);
  if (!items) return;
  button.setAttribute("aria-expanded", String(!collapsed));
  items.hidden = collapsed;
}

document.querySelectorAll("[data-group-toggle]").forEach((button) => {
  const collapsed = collapsedGroups.has(button.dataset.groupToggle);
  applyGroup(button, collapsed);
  button.addEventListener("click", () => {
    const key = button.dataset.groupToggle;
    const nowCollapsed = button.getAttribute("aria-expanded") === "true";
    applyGroup(button, nowCollapsed);
    if (nowCollapsed) collapsedGroups.add(key);
    else collapsedGroups.delete(key);
    try { localStorage.setItem(groupStateKey, JSON.stringify([...collapsedGroups])); }
    catch { /* 无痕模式下存储不可用，不影响本次切换 */ }
  });
});

// 新订阅首次同步在后台进行，轮询其状态，一旦有结果就刷新页面显示文章/错误。
const syncPoll = document.querySelector("[data-sync-poll]");
if (syncPoll) {
  const feedId = syncPoll.dataset.syncPoll;
  let attempts = 0;
  const check = async () => {
    // 最多轮询约 2 分钟（后台抓取 RSSHub 源可能较慢），之后交由用户手动刷新。
    if (attempts++ >= 40) { syncPoll.textContent = "仍在同步，请稍后手动刷新。"; return; }
    try {
      const response = await fetch(`/feeds/${feedId}/status`);
      if (response.ok) {
        const data = await response.json();
        if (data.updated || data.error) { location.reload(); return; }
      }
    } catch { /* 网络抖动，继续轮询 */ }
    setTimeout(check, 3000);
  };
  setTimeout(check, 2000);
}
