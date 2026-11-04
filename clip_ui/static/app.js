"use strict";
const $ = id => document.getElementById(id);
const state = {clips: [], active: null, config: null, busy: false, submitting: false, folder: null, jobs: [], cropSubmission: null};
const labels = {extract: "Extração", review: "Revisão", crop: "Crop", pending: "Na fila", running: "Em execução", succeeded: "Concluído", failed: "Falhou", blocked: "Bloqueado"};
function node(tag, text, cls) {const el = document.createElement(tag); if(text !== undefined) el.textContent = text; if(cls) el.className = cls; return el;}
function error(err) {$("message").textContent = err.message || String(err); $("message").hidden = false;}
function clearError() {$("message").hidden = true;}
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json", "X-Clip-Token":state.config.token}, body:JSON.stringify(data)});
  const result = await response.json();
  if(!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
  return result;
}
function settings(clip) {return {video:clip.video, output_base:clip.destinations.base, engine:clip.engine, extension:clip.extension, crop_text:clip.crop_text.trim() || $("shared-crop").value.trim(), start_time:clip.start_time || null, end_time:clip.end_time || null, prepare_review:clip.prepare_review};}
function saveActive() {
  const c = state.active; if(!c) return;
  Object.assign(c, {start_time:$("start").value, end_time:$("end").value, crop_text:$("crop").value, engine:$("engine").value, extension:$("extension").value, prepare_review:$("prepare").checked});
}
function selectClip(c) {
  saveActive(); state.active = c; $("settings-empty").hidden = true; $("settings").hidden = false;
  $("clip-name").textContent = c.name;
  for(const [id,key] of [["start","start_time"],["end","end_time"],["crop","crop_text"],["engine","engine"],["extension","extension"]]) $(id).value = c[key];
  $("prepare").checked = c.prepare_review;
  $("inference").textContent = c.inferred ? "Extensão identificada no nome do vídeo. Você pode escolher outra." : "Extensão não identificada. TXT é o padrão; escolha outra se necessário.";
  $("extract-path").textContent = c.destinations.extraction; $("review-path").textContent = c.destinations.review; $("overwrite").hidden = !c.destinations.exists;
  renderClips();
}
function renderClips() {
  const list = $("clip-list"); list.replaceChildren();
  if(!state.clips.length) list.append(node("p", "Nenhum vídeo encontrado nesta pasta. Escolha outra pasta.", "empty"));
  for(const c of state.clips) {
    const row = node("div", undefined, `clip-row${state.active === c ? " active" : ""}`);
    const check = node("input"); check.type = "checkbox"; check.checked = c.selected; check.setAttribute("aria-label", `Selecionar ${c.name}`);
    check.addEventListener("change", () => {c.selected = check.checked; updateSelection();});
    const button = node("button", c.name, "clip-button"); button.type = "button"; button.setAttribute("aria-pressed", state.active === c ? "true" : "false");
    button.append(node("span", `${c.extension.toUpperCase()} · ${c.inferred ? "extensão identificada" : "extensão a definir"}`, "clip-meta"));
    button.addEventListener("click", () => selectClip(c)); row.append(check, button); list.append(row);
  }
  updateSelection();
}
function updateSelection() {
  const selected = state.clips.filter(c => c.selected);
  $("selected-count").textContent = `${selected.length} ${selected.length === 1 ? "selecionado" : "selecionados"}`;
  $("select-all").checked = !!selected.length && selected.length === state.clips.length;
  $("select-all").indeterminate = selected.length > 0 && selected.length < state.clips.length;
  $("run").disabled = !selected.length || state.busy || state.submitting;
  $("suggest").disabled = !state.active || state.busy || state.submitting;
  $("concurrency").disabled = state.busy || state.submitting;
  $("crop-reference").textContent = state.active ? `Vídeo de referência: ${state.active.name}. A sugestão usa o início e o fim definidos nos ajustes desse clip.` : "Escolha um clip na lista para testar o recorte.";
  renderCropStatus();
  $("run").textContent = state.busy ? "Fila em execução…" : "Iniciar seleção";
  $("review-note").hidden = $("action").value === "extract";
  const preview = $("run-preview"), wasOpen = !!preview.querySelector("details[open]"); preview.replaceChildren();
  if(selected.length) {
    const details = node("details"), summary = node("summary", `Conferir destinos dos ${selected.length} clips selecionados`), list = node("ul");
    for(const c of selected) list.append(node("li", `${c.name}: ${$("action").value === "review" ? c.destinations.review : c.destinations.extraction}${$("action").value === "combined" ? " → " + c.destinations.review : ""}${c.destinations.exists ? " — já existem resultados; a execução pode substituí-los" : ""}`));
    details.open = wasOpen; details.append(summary,list); preview.append(details);
  }
}
function renderCropStatus() {
  const status = $("crop-status"), button = $("suggest");
  button.textContent = "Sugerir crop";
  let text = "", url = null, failed = false;
  const submission = state.cropSubmission;
  const job = [...state.jobs].reverse().find(j => j.action === "crop" && j.clips.some(c => c.settings.video === state.active?.video));
  const clip = job?.clips.find(c => c.settings.video === state.active?.video);
  const stage = clip?.stages.find(s => s.name === "crop");
  if(submission?.video === state.active?.video && submission) {
    text = submission.text; failed = !!submission.error;
    if(!failed) button.textContent = "Enviando…";
  } else if(stage?.state === "pending" || stage?.state === "running") {
    text = stage.state === "pending" ? "Sugestão na fila. Aguarde o início da análise." : "Analisando os frames e preparando o preview. Aguarde; o link aparecerá aqui quando estiver pronto.";
    button.textContent = "Analisando crop…";
  } else if(clip?.preview_url) {
    text = "Sugestão pronta. Abra o preview para conferir e ajustar o recorte.";
    url = clip.preview_url;
  } else if(stage?.state === "failed" || stage?.state === "blocked") {
    text = stage.error || "Não foi possível preparar o preview. Consulte os logs em Acompanhamento.";
    failed = true;
  } else if(stage?.state === "succeeded") {
    text = "Este preview foi encerrado para outra operação. Clique em Sugerir crop para gerar um novo.";
  } else if(state.busy) {
    text = "Há outra operação em execução. Aguarde a fila terminar para sugerir o crop deste clip.";
  }
  // Polling must not replace the focused preview link or repeat live announcements.
  const signature = JSON.stringify([text, url, failed]);
  if(status.dataset.signature === signature) return;
  status.dataset.signature = signature;
  status.hidden = !text;
  status.classList.toggle("crop-error", failed);
  status.replaceChildren();
  if(text) status.append(node("p", text));
  if(url) {
    const link = node("a", "Abrir preview de crop ↗");
    link.href = url; link.target = "_blank"; link.rel = "noopener";
    status.append(link);
  }
}
async function loadClips(event) {
  event.preventDefault(); clearError();
  try {
    const query = new URLSearchParams({folder:$("folder").value}); if($("base").value.trim()) query.set("output_base",$("base").value.trim());
    const clips = await api(`/api/clips?${query}`);
    state.active = null; state.clips = clips.map(c => ({...c, selected:false, engine:"paddle", crop_text:"", start_time:"", end_time:"", prepare_review:true}));
    $("inventory-count").textContent = `${clips.length} vídeos encontrados`; $("settings").hidden = true; $("settings-empty").hidden = false;
    renderClips(); if(state.clips.length) selectClip(state.clips[0]);
  } catch(err) {error(err);}
}
async function browse(path) {
  try {const result = await api(`/api/folders?${new URLSearchParams({path})}`); state.folder = result; $("browse-path").textContent = result.path; $("folder-list").replaceChildren();
    for(const folder of result.folders) {const b = node("button", `▸ ${folder.name}`); b.onclick = () => browse(folder.path); $("folder-list").append(b);}
    if(!result.folders.length) $("folder-list").append(node("p", "Sem subpastas.", "hint"));
    if(!$("folder-dialog").open) $("folder-dialog").showModal();
  } catch(err) {error(err);}
}
async function submit(action) {
  clearError(); saveActive(); state.submitting = true;
  const cropVideo = action === "crop" ? state.active?.video : null;
  if(cropVideo) state.cropSubmission = {video:cropVideo, text:"Enviando solicitação de crop…"};
  updateSelection();
  try {
    const chosen = action === "crop" ? [state.active] : state.clips.filter(c => c.selected);
    const clips = chosen.map(c => {const s = settings(c); if(action === "crop") s.engine = $("crop-engine").value; return s;});
    const concurrency = action === "crop" ? 1 : Number($("concurrency").value);
    if(!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 500) throw new Error("Vídeos simultâneos deve ser um inteiro entre 1 e 500.");
    await api("/api/jobs", {action,clips,concurrency});
    if(cropVideo) state.cropSubmission = null;
    state.busy = true; await poll();
  } catch(err) {
    if(cropVideo) state.cropSubmission = {video:cropVideo, text:err.message || String(err), error:true};
    error(err);
  } finally {state.submitting = false; updateSelection();}
}
function durationText(seconds) {
  seconds = Math.max(0, seconds);
  if(seconds < 1) return `${seconds.toFixed(2)}s`;
  const whole = Math.floor(seconds), minutes = Math.floor(whole / 60);
  return minutes ? `${minutes}min ${whole % 60}s` : `${whole}s`;
}
function updateReviewTimers() {
  for(const timer of document.querySelectorAll("[data-review-start]")) {
    timer.textContent = `${durationText(Date.now() / 1000 - Number(timer.dataset.reviewStart))} decorridos`;
  }
}
function renderReviewSteps(row, clip) {
  let panel = row.querySelector(".review-progress");
  const steps = clip.review_steps || [];
  if(!steps.length) return;
  if(!panel) {
    panel = node("section", undefined, "review-progress");
    panel.setAttribute("aria-label", "Etapas e tempos da revisão");
    row.insertBefore(panel, row.querySelector("details"));
  }
  const signature = JSON.stringify(steps);
  if(panel.dataset.signature === signature) return;
  panel.dataset.signature = signature;
  panel.replaceChildren(node("strong", "Etapas da revisão"));
  const list = node("ol");
  for(const step of steps) {
    const item = node("li", undefined, `review-step ${step.state}`);
    const label = node("span", step.label), elapsed = node("span", undefined, "step-duration");
    if(step.state === "running") {
      elapsed.dataset.reviewStart = step.started_at;
      item.setAttribute("aria-current", "step");
    } else {
      elapsed.textContent = `${durationText(step.duration_seconds || 0)} · ${step.state === "failed" ? "falhou" : "concluída"}`;
    }
    item.append(label, elapsed); list.append(item);
  }
  panel.append(list);
  if(steps.some(s => s.state === "running" && s.label.includes("Aguardando resposta"))) {
    panel.append(node("p", "Solicitação em andamento. O tempo decorrido não indica o percentual processado pelo modelo.", "hint"));
  }
  updateReviewTimers();
}
function renderJobs(jobs) {
  const container = $("jobs");
  if(!jobs.length) return;
  const existing = new Map([...container.querySelectorAll("article.job")].map(row => [row.dataset.id, row]));
  for(const child of [...container.children]) if(!child.matches("article.job")) child.remove();
  let complete = 0, total = 0, position = 0;
  for(const job of [...jobs].reverse()) for(const c of job.clips) {
    let row = existing.get(c.id);
    existing.delete(c.id);
    if(!row) {
      row = node("article", undefined, "job"); row.dataset.id = c.id;
      const head = node("div",undefined,"job-head"), detail = node("details");
      head.append(node("span", c.settings.video.split(/[\\/]/).pop(), "job-name"), node("div",undefined,"stage-list"));
      detail.dataset.id = c.id;
      const logs = node("textarea", undefined, "job-logs");
      logs.readOnly = true; logs.rows = 12; logs.spellcheck = false;
      logs.placeholder = "Aguardando início…";
      logs.setAttribute("aria-label", `Logs de ${c.settings.video.split(/[\\/]/).pop()}`);
      const toolbar = node("div", undefined, "log-toolbar"), copy = node("button", "Copiar logs"), feedback = node("span");
      copy.type = "button"; copy.disabled = true; feedback.setAttribute("role", "status");
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(logs.value);
          feedback.textContent = "Logs copiados.";
        } catch {
          feedback.textContent = "Não foi possível copiar. Selecione o texto na caixa e use Ctrl+C.";
        }
      });
      toolbar.append(copy, feedback);
      detail.append(node("summary"), toolbar, logs, node("output",`Extração: ${c.extraction}\nRevisão: ${c.review}`));
      row.append(head, node("div",undefined,"job-messages"), detail);
    }
    if(container.children[position] !== row) container.insertBefore(row, container.children[position] || null);
    position++;
    renderReviewSteps(row, c);
    for(const s of c.stages) {total++; if(!["pending","running"].includes(s.state)) complete++;}
    const extractionFinished = c.stages.some(s => s.name === "extract" && s.state === "succeeded");
    const logText = c.logs.join(" ").replace(/\s+/g, " ");
    const extractionSummary = extractionFinished ? [
      logText.match(/Selection:.*?\d+ skipped after replacement/)?.[0],
      logText.match(/Reconstruction:.*?\(\d+ marked(?: \[OCR_UNCERTAIN\])?\)/)?.[0],
      logText.match(/Report: \d+ missing lines, \d+ uncertain, \d+ unextractable spans/)?.[0],
    ].filter(Boolean) : [];
    const reviewFinished = c.stages.some(s => s.name === "review" && s.state === "succeeded");
    const saved = c.logs.join("\n").match(/Saved\s+(\d+)\s+proposed edits,\s*(\d+)\s+unresolved issues and a diff in/);
    const reviewSummary = reviewFinished && saved ? `Saved ${saved[1]} proposed edits, ${saved[2]} unresolved issues and a diff in ${c.review}` : null;
    const signature = JSON.stringify([c.stages, c.preview_url, extractionSummary, reviewSummary]);
    if(row.dataset.status !== signature) {
      const stages = row.querySelector(".stage-list"), messages = row.querySelector(".job-messages");
      stages.replaceChildren(); messages.replaceChildren();
      for(const s of c.stages) {
        stages.append(node("span", `${labels[s.name]} · ${labels[s.state]}`, `stage ${s.state}`));
        if(s.error) messages.append(node("p",s.error,"error"));
      }
      if(c.preview_url) {const a = node("a","Abrir preview de crop ↗"); a.href = c.preview_url; a.target = "_blank"; a.rel = "noopener"; messages.append(a);}
      if(extractionFinished) {
        const result = node("div", undefined, "review-result extraction-result");
        result.setAttribute("role", "status");
        result.append(node("strong", "Extração concluída"));
        for(const text of extractionSummary) result.append(node("p", text));
        result.append(node("output", `Resultados em ${c.extraction}`));
        messages.append(result);
      }
      if(reviewFinished) {
        const result = node("div", undefined, "review-result");
        result.setAttribute("role", "status");
        result.append(node("strong", "Revisão concluída"), node("p", reviewSummary || `Resultados em ${c.review}`));
        messages.append(result);
      }
      row.dataset.status = signature;
    }
    const detail = row.querySelector("details"), pre = detail.querySelector(".job-logs"), summary = detail.querySelector("summary");
    const caption = `Logs e destinos · ${c.logs.length} linhas recentes`;
    if(summary.textContent !== caption) summary.textContent = caption;
    const text = c.logs.join("\n");
    if(pre.value !== text) {
      const top = pre.scrollTop, left = pre.scrollLeft;
      const start = pre.selectionStart, end = pre.selectionEnd, direction = pre.selectionDirection;
      const focused = document.activeElement === pre;
      const follow = detail.open && !(focused && start !== end) && pre.scrollHeight - pre.clientHeight - top <= 2;
      pre.value = text;
      if(focused) pre.setSelectionRange(start, end, direction);
      pre.scrollTop = follow ? pre.scrollHeight : top;
      pre.scrollLeft = left;
      detail.querySelector(".log-toolbar button").disabled = !text;
    }
  }
  for(const row of existing.values()) row.remove();
  $("queue-summary").textContent = `${complete}/${total} etapas encerradas${state.busy ? " · Em execução" : " · Fila finalizada"}`;
}
async function poll() {
  try {const jobs = await api("/api/jobs"); state.jobs = jobs; state.busy = jobs.some(j => !j.done); renderJobs(jobs); updateSelection();}
  catch(err) {
    $("queue-summary").textContent = "Conexão interrompida. Tentando reconectar…";
    state.busy = true; updateSelection();
    $("crop-status").hidden = false;
    $("crop-status").textContent = "Conexão interrompida. Tentando reconectar para acompanhar o crop…";
    delete $("crop-status").dataset.signature;
  }
}
async function init() {
  try {
    state.config = await api("/api/config");
    for(const engine of state.config.engines) {const o = node("option",engine); o.value = engine; $("engine").append(o);}
    for(const extension of state.config.extensions) {const o = node("option",extension.toUpperCase()); o.value = extension; $("extension").append(o);}
    $("source-form").onsubmit = loadClips;
    $("browse").onclick = () => browse($("folder").value || state.config.root);
    $("parent-folder").onclick = () => browse(state.folder.parent);
    $("use-folder").onclick = () => {$("folder").value = state.folder.path; $("folder-dialog").close(); $("source-form").requestSubmit();};
    $("select-all").onchange = () => {state.clips.forEach(c => c.selected = $("select-all").checked); renderClips();};
    $("settings").addEventListener("input",saveActive);
    $("extension").addEventListener("change",renderClips);
    $("action").onchange = updateSelection; $("run").onclick = () => submit($("action").value); $("suggest").onclick = () => submit("crop");
    await poll(); setInterval(poll,1500); setInterval(updateReviewTimers,1000);
  } catch(err) {error(err);}
}
init();
