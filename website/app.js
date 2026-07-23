/* Cauzon site — minimal interactions. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // Mobile nav toggle
  const toggle = $("#navToggle");
  const links = $("#navLinks");
  toggle?.addEventListener("click", () => links.classList.toggle("open"));
  $$("#navLinks a").forEach((a) =>
    a.addEventListener("click", () => links.classList.remove("open"))
  );
})();
