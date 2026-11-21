const formToken = document.querySelector("#reader-form-token");
const markAll = document.querySelector("[data-mark-all]");
const unreadCounts = new Map(
  Array.from(document.querySelectorAll("[data-unread-count]"), (count) => [count.dataset.unreadCount, count]),
);

document.querySelectorAll("details[data-open-url]").forEach((entry) => {
  let loading = false;
  const content = entry.querySelector(".entry-content");
  entry.addEventListener("toggle", async () => {
    if (!entry.open || loading) return;
    loading = true;
    if (!content.dataset.loaded) content.textContent = "正在载入正文…";
    try {
      const response = await fetch(entry.dataset.openUrl, {
        method: "POST",
        body: new URLSearchParams({ form_token: formToken.value }),
      });
      if (!response.ok) throw new Error(String(response.status));
      content.innerHTML = await response.text();
      content.dataset.loaded = "true";
      if (entry.classList.contains("unread")) {
        entry.classList.remove("unread");
        for (const key of ["all", entry.dataset.feedId]) {
          const count = unreadCounts.get(key);
          if (count) count.textContent = Math.max(0, Number(count.textContent) - 1);
        }
        const scopeCount = markAll && unreadCounts.get(markAll.dataset.markAll);
        if (scopeCount && Number(scopeCount.textContent) === 0) markAll.disabled = true;
      }
    } catch {
      if (!content.dataset.loaded) content.textContent = "正文加载失败。请刷新页面后重试。";
    } finally {
      loading = false;
    }
  });
});
