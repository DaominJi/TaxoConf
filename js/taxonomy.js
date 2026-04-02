/**
 * taxonomy.js — Topic taxonomy data structure and classification functions.
 */

export const taxonomy = [
  { id: "root", parent: null, label: "Information Retrieval", w: 0, leaf: false },
  { id: "retrieval_core", parent: "root", label: "Retrieval Core", w: 0.34, leaf: false },
  { id: "gen_interactive", parent: "root", label: "Generative & Interactive IR", w: 0.31, leaf: false },
  { id: "recsys", parent: "root", label: "Recommendation", w: 0.29, leaf: false },
  { id: "methods", parent: "root", label: "Representation & Graph Methods", w: 0.28, leaf: false },
  { id: "evaluation", parent: "root", label: "Evaluation & Responsible IR", w: 0.30, leaf: false },
  { id: "reliability", parent: "root", label: "Reliability & Security", w: 0.30, leaf: false },
  { id: "neural_rank", parent: "retrieval_core", label: "Neural Ranking & Re-ranking", w: 0.18, leaf: true },
  { id: "index_ann", parent: "retrieval_core", label: "Indexing & ANN Systems", w: 0.17, leaf: true },
  { id: "gen_rag", parent: "gen_interactive", label: "Generative Retrieval & RAG", w: 0.18, leaf: true },
  { id: "convo_ir", parent: "gen_interactive", label: "Conversational & Interactive IR", w: 0.16, leaf: true },
  { id: "seq_rec", parent: "recsys", label: "Sequential Recommendation", w: 0.17, leaf: true },
  { id: "rec_objective", parent: "recsys", label: "Recommendation Objectives", w: 0.16, leaf: true },
  { id: "graph_method", parent: "methods", label: "Graph-based Modeling", w: 0.17, leaf: true },
  { id: "repr_embed", parent: "methods", label: "Embedding & Representation Learning", w: 0.16, leaf: true },
  { id: "user_eval", parent: "evaluation", label: "User, Evaluation & Explainability", w: 0.17, leaf: true },
  { id: "fair_bias", parent: "evaluation", label: "Fairness & Bias Mitigation", w: 0.16, leaf: true },
  { id: "robust_secure", parent: "reliability", label: "Robustness & Security", w: 0.17, leaf: true }
];

export const keywordLexicon = {
  neural_rank: [
    ["dense retrieval", 2.2], ["retrieval", 0.6], ["ranking", 1.6], ["re-ranking", 1.7], ["reranking", 1.7],
    ["cross-encoder", 1.9], ["bi-encoder", 1.8], ["learning-to-rank", 1.8], ["ranker", 1.2]
  ],
  index_ann: [
    ["index", 1.6], ["indexing", 1.6], ["ann", 1.8], ["approximate nearest neighbor", 2.0],
    ["nearest neighbor", 1.7], ["multi-vector", 1.7], ["vector search", 1.5], ["latency", 1.3],
    ["throughput", 1.2], ["scalable", 1.2], ["infrastructure", 1.3], ["benchmark", 1.2]
  ],
  gen_rag: [
    ["rag", 2.3], ["retrieval-augmented", 2.2], ["retrieval augmented", 2.2], ["large language model", 1.9],
    ["llm", 1.9], ["generative retrieval", 2.0], ["fact-check", 1.8], ["question-answer", 1.7],
    ["reasoning", 1.5], ["prompt", 1.4], ["alignment", 1.3]
  ],
  convo_ir: [
    ["conversational", 2.0], ["dialogue", 1.8], ["interactive search", 1.8], ["voice search", 1.7],
    ["clarification", 1.3], ["search behavior", 1.4], ["search behaviour", 1.4], ["user simulation", 1.3]
  ],
  seq_rec: [
    ["sequential recommendation", 2.2], ["session-based recommendation", 2.2], ["session recommendation", 2.0],
    ["next-item", 1.8], ["next item", 1.8], ["click sequence", 1.4], ["temporal user", 1.3]
  ],
  rec_objective: [
    ["recommendation objective", 1.8], ["multi-objective", 1.7], ["personalization", 1.4], ["diversified", 1.4],
    ["item-item", 1.4], ["collaborative filtering", 1.8], ["recommender systems", 1.2], ["exposure", 1.2]
  ],
  graph_method: [
    ["graph neural", 2.1], ["gnn", 2.1], ["graph-based", 1.9], ["hypergraph", 2.0],
    ["knowledge graph", 1.9], ["proximity graph", 1.8], ["message passing", 1.4]
  ],
  repr_embed: [
    ["embedding", 1.9], ["representation learning", 1.8], ["neural embedding", 2.0], ["hyperbolic", 1.8],
    ["distance approximation", 1.8], ["latent space", 1.4], ["metric learning", 1.4], ["diffusion", 1.2]
  ],
  user_eval: [
    ["evaluation", 1.7], ["benchmark", 1.5], ["calibration", 1.7], ["explainability", 1.8], ["shap", 1.8],
    ["user study", 1.6], ["measurement", 1.3], ["effectiveness", 1.3], ["search behaviours", 1.4]
  ],
  fair_bias: [
    ["fairness", 2.1], ["bias", 2.0], ["equity", 1.8], ["debias", 1.8], ["source bias", 2.0],
    ["polarization", 1.7], ["responsible ai", 1.4]
  ],
  robust_secure: [
    ["robust", 1.9], ["robustness", 1.9], ["adversarial", 1.9], ["drift", 1.6], ["noise", 1.3],
    ["security", 1.7], ["cyber threat", 1.8], ["reliability", 1.6], ["trust", 1.3], ["verification", 1.3]
  ]
};

export const byId = Object.fromEntries(taxonomy.map((x) => [x.id, x]));

export const children = {};
taxonomy.forEach((n) => {
  if (!n.parent) return;
  if (!children[n.parent]) children[n.parent] = [];
  children[n.parent].push(n.id);
});

export const leafIds = taxonomy.filter((x) => x.leaf).map((x) => x.id);

export const descendants = {};
function collectLeaves(nodeId) {
  if (descendants[nodeId]) return descendants[nodeId];
  const node = byId[nodeId];
  if (node.leaf) {
    descendants[nodeId] = [nodeId];
    return descendants[nodeId];
  }
  descendants[nodeId] = (children[nodeId] || []).flatMap((c) => collectLeaves(c));
  return descendants[nodeId];
}
taxonomy.forEach((n) => collectLeaves(n.id));

export function normalizeDist(dist) {
  const out = {};
  let sum = 0;
  leafIds.forEach((id) => {
    const v = Math.max(0, Number(dist[id] || 0));
    out[id] = v;
    sum += v;
  });
  if (sum <= 0) {
    const u = 1 / leafIds.length;
    leafIds.forEach((id) => { out[id] = u; });
    return out;
  }
  leafIds.forEach((id) => { out[id] /= sum; });
  return out;
}

export function sparsify(dist, topK) {
  const sorted = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const keep = sorted.slice(0, topK);
  const out = {};
  leafIds.forEach((id) => { out[id] = 0; });
  let sum = 0;
  keep.forEach(([id, v]) => { out[id] = v; sum += v; });
  if (sum <= 0) return out;
  keep.forEach(([id]) => { out[id] /= sum; });
  return out;
}

export function treeWasserstein(a, b) {
  let d = 0;
  taxonomy.forEach((node) => {
    if (!node.parent) return;
    const delta = descendants[node.id].reduce((acc, leaf) => acc + (a[leaf] || 0) - (b[leaf] || 0), 0);
    d += node.w * Math.abs(delta);
  });
  return d;
}

export function similarity(a, b, topK = 4) {
  const dd = treeWasserstein(sparsify(a, topK), sparsify(b, topK));
  return Math.exp(-dd);
}

export function textToDist(text) {
  const lower = String(text || "").toLowerCase();
  const raw = {};
  leafIds.forEach((leaf) => { raw[leaf] = 0.02; });
  Object.entries(keywordLexicon).forEach(([leaf, kws]) => {
    kws.forEach((entry) => {
      const kw = Array.isArray(entry) ? String(entry[0] || "").toLowerCase() : String(entry || "").toLowerCase();
      const w = Array.isArray(entry) ? Number(entry[1] || 1) : 1;
      if (!kw) return;
      let idx = 0;
      while (true) {
        const found = lower.indexOf(kw, idx);
        if (found === -1) break;
        raw[leaf] += w;
        idx = found + kw.length;
      }
    });
  });
  return normalizeDist(raw);
}

export const hintRules = [
  { leaf: "neural_rank", re: /\b(dense retrieval|ranking|re-ranking|reranking|cross-encoder|bi-encoder|learning-to-rank)\b/g },
  { leaf: "index_ann", re: /\b(index|indexing|ann|approximate nearest neighbor|nearest neighbor|multi-vector|latency|throughput|infrastructure)\b/g },
  { leaf: "gen_rag", re: /\b(rag|retrieval-augmented|large language model|llm|generative|fact-check|reasoning|prompt|alignment)\b/g },
  { leaf: "convo_ir", re: /\b(conversational|dialogue|interactive search|voice search|clarification|search behavio[u]?r|user simulation)\b/g },
  { leaf: "seq_rec", re: /\b(sequential|session|next[- ]item|click sequence|temporal user)\b/g },
  { leaf: "rec_objective", re: /\b(recommendation objective|multi-objective|personalization|diversified|collaborative filtering|item-item|exposure)\b/g },
  { leaf: "graph_method", re: /\b(graph neural|gnn|graph-based|hypergraph|knowledge graph|proximity graph|message passing)\b/g },
  { leaf: "repr_embed", re: /\b(embedding|representation learning|neural embedding|hyperbolic|distance approximation|latent space|metric learning|diffusion)\b/g },
  { leaf: "user_eval", re: /\b(evaluation|benchmark|calibration|explainability|shap|user study|effectiveness|measurement)\b/g },
  { leaf: "fair_bias", re: /\b(fairness|bias|equity|debias|source bias|polarization|responsible ai)\b/g },
  { leaf: "robust_secure", re: /\b(robust|robustness|adversarial|drift|noise|security|cyber threat|reliability|trust|verification)\b/g }
];

export function inferTopicHintsFromText(text) {
  const lower = String(text || "").toLowerCase();
  const scores = {};
  leafIds.forEach((id) => { scores[id] = 0; });
  hintRules.forEach((rule) => {
    const matches = lower.match(rule.re);
    if (matches && matches.length) scores[rule.leaf] += matches.length;
  });
  const ranked = Object.entries(scores)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => id);
  if (!ranked.length) return ["neural_rank"];
  return ranked.slice(0, 4);
}

export function hintsToDist(hints) {
  const raw = {};
  leafIds.forEach((id) => { raw[id] = 0.01; });
  const uniq = [...new Set((Array.isArray(hints) ? hints : []).filter((h) => leafIds.includes(h)))];
  if (!uniq.length) return normalizeDist(raw);
  uniq.forEach((h, idx) => {
    raw[h] += Math.max(0.55, 1.2 - idx * 0.2);
  });
  return normalizeDist(raw);
}

export function blendDists(baseDist, hintDist, textWeight = 0.72) {
  const raw = {};
  leafIds.forEach((id) => {
    raw[id] = textWeight * (baseDist[id] || 0) + (1 - textWeight) * (hintDist[id] || 0);
  });
  return normalizeDist(raw);
}

export function avgDist(dists) {
  const raw = {};
  leafIds.forEach((l) => { raw[l] = 0; });
  if (!dists.length) return normalizeDist(raw);
  dists.forEach((d) => {
    leafIds.forEach((l) => { raw[l] += d[l] || 0; });
  });
  leafIds.forEach((l) => { raw[l] /= dists.length; });
  return normalizeDist(raw);
}

export const topicHintAlias = {
  "retrieval core": "neural_rank",
  neural_rank: "neural_rank",
  dense_rank: "neural_rank",
  dense: "neural_rank",
  retrieval: "neural_rank",
  ranking: "neural_rank",
  reranking: "neural_rank",
  "re-ranking": "neural_rank",
  index_ann: "index_ann",
  infra: "index_ann",
  indexing: "index_ann",
  "indexing & ann systems": "index_ann",
  "retrieval infrastructure": "index_ann",
  ann: "index_ann",
  "vector search": "index_ann",
  "generative ir": "gen_rag",
  "generative retrieval": "gen_rag",
  rag: "gen_rag",
  "nlp for ir": "gen_rag",
  llm: "gen_rag",
  conversational: "convo_ir",
  convo_ux: "convo_ir",
  "interactive search": "convo_ir",
  "conversational & interactive ir": "convo_ir",
  seqrec: "seq_rec",
  seq_rec: "seq_rec",
  "sequential recommendation": "seq_rec",
  sequential: "seq_rec",
  session: "seq_rec",
  recsys: "rec_objective",
  "recommender modeling": "rec_objective",
  recsys_model: "rec_objective",
  "recommendation objectives": "rec_objective",
  collab: "rec_objective",
  "collaborative filtering": "rec_objective",
  collaborative: "rec_objective",
  gnn: "graph_method",
  graph: "graph_method",
  graph_rep: "graph_method",
  "graph-based modeling": "graph_method",
  "graph-based learning": "graph_method",
  "graph representation learning": "graph_method",
  deepwalk: "repr_embed",
  embedding: "repr_embed",
  representation: "repr_embed",
  "embedding & representation learning": "repr_embed",
  user_eval: "user_eval",
  "user, evaluation & explainability": "user_eval",
  evaluation: "user_eval",
  robust: "robust_secure",
  robustness: "robust_secure",
  reliability: "robust_secure",
  fair: "fair_bias",
  fairness: "fair_bias",
  fair_xai: "fair_bias",
  bias: "fair_bias",
  explainability: "user_eval"
};

export function normalizeTopicHints(rawHints) {
  if (!rawHints) return [];
  const arr = Array.isArray(rawHints) ? rawHints : [rawHints];
  return [...new Set(arr
    .map((x) => String(x || "").trim().toLowerCase())
    .map((x) => topicHintAlias[x] || x)
    .filter((x) => leafIds.includes(x)))];
}

export function topicHintsLabel(hints) {
  const arr = normalizeTopicHints(hints);
  return arr.length ? arr.map((id) => byId[id].label).join(", ") : "N/A";
}

/* ── Submission / PC distribution helpers ─────────────────────────── */

export function submissionDist(sub) {
  const text = `${sub.title || ""} ${sub.abstract || ""}`;
  const base = textToDist(text);
  const hints = Array.isArray(sub.topic_hints) && sub.topic_hints.length
    ? normalizeTopicHints(sub.topic_hints)
    : inferTopicHintsFromText(text);
  const textWeight = hints.length ? 0.3 : 0.7;
  return blendDists(base, hintsToDist(hints), textWeight);
}

export function pcDist(pc) {
  const pubs = Array.isArray(pc.publication_history) ? pc.publication_history : [];
  const fallbackText = `${pc.name || ""} ${pc.title || ""} ${pc.role || ""}`;
  const sourceText = pubs.length
    ? pubs.map((p) => `${p.title || ""} ${p.abstract || ""}`).join(" ")
    : fallbackText;
  const base = pubs.length
    ? avgDist(pubs.map((p) => textToDist(`${p.title || ""} ${p.abstract || ""}`)))
    : textToDist(sourceText);
  const hints = Array.isArray(pc.topic_hints) && pc.topic_hints.length
    ? pc.topic_hints
    : inferTopicHintsFromText(sourceText);
  return blendDists(base, hintsToDist(hints), 0.74);
}

export function topTopicEntries(dist, limit = 4) {
  return leafIds
    .map((id) => ({ id, v: dist[id] || 0 }))
    .sort((a, b) => b.v - a.v)
    .slice(0, limit);
}

export function barsHtml(dist, cls = "") {
  return `
    <div class="bars">
      ${topTopicEntries(dist, 6).map((x) => `
        <div class="bar-row">
          <div>${byId[x.id].label}</div>
          <div class="bar-track"><div class="bar-fill ${cls}" style="width:${(x.v * 100).toFixed(2)}%"></div></div>
          <div class="mono">${(x.v * 100).toFixed(1)}%</div>
        </div>
      `).join("")}
    </div>
  `;
}
