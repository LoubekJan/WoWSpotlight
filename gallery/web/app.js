const dances = document.querySelector("#dances");
const status = document.querySelector("#status");
const reload = document.querySelector("#reload");
const pagination = document.querySelector("#pagination");
const previous = document.querySelector("#previous");
const next = document.querySelector("#next");
const pageLabel = document.querySelector("#page");
const idPattern = /^[a-f0-9]{64}$/;
const dateFormat = new Intl.DateTimeFormat("cs", { dateStyle: "medium" });
const durationFormat = new Intl.NumberFormat("cs", { maximumFractionDigits: 1 });
const svgNamespace = "http://www.w3.org/2000/svg";
const palettes = ["plum", "indigo", "olive", "rust"];
let page = 1;
let pages = 1;
let requestedPage = 1;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function svgElement(tag, attributes) {
  const node = document.createElementNS(svgNamespace, tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  return node;
}

function decoration(id) {
  const seed = Number.parseInt(id.slice(0, 4), 16);
  const shift = seed % 25;
  const art = element("div", `card-art ${palettes[seed % palettes.length]}`);
  const svg = svgElement("svg", {
    "aria-hidden": "true",
    viewBox: "0 0 400 110",
    preserveAspectRatio: "xMidYMid slice",
    fill: "none"
  });
  svg.append(
    svgElement("path", {
      d: "M0 22h400M0 55h400M0 88h400M40 0v110M100 0v110M160 0v110M220 0v110M280 0v110M340 0v110",
      stroke: "currentColor",
      opacity: ".15"
    }),
    svgElement("path", {
      d: `M-15 84C84 ${-10 + shift} 152 ${144 - shift} 237 58S331 ${12 + shift} 415 69`,
      stroke: "currentColor",
      "stroke-width": "2"
    }),
    svgElement("path", {
      d: `M-15 98C84 ${4 + shift} 152 ${158 - shift} 237 72S331 ${26 + shift} 415 83`,
      stroke: "currentColor",
      "stroke-dasharray": "4 6",
      opacity: ".6"
    }),
    svgElement("circle", { cx: "237", cy: "58", r: "4", fill: "currentColor" })
  );
  const label = element("code", "clip-id", id.slice(0, 10));
  label.title = id;
  art.append(svg, label);
  return art;
}

function danceCard(dance) {
  const card = element("li", "card");
  const body = element("div", "card-body");
  const date = new Date(dance.created_at_ms);
  const time = element("time", null, dateFormat.format(date));
  time.dateTime = date.toISOString();
  const metadata = element("p", "metadata");
  metadata.append(`${durationFormat.format(dance.duration_ms / 1000)} s · `, time);
  const download = element("a", "download", "Stáhnout tanec");
  download.href = `/api/dances/${dance.id}`;
  download.download = `${dance.id}.motion.json`;
  download.setAttribute("aria-label", `Stáhnout tanec ${dance.name}`);
  const arrow = element("span", null, "↓");
  arrow.setAttribute("aria-hidden", "true");
  download.append(arrow);
  body.append(element("h3", null, dance.name), metadata, download);
  card.append(decoration(dance.id), body);
  return card;
}

function isDance(dance) {
  return dance && typeof dance.id === "string" && idPattern.test(dance.id)
    && typeof dance.name === "string" && dance.name.trim().length > 0
    && Number.isSafeInteger(dance.created_at_ms) && dance.created_at_ms > 0
    && !Number.isNaN(new Date(dance.created_at_ms).getTime())
    && Number.isSafeInteger(dance.duration_ms) && dance.duration_ms > 0;
}

async function showPage(target) {
  requestedPage = target;
  reload.disabled = previous.disabled = next.disabled = true;
  status.hidden = false;
  status.textContent = "Načítám galerii…";
  dances.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(`/api/dances?page=${target}`, { signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Number.isSafeInteger(data.page) || !Number.isSafeInteger(data.pages)
        || data.page < 1 || data.page > data.pages || !Array.isArray(data.items)
        || data.items.length > 6 || !data.items.every(isDance)) {
      throw new Error("Unexpected gallery response");
    }
    page = data.page;
    pages = data.pages;
    requestedPage = page;
    dances.replaceChildren(...data.items.map(danceCard));
    status.textContent = data.items.length
      ? `Načtena stránka ${page} z ${pages}.`
      : "Galerie je zatím prázdná. Tance se objeví po dokončení převodu v ComfyUI.";
    status.classList.toggle("sr-only", data.items.length > 0);
    pagination.hidden = pages < 2;
    pageLabel.textContent = `${page} / ${pages}`;
  } catch {
    status.classList.remove("sr-only");
    status.textContent = "Galerii se nepodařilo načíst. Zkus ji obnovit.";
  } finally {
    dances.setAttribute("aria-busy", "false");
    reload.disabled = false;
    previous.disabled = page <= 1;
    next.disabled = page >= pages;
  }
}

reload.addEventListener("click", () => showPage(requestedPage));
previous.addEventListener("click", () => showPage(page - 1));
next.addEventListener("click", () => showPage(page + 1));
showPage(1);
