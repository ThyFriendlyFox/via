// The page's script: the theme button and the copy button. Nothing else moves.

(() => {
  const root = document.documentElement;
  const metas = document.querySelectorAll('meta[name="theme-color"]');

  const toggle = document.querySelector("[data-theme-toggle]");
  const show = () => {
    const dark = root.classList.contains("dark");
    if (toggle) toggle.setAttribute("aria-pressed", String(dark));
  };
  show();
  if (toggle) {
    toggle.addEventListener("click", () => {
      const dark = !root.classList.contains("dark");
      // The swap is instant: no transition paints the old colours over the new.
      root.classList.add("theme-switching");
      root.classList.toggle("dark", dark);
      for (const m of metas) m.content = dark ? "#1b1917" : "#fbfaf7";
      try {
        localStorage.setItem("theme", dark ? "dark" : "light");
      } catch {}
      show();
      requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
    });
  }

  // Without a stored choice the page follows the system while it is open.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    let stored = null;
    try {
      stored = localStorage.getItem("theme");
    } catch {}
    if (stored) return;
    root.classList.toggle("dark", e.matches);
    show();
  });

  for (const button of document.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async () => {
      const pre = button.parentElement.querySelector("pre");
      // The commands without their prompts, 1 per line.
      const text = pre.textContent
        .split("\n")
        .map((line) => line.replace(/^\$ /, ""))
        .join("\n");
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return;
      }
      button.setAttribute("data-copied", "");
      setTimeout(() => button.removeAttribute("data-copied"), 1500);
    });
  }
})();
